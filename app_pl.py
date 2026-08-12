"""
Kalkulator cięcia liniowego (1D Cutting Stock)
Wersja nowoczesna na Streamlit + PuLP / OR-Tools
"""

import streamlit as st
import pandas as pd
import numpy as np
from typing import List, Dict, Tuple, Optional
from collections import Counter
import io

# Najpierw próbujemy OR-Tools, w przeciwnym razie PuLP
try:
    from ortools.linear_solver import pywraplp
    SOLVER_BACKEND = "ortools"
except ImportError:
    import pulp
    SOLVER_BACKEND = "pulp"


st.set_page_config(
    page_title="Cięcie liniowe",
    page_icon="✂️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
#  Rdzeń optymalizacji
# ============================================================

def generate_patterns(
    piece_lengths: List[int],
    stock_length: int,
    max_pieces_per_bar: int = 20,
) -> List[Tuple[int, ...]]:
    """
    Generuje wszystkie sensowne schematy cięcia (kombinacje elementów,
    które mieszczą się w jednym pręcie).
    Używa rekurencyjnego przeszukiwania z przycinaniem.
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
                rec(i, remaining - L, current)  # można wziąć ten sam element ponownie
                current.pop()

    rec(0, stock_length, [])
    # Usuwamy duplikaty
    unique = list(set(patterns))
    return unique


def solve_cutting_stock_pulp(
    demands: Dict[int, int],
    stock_length: int,
    time_limit: int = 30,
) -> Tuple[List[Dict], int]:
    """
    Rozwiązuje problem cięcia liniowego przez generowanie schematów + ILP (PuLP).
    Zwraca listę schematów i całkowitą liczbę prętów.
    """
    import pulp

    lengths = sorted(demands.keys(), reverse=True)
    if not lengths:
        return [], 0

    # Generujemy schematy
    patterns = generate_patterns(lengths, stock_length)
    if not patterns:
        return [], 0

    # Ograniczamy liczbę schematów, jeśli jest ich zbyt wiele
    if len(patterns) > 3000:
        # Zostawiamy najgęstsze
        patterns = sorted(patterns, key=lambda p: sum(p), reverse=True)[:3000]

    # Model
    prob = pulp.LpProblem("CuttingStock", pulp.LpMinimize)

    # Zmienne: ile razy każdy schemat jest użyty
    x = [pulp.LpVariable(f"p_{i}", lowBound=0, cat="Integer") for i in range(len(patterns))]

    # Cel: minimum prętów
    prob += pulp.lpSum(x)

    # Ograniczenia zapotrzebowania
    for length, qty in demands.items():
        prob += (
            pulp.lpSum(x[i] * patterns[i].count(length) for i in range(len(patterns)))
            >= qty,
            f"demand_{length}",
        )

    # Rozwiązujemy
    status = prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit))

    if pulp.LpStatus[status] not in ("Optimal", "Feasible"):
        # Fallback — proste First Fit Decreasing
        return solve_ffd(demands, stock_length)

    # Zbieramy wyniki
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

    # Sortujemy malejąco według wykorzystania
    result_patterns.sort(key=lambda p: (-p["used"], -p["count"]))
    return result_patterns, total_bars


def solve_ffd(demands: Dict[int, int], stock_length: int) -> Tuple[List[Dict], int]:
    """
    First Fit Decreasing + zachłanne wypełnianie.
    Niezawodny fallback.
    """
    # Rozwijamy do listy elementów
    items = []
    for L, q in sorted(demands.items(), reverse=True):
        items.extend([L] * q)

    bars = []  # każdy pręt to lista długości

    for item in items:
        placed = False
        for bar in bars:
            if sum(bar) + item <= stock_length:
                bar.append(item)
                placed = True
                break
        if not placed:
            bars.append([item])

    # Grupujemy identyczne schematy
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
    Główny punkt wejścia.
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
#  Funkcje pomocnicze
# ============================================================

def prepare_demands(
    df: pd.DataFrame,
    kerf: float,
    stock_length: float,
    end_cut: float,
) -> Tuple[Dict[int, int], float, List[str]]:
    """
    Buduje słownik zapotrzebowania z uwzględnieniem cięcia (kerf).
    Zwraca (demands, effective_stock, warnings)
    """
    warnings = []
    effective_stock = stock_length - end_cut
    demands: Dict[int, int] = {}

    for _, row in df.iterrows():
        length = float(row["Długość, mm"])
        qty = int(row["Ilość"])
        if length <= 0 or qty <= 0:
            continue

        # Do długości elementu dodajemy cięcie
        effective_length = length + kerf

        if effective_length > effective_stock:
            warnings.append(
                f"Element {length} mm (z cięciem {effective_length:.1f}) "
                f"jest dłuższy niż pręt ({effective_stock:.1f} mm) — pominięto"
            )
            continue

        # Pracujemy na liczbach całkowitych (mm)
        L = int(round(effective_length))
        demands[L] = demands.get(L, 0) + qty

    return demands, effective_stock, warnings


def format_pattern(pieces: List[int], kerf: float) -> str:
    """Pokazuje rzeczywiste długości elementów (bez cięcia)."""
    real = [max(0, int(round(p - kerf))) for p in pieces]
    return " + ".join(map(str, real))


# ============================================================
#  Interfejs
# ============================================================

def main():
    st.title("✂️ Kalkulator cięcia liniowego")
    st.caption("Nowoczesna wersja · Streamlit + optymalizacja matematyczna")

    # ---------- Panel boczny ----------
    with st.sidebar:
        st.header("Parametry pręta")
        stock_length = st.number_input(
            "Długość pręta, mm",
            min_value=100.0,
            value=6000.0,
            step=100.0,
            help="Standardowa długość profilu / rury / drewna",
        )
        end_cut = st.number_input(
            "Przycięcie czołowe, mm",
            min_value=0.0,
            value=0.0,
            step=1.0,
            help="Ile jest odcinane z końca pręta (przycięcie czołowe)",
        )
        kerf = st.number_input(
            "Szerokość narzędzia (cięcie), mm",
            min_value=0.0,
            value=3.0,
            step=0.5,
            help="Grubość cięcia. Dodawana do każdego elementu",
        )
        min_remnant = st.number_input(
            "Minimalny użyteczny odcinek, mm",
            min_value=0.0,
            value=0.0,
            step=10.0,
            help="Odcinki krótsze niż ta wartość są traktowane jako odpad (na razie informacyjnie)",
        )

        st.divider()
        method = st.selectbox(
            "Metoda optymalizacji",
            options=["auto", "ilp", "ffd"],
            format_func=lambda x: {
                "auto": "Auto (zalecane)",
                "ilp": "ILP (dokładna, wolniejsza)",
                "ffd": "First Fit Decreasing (szybka)",
            }[x],
            help="ILP szuka planu cięcia bliskiego optymalnemu. FFD to bardzo szybka heurystyka.",
        )

        st.divider()
        st.markdown("**Przykładowe dane**")
        if st.button("Wczytaj przykład ze starego Excela"):
            st.session_state["example_loaded"] = True

    # ---------- Tabela elementów ----------
    st.subheader("Elementy")

    if "example_loaded" in st.session_state and st.session_state["example_loaded"]:
        default_df = pd.DataFrame({
            "Nazwa": [
                "Element 1", "Element 2", "Element 3", "Element 4",
                "Element 5", "Element 6", "Element 7", "Element 8"
            ],
            "Długość, mm": [540, 790, 1680, 580, 390, 680, 760, 1200],
            "Ilość": [2, 2, 4, 2, 2, 2, 4, 4],
        })
        # Resetujemy flagę, żeby można było edytować ponownie
        st.session_state["example_loaded"] = False
    else:
        default_df = pd.DataFrame({
            "Nazwa": ["Element 1", "Element 2"],
            "Długość, mm": [1500.0, 2200.0],
            "Ilość": [4, 6],
        })

    df = st.data_editor(
        default_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Nazwa": st.column_config.TextColumn("Nazwa", width="medium"),
            "Długość, mm": st.column_config.NumberColumn("Długość, mm", min_value=1, step=1, format="%.0f"),
            "Ilość": st.column_config.NumberColumn("Ilość", min_value=1, step=1),
        },
        key="pieces_editor",
    )

    col_run, col_clear = st.columns([1, 5])
    with col_run:
        run = st.button("Oblicz plan cięcia", type="primary", use_container_width=True)

    # ---------- Obliczenia ----------
    if run:
        # Walidacja
        if df.empty or df["Długość, mm"].isna().all():
            st.error("Dodaj przynajmniej jeden element")
            return

        demands, effective_stock, warnings = prepare_demands(
            df, kerf=kerf, stock_length=stock_length, end_cut=end_cut
        )

        for w in warnings:
            st.warning(w)

        if not demands:
            st.error("Żaden element nie mieści się w pręcie")
            return

        with st.spinner("Optymalizuję plan cięcia..."):
            patterns, total_bars = solve_cutting_stock(
                demands, int(round(effective_stock)), method=method
            )

        if total_bars == 0:
            st.error("Nie udało się utworzyć planu cięcia")
            return

        # ---------- Wyniki ----------
        total_length_needed = sum(
            (L - kerf) * q for L, q in demands.items()
        )
        total_stock_length = total_bars * stock_length
        total_waste = total_stock_length - total_length_needed - total_bars * end_cut
        # Dokładniejsze obliczenie odpadu z uwzględnieniem cięć
        total_kerf_loss = sum(kerf * q for q in demands.values())
        usable = total_length_needed
        efficiency = (usable / (total_bars * effective_stock)) * 100 if total_bars else 0

        st.success(f"**Gotowe!** Użyto **{total_bars}** pręt(ów)")

        # Metryki
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Pręty", total_bars)
        m2.metric("Wykorzystanie", f"{efficiency:.1f}%")
        m3.metric("Całkowita długość użytkowa", f"{usable:.0f} mm")
        m4.metric("Całkowity odpad", f"{total_bars * effective_stock - sum(p['used'] * p['count'] for p in patterns):.0f} mm")

        st.divider()

        # Tabela schematów cięcia
        st.subheader("Schematy cięcia")

        rows = []
        for idx, p in enumerate(patterns, 1):
            real_pieces = [max(0, int(round(x - kerf))) for x in p["pieces"]]
            rows.append({
                "Lp.": idx,
                "Schemat (długości elementów)": " + ".join(map(str, real_pieces)),
                "Użyto, mm": int(round(p["used"] + end_cut)),
                "Pozostałość, mm": int(round(effective_stock - p["used"])),
                "Powtórzenia": p["count"],
                "Elementów w schemacie": len(p["pieces"]),
            })

        result_df = pd.DataFrame(rows)
        st.dataframe(result_df, use_container_width=True, hide_index=True)

        # Wizualizacja
        st.subheader("Wizualizacja schematów")
        show_visualization(patterns, effective_stock, kerf, end_cut)

        # Eksport
        st.divider()
        st.subheader("Eksport")
        export_df = result_df.copy()
        csv = export_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "Pobierz CSV",
            data=csv,
            file_name="plan_ciecia.csv",
            mime="text/csv",
        )

        # Szczegółowy raport tekstowy
        with st.expander("Raport tekstowy (do druku)"):
            report = []
            report.append(f"Długość pręta: {stock_length} mm")
            report.append(f"Przycięcie czołowe: {end_cut} mm")
            report.append(f"Cięcie: {kerf} mm")
            report.append(f"Razem prętów: {total_bars}")
            report.append(f"Wykorzystanie: {efficiency:.1f}%")
            report.append("")
            for idx, p in enumerate(patterns, 1):
                real = [max(0, int(round(x - kerf))) for x in p["pieces"]]
                report.append(
                    f"Schemat {idx} × {p['count']}: "
                    f"{' + '.join(map(str, real))}  "
                    f"(pozostałość {effective_stock - p['used']:.0f} mm)"
                )
            st.code("\n".join(report))


def show_visualization(patterns, effective_stock, kerf, end_cut):
    """Prosta wizualizacja pasków za pomocą HTML."""
    colors = [
        "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
        "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
    ]

    html_parts = []
    for idx, p in enumerate(patterns):
        real_pieces = [max(0, int(round(x - kerf))) for x in p["pieces"]]
        used = p["used"]
        waste = effective_stock - used

        # Pasek pręta
        bar_html = f'<div style="margin-bottom:14px;">'
        bar_html += f'<div style="font-size:13px; margin-bottom:4px;"><b>Schemat {idx+1}</b> × {p["count"]} &nbsp;|&nbsp; pozostałość {waste:.0f} mm</div>'
        bar_html += '<div style="display:flex; height:28px; border:1px solid #ccc; border-radius:4px; overflow:hidden; background:#f0f0f0;">'

        for i, length in enumerate(p["pieces"]):
            pct = (length / effective_stock) * 100
            color = colors[i % len(colors)]
            real_len = max(0, int(round(length - kerf)))
            bar_html += (
                f'<div title="{real_len} mm" style="width:{pct}%; background:{color}; '
                f'display:flex; align-items:center; justify-content:center; '
                f'color:white; font-size:11px; font-weight:600;">{real_len}</div>'
            )

        if waste > 0.5:
            pct_w = (waste / effective_stock) * 100
            bar_html += (
                f'<div title="Odpad {waste:.0f} mm" style="width:{pct_w}%; background:#e0e0e0; '
                f'display:flex; align-items:center; justify-content:center; '
                f'color:#666; font-size:11px;">{int(round(waste))}</div>'
            )

        bar_html += "</div></div>"
        html_parts.append(bar_html)

    st.markdown("".join(html_parts), unsafe_allow_html=True)


if __name__ == "__main__":
    main()

# Wersja 1.0