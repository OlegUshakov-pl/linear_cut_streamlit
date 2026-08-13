"""
Калькулятор линейного раскроя (1D Cutting Stock)
Современная версия на Streamlit + PuLP / OR-Tools
"""

import streamlit as st
import pandas as pd
import numpy as np
from typing import List, Dict, Tuple, Optional
from collections import Counter
import io

# Попытка использовать OR-Tools, иначе PuLP
try:
    from ortools.linear_solver import pywraplp
    SOLVER_BACKEND = "ortools"
except ImportError:
    import pulp
    SOLVER_BACKEND = "pulp"


st.set_page_config(
    page_title="Линейный раскрой",
    page_icon="✂️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
#  Ядро оптимизации
# ============================================================

def generate_patterns(
    piece_lengths: List[int],
    stock_length: int,
    max_pieces_per_bar: int = 20,
) -> List[Tuple[int, ...]]:
    """
    Генерирует все разумные паттерны раскроя (комбинации деталей,
    которые помещаются в один хлыст).
    Используется рекурсивный перебор с отсечением.
    """
    n = len(piece_lengths)
    patterns = []

    def rec(start: int, remaining: int, current: List[int]):
        if current:
            patterns.append(tuple(sorted(current, reverse=True)))
        if len(current) >= max_pieces_per_bar:
            return
        for i in range(start, n):
            L = piece_lengths[i]
            if L <= remaining:
                current.append(L)
                rec(i, remaining - L, current)  # можно брать ту же деталь ещё
                current.pop()

    rec(0, stock_length, [])
    # Убираем дубликаты
    unique = list(set(patterns))
    return unique


def solve_cutting_stock_pulp(
    demands: Dict[int, int],
    stock_length: int,
    time_limit: int = 30,
) -> Tuple[List[Dict], int]:
    """
    Решает задачу раскроя через генерацию паттернов + ILP (PuLP).
    Возвращает список схем и общее количество хлыстов.
    """
    import pulp

    lengths = sorted(demands.keys(), reverse=True)
    if not lengths:
        return [], 0

    # Генерируем паттерны
    patterns = generate_patterns(lengths, stock_length)
    if not patterns:
        return [], 0

    # Ограничиваем количество паттернов, если их слишком много
    if len(patterns) > 3000:
        # Оставляем самые плотные
        patterns = sorted(patterns, key=lambda p: sum(p), reverse=True)[:3000]

    # Модель
    prob = pulp.LpProblem("CuttingStock", pulp.LpMinimize)

    # Переменные: сколько раз использовать каждый паттерн
    x = [pulp.LpVariable(f"p_{i}", lowBound=0, cat="Integer") for i in range(len(patterns))]

    # Цель: минимум хлыстов
    prob += pulp.lpSum(x)

    # Ограничения спроса
    for length, qty in demands.items():
        prob += (
            pulp.lpSum(x[i] * patterns[i].count(length) for i in range(len(patterns)))
            >= qty,
            f"demand_{length}",
        )

    # Решаем
    status = prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit))

    if pulp.LpStatus[status] not in ("Optimal", "Feasible"):
        # Fallback — простой First Fit Decreasing
        return solve_ffd(demands, stock_length)

    # Собираем результат
    result_patterns = []
    total_bars = 0
    for i, var in enumerate(x):
        cnt = int(pulp.value(var) or 0)
        if cnt > 0:
            used = sum(patterns[i])
            result_patterns.append({
                "pieces": list(patterns[i]),
                "count": cnt,
                "used": used,
                "waste": stock_length - used,
            })
            total_bars += cnt

    # Сортируем по убыванию использования
    result_patterns.sort(key=lambda p: (-p["used"], -p["count"]))
    return result_patterns, total_bars


def solve_ffd(demands: Dict[int, int], stock_length: int) -> Tuple[List[Dict], int]:
    """
    First Fit Decreasing + жадное заполнение.
    Надёжный fallback.
    """
    # Разворачиваем в список деталей
    items = []
    for L, q in sorted(demands.items(), reverse=True):
        items.extend([L] * q)

    bars = []  # каждый бар — список длин

    for item in items:
        placed = False
        for bar in bars:
            if sum(bar) + item <= stock_length:
                bar.append(item)
                placed = True
                break
        if not placed:
            bars.append([item])

    # Группируем одинаковые схемы
    from collections import defaultdict
    groups = defaultdict(int)
    for bar in bars:
        key = tuple(sorted(bar, reverse=True))
        groups[key] += 1

    result = []
    for pieces, cnt in groups.items():
        used = sum(pieces)
        result.append({
            "pieces": list(pieces),
            "count": cnt,
            "used": used,
            "waste": stock_length - used,
        })

    result.sort(key=lambda p: (-p["used"], -p["count"]))
    return result, len(bars)


def solve_cutting_stock(
    demands: Dict[int, int],
    stock_length: int,
    method: str = "auto",
) -> Tuple[List[Dict], int]:
    """
    Главная точка входа.
    method: "auto" | "ilp" | "ffd"
    """
    total_pieces = sum(demands.values())
    n_types = len(demands)

    if method == "ffd" or (method == "auto" and (total_pieces > 400 or n_types > 40)):
        return solve_ffd(demands, stock_length)

    try:
        return solve_cutting_stock_pulp(demands, stock_length)
    except Exception:
        return solve_ffd(demands, stock_length)


# ============================================================
#  Вспомогательные функции
# ============================================================

def prepare_demands(
    df: pd.DataFrame,
    kerf: float,
    stock_length: float,
    end_cut: float,
) -> Tuple[Dict[int, int], float, List[str]]:
    """
    Подготавливает словарь спроса с учётом пропила.
    Возвращает (demands, effective_stock, warnings)
    """
    warnings = []
    effective_stock = stock_length - end_cut
    demands: Dict[int, int] = {}

    for _, row in df.iterrows():
        if pd.isna(row["Длина, мм"]) or pd.isna(row["Количество"]):
            continue
        length = float(row["Длина, мм"])
        qty = int(row["Количество"])
        if length <= 0 or qty <= 0:
            continue

        # К длине детали прибавляем пропил
        effective_length = length + kerf

        if effective_length > effective_stock:
            warnings.append(
                f"Деталь {length} мм (с пропилом {effective_length:.1f}) "
                f"длиннее хлыста ({effective_stock:.1f} мм) — пропущена"
            )
            continue

        # Работаем в целых (мм)
        L = int(round(effective_length))
        demands[L] = demands.get(L, 0) + qty

    return demands, effective_stock, warnings


def format_pattern(pieces: List[int], kerf: float) -> str:
    """Показывает реальные длины деталей (без пропила)."""
    real = [max(0, int(round(p - kerf))) for p in pieces]
    return " + ".join(map(str, real))


# ============================================================
#  Интерфейс
# ============================================================

def main():
    st.title("✂️ Калькулятор линейного раскроя")
    st.caption("Современная версия · Streamlit + математическая оптимизация")

    # ---------- Боковая панель ----------
    with st.sidebar:
        st.header("Параметры хлыста")
        stock_length = st.number_input(
            "Длина хлыста, мм",
            min_value=100.0,
            value=6000.0,
            step=100.0,
            help="Стандартная длина профиля / трубы / бруса",
        )
        end_cut = st.number_input(
            "Торцевый спил, мм",
            min_value=0.0,
            value=0.0,
            step=1.0,
            help="Сколько срезается с конца хлыста (торцевание)",
        )
        kerf = st.number_input(
            "Ширина инструмента (пропил), мм",
            min_value=0.0,
            value=3.0,
            step=0.5,
            help="Толщина реза. Прибавляется к каждой детали",
        )
        min_remnant = st.number_input(
            "Минимальный полезный остаток, мм",
            min_value=0.0,
            value=0.0,
            step=10.0,
            help="Остатки короче этого значения считаются отходом (пока информативно)",
        )

        st.divider()
        method = st.selectbox(
            "Метод оптимизации",
            options=["auto", "ilp", "ffd"],
            format_func=lambda x: {
                "auto": "Авто (рекомендуется)",
                "ilp": "ILP (точный, медленнее)",
                "ffd": "First Fit Decreasing (быстрый)",
            }[x],
            help="ILP ищет близкий к оптимуму раскрой. FFD — очень быстрый эвристический.",
        )

    # ---------- Таблица деталей ----------
    st.subheader("Детали")

    default_df = pd.DataFrame({
        "Название": ["Деталь 1", "Деталь 2"],
        "Длина, мм": [1500.0, 2200.0],
        "Количество": [4, 6],
    })

    df = st.data_editor(
        default_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Название": st.column_config.TextColumn("Название", width="medium"),
            "Длина, мм": st.column_config.NumberColumn("Длина, мм", min_value=1, step=1, format="%.0f"),
            "Количество": st.column_config.NumberColumn("Количество", min_value=1, step=1),
        },
        key="pieces_editor",
    )

    col_run, col_clear = st.columns([1, 5])
    with col_run:
        run = st.button("Рассчитать раскрой", type="primary", use_container_width=True)

    # ---------- Расчёт ----------
    if run:
        # Валидация
        if df.empty or df["Длина, мм"].isna().all():
            st.error("Добавьте хотя бы одну деталь")
            return

        demands, effective_stock, warnings = prepare_demands(
            df, kerf=kerf, stock_length=stock_length, end_cut=end_cut
        )

        for w in warnings:
            st.warning(w)

        if not demands:
            st.error("Нет ни одной детали, которая помещается в хлыст")
            return

        with st.spinner("Оптимизирую раскрой..."):
            patterns, total_bars = solve_cutting_stock(
                demands, int(round(effective_stock)), method=method
            )

        if total_bars == 0:
            st.error("Не удалось построить раскрой")
            return

        # ---------- Результаты ----------
        total_length_needed = sum(
            (L - kerf) * q for L, q in demands.items()
        )
        total_stock_length = total_bars * stock_length
        total_waste = total_stock_length - total_length_needed - total_bars * end_cut
        # Более точный расчёт отхода с учётом пропилов
        total_kerf_loss = sum(kerf * q for q in demands.values())
        usable = total_length_needed
        efficiency = (usable / (total_bars * effective_stock)) * 100 if total_bars else 0

        st.success(f"**Готово!** Использовано **{total_bars}** хлыст(ов)")

        # Метрики
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Хлыстов", total_bars)
        m2.metric("Использование", f"{efficiency:.1f}%")
        m3.metric("Общий полезный метраж", f"{usable:.0f} мм")
        m4.metric("Суммарный отход", f"{total_bars * effective_stock - sum(p['used'] * p['count'] for p in patterns):.0f} мм")

        st.divider()

        # Таблица схем
        st.subheader("Схемы раскроя")

        rows = []
        for idx, p in enumerate(patterns, 1):
            real_pieces = [max(0, int(round(x - kerf))) for x in p["pieces"]]
            rows.append({
                "№": idx,
                "Схема (длины деталей)": " + ".join(map(str, real_pieces)),
                "Использовано, мм": int(round(p["used"] + end_cut)),
                "Остаток, мм": int(round(effective_stock - p["used"])),
                "Повторов": p["count"],
                "Деталей в схеме": len(p["pieces"]),
            })

        result_df = pd.DataFrame(rows)
        st.dataframe(result_df, use_container_width=True, hide_index=True)

        # Визуализация
        st.subheader("Визуализация схем")
        show_visualization(patterns, effective_stock, kerf, end_cut)

        # Экспорт
        st.divider()
        st.subheader("Экспорт")
        export_df = result_df.copy()
        csv = export_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "Скачать CSV",
            data=csv,
            file_name="raskroy.csv",
            mime="text/csv",
        )

        # Подробный текстовый отчёт
        with st.expander("Текстовый отчёт (для печати)"):
            report = []
            report.append(f"Длина хлыста: {stock_length} мм")
            report.append(f"Торцевый спил: {end_cut} мм")
            report.append(f"Пропил: {kerf} мм")
            report.append(f"Всего хлыстов: {total_bars}")
            report.append(f"Использование: {efficiency:.1f}%")
            report.append("")
            for idx, p in enumerate(patterns, 1):
                real = [max(0, int(round(x - kerf))) for x in p["pieces"]]
                report.append(
                    f"Схема {idx} × {p['count']}: "
                    f"{' + '.join(map(str, real))}  "
                    f"(остаток {effective_stock - p['used']:.0f} мм)"
                )
            st.code("\n".join(report))


def show_visualization(patterns, effective_stock, kerf, end_cut):
    """Простая визуализация полосками через HTML."""
    colors = [
        "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
        "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
    ]

    html_parts = []
    for idx, p in enumerate(patterns):
        real_pieces = [max(0, int(round(x - kerf))) for x in p["pieces"]]
        used = p["used"]
        waste = effective_stock - used

        # Полоска
        bar_html = f'<div style="margin-bottom:14px;">'
        bar_html += f'<div style="font-size:13px; margin-bottom:4px;"><b>Схема {idx+1}</b> × {p["count"]} &nbsp;|&nbsp; остаток {waste:.0f} мм</div>'
        bar_html += '<div style="display:flex; height:28px; border:1px solid #ccc; border-radius:4px; overflow:hidden; background:#f0f0f0;">'

        for i, length in enumerate(p["pieces"]):
            pct = (length / effective_stock) * 100
            color = colors[i % len(colors)]
            real_len = max(0, int(round(length - kerf)))
            bar_html += (
                f'<div title="{real_len} мм" style="width:{pct}%; background:{color}; '
                f'display:flex; align-items:center; justify-content:center; '
                f'color:white; font-size:11px; font-weight:600;">{real_len}</div>'
            )

        if waste > 0.5:
            pct_w = (waste / effective_stock) * 100
            bar_html += (
                f'<div title="Отход {waste:.0f} мм" style="width:{pct_w}%; background:#e0e0e0; '
                f'display:flex; align-items:center; justify-content:center; '
                f'color:#666; font-size:11px;">{int(round(waste))}</div>'
            )

        bar_html += "</div></div>"
        html_parts.append(bar_html)

    st.markdown("".join(html_parts), unsafe_allow_html=True)


if __name__ == "__main__":
    main()

# Версия 1.0