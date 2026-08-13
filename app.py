"""
Linear cutting stock calculator (1D Cutting Stock)
Modern version on Streamlit + PuLP / OR-Tools
"""

import streamlit as st
import pandas as pd
import numpy as np
from typing import List, Dict, Tuple, Optional
from collections import Counter
import io

# Try OR-Tools first, otherwise PuLP
try:
    from ortools.linear_solver import pywraplp
    SOLVER_BACKEND = "ortools"
except ImportError:
    import pulp
    SOLVER_BACKEND = "pulp"


st.set_page_config(
    page_title="Linear cutting",
    page_icon="✂️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
#  Optimization core
# ============================================================

def generate_patterns(
    piece_lengths: List[int],
    stock_length: int,
    max_pieces_per_bar: int = 20,
) -> List[Tuple[int, ...]]:
    """
    Generates all reasonable cutting patterns (combinations of pieces
    that fit into one bar).
    Uses recursive search with pruning.
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
                rec(i, remaining - L, current)  # can take the same piece again
                current.pop()

    rec(0, stock_length, [])
    # Remove duplicates
    unique = list(set(patterns))
    return unique


def solve_cutting_stock_pulp(
    demands: Dict[int, int],
    stock_length: int,
    time_limit: int = 30,
) -> Tuple[List[Dict], int]:
    """
    Solves the cutting stock problem using pattern generation + ILP (PuLP).
    Returns a list of patterns and the total number of bars.
    """
    import pulp

    lengths = sorted(demands.keys(), reverse=True)
    if not lengths:
        return [], 0

    # Generate patterns
    patterns = generate_patterns(lengths, stock_length)
    if not patterns:
        return [], 0

    # Limit the number of patterns if there are too many
    if len(patterns) > 3000:
        # Keep the densest ones
        patterns = sorted(patterns, key=lambda p: sum(p), reverse=True)[:3000]

    # Model
    prob = pulp.LpProblem("CuttingStock", pulp.LpMinimize)

    # Variables: how many times each pattern is used
    x = [pulp.LpVariable(f"p_{i}", lowBound=0, cat="Integer") for i in range(len(patterns))]

    # Objective: minimize bars
    prob += pulp.lpSum(x)

    # Demand constraints
    for length, qty in demands.items():
        prob += (
            pulp.lpSum(x[i] * patterns[i].count(length) for i in range(len(patterns)))
            == qty,
            f"demand_{length}",
        )

    # Solve
    status = prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit))

    if pulp.LpStatus[status] not in ("Optimal", "Feasible"):
        # Fallback — simple First Fit Decreasing
        return solve_ffd(demands, stock_length)

    # Collect results
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

    # Sort by descending usage
    result_patterns.sort(key=lambda p: (-p["used"], -p["count"]))
    return result_patterns, total_bars


def solve_ffd(demands: Dict[int, int], stock_length: int) -> Tuple[List[Dict], int]:
    """
    First Fit Decreasing + greedy filling.
    Reliable fallback.
    """
    # Expand into a list of pieces
    items = []
    for L, q in sorted(demands.items(), reverse=True):
        items.extend([L] * q)

    bars = []  # each bar is a list of lengths

    for item in items:
        placed = False
        for bar in bars:
            if sum(bar) + item <= stock_length:
                bar.append(item)
                placed = True
                break
        if not placed:
            bars.append([item])

    # Group identical patterns
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
    Main entry point.
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
#  Helper functions
# ============================================================

def prepare_demands(
    df: pd.DataFrame,
    kerf: float,
    stock_length: float,
    end_cut: float,
) -> Tuple[Dict[int, int], float, List[str]]:
    """
    Builds the demand dictionary taking the kerf into account.
    Returns (demands, effective_stock, warnings)
    """
    warnings = []
    effective_stock = stock_length - end_cut
    demands: Dict[int, int] = {}

    for _, row in df.iterrows():
        if pd.isna(row["Length, mm"]) or pd.isna(row["Quantity"]):
            continue
        length = float(row["Length, mm"])
        qty = int(row["Quantity"])
        if length <= 0 or qty <= 0:
            continue

        # The kerf is added to each piece length
        effective_length = length + kerf

        if effective_length > effective_stock:
            warnings.append(
                f"Piece {length} mm (with kerf {effective_length:.1f}) "
                f"is longer than the bar ({effective_stock:.1f} mm) — skipped"
            )
            continue

        # Work with integers (mm)
        L = int(round(effective_length))
        demands[L] = demands.get(L, 0) + qty

    return demands, effective_stock, warnings


def format_pattern(pieces: List[int], kerf: float) -> str:
    """Shows the real piece lengths (without the kerf)."""
    real = [max(0, int(round(p - kerf))) for p in pieces]
    return " + ".join(map(str, real))


# ============================================================
#  Interface
# ============================================================

def main():
    st.title("✂️ Linear cutting calculator")
    st.caption("Modern version · Streamlit + mathematical optimization")

    # ---------- Sidebar ----------
    with st.sidebar:
        st.header("Bar parameters")
        stock_length = st.number_input(
            "Bar length, mm",
            min_value=100.0,
            value=6000.0,
            step=100.0,
            help="Standard length of profile / pipe / timber",
        )
        end_cut = st.number_input(
            "End trim, mm",
            min_value=0.0,
            value=0.0,
            step=1.0,
            help="How much is cut off the end of the bar (end trimming)",
        )
        kerf = st.number_input(
            "Tool width (kerf), mm",
            min_value=0.0,
            value=3.0,
            step=0.5,
            help="Cut thickness. Added to each piece",
        )
        min_remnant = st.number_input(
            "Minimum useful remnant, mm",
            min_value=0.0,
            value=0.0,
            step=10.0,
            help="Remnants shorter than this count as waste (informational for now)",
        )

        st.divider()
        method = st.selectbox(
            "Optimization method",
            options=["auto", "ilp", "ffd"],
            format_func=lambda x: {
                "auto": "Auto (recommended)",
                "ilp": "ILP (exact, slower)",
                "ffd": "First Fit Decreasing (fast)",
            }[x],
            help="ILP searches for a near-optimal cutting plan. FFD is a very fast heuristic.",
        )

    # ---------- Pieces table ----------
    st.subheader("Pieces")

    default_df = pd.DataFrame({
        "Name": ["Piece 1", "Piece 2"],
        "Length, mm": [1500.0, 2200.0],
        "Quantity": [4, 6],
    })

    df = st.data_editor(
        default_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Name": st.column_config.TextColumn("Name", width="medium"),
            "Length, mm": st.column_config.NumberColumn("Length, mm", min_value=1, step=1, format="%.0f"),
            "Quantity": st.column_config.NumberColumn("Quantity", min_value=1, step=1),
        },
        key="pieces_editor",
    )

    col_run, col_clear = st.columns([1, 5])
    with col_run:
        run = st.button("Calculate cutting plan", type="primary", use_container_width=True)

    # ---------- Calculation ----------
    if run:
        # Validation
        if df.empty or df["Length, mm"].isna().all():
            st.error("Add at least one piece")
            return

        demands, effective_stock, warnings = prepare_demands(
            df, kerf=kerf, stock_length=stock_length, end_cut=end_cut
        )

        for w in warnings:
            st.warning(w)

        if not demands:
            st.error("No piece fits into the bar")
            return

        with st.spinner("Optimizing cutting plan..."):
            patterns, total_bars = solve_cutting_stock(
                demands, int(round(effective_stock)), method=method
            )

        if total_bars == 0:
            st.error("Failed to build a cutting plan")
            return

        # ---------- Results ----------
        total_length_needed = sum(
            (L - kerf) * q for L, q in demands.items()
        )
        total_stock_length = total_bars * stock_length
        total_waste = total_stock_length - total_length_needed - total_bars * end_cut
        # More accurate waste calculation accounting for kerfs
        total_kerf_loss = sum(kerf * q for q in demands.values())
        usable = total_length_needed
        efficiency = (usable / (total_bars * effective_stock)) * 100 if total_bars else 0

        st.success(f"**Done!** Used **{total_bars}** bar(s)")

        # Metrics
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Bars", total_bars)
        m2.metric("Usage", f"{efficiency:.1f}%")
        m3.metric("Total useful length", f"{usable:.0f} mm")
        m4.metric("Total waste", f"{total_bars * effective_stock - sum(p['used'] * p['count'] for p in patterns):.0f} mm")

        st.divider()

        # Cutting patterns table
        st.subheader("Cutting patterns")

        rows = []
        for idx, p in enumerate(patterns, 1):
            real_pieces = [max(0, int(round(x - kerf))) for x in p["pieces"]]
            rows.append({
                "#": idx,
                "Pattern (piece lengths)": " + ".join(map(str, real_pieces)),
                "Used, mm": int(round(p["used"] + end_cut)),
                "Remainder, mm": int(round(effective_stock - p["used"])),
                "Repeats": p["count"],
                "Pieces in pattern": len(p["pieces"]),
            })

        result_df = pd.DataFrame(rows)
        st.dataframe(result_df, use_container_width=True, hide_index=True)

        # Visualization
        st.subheader("Pattern visualization")
        show_visualization(patterns, effective_stock, kerf, end_cut)

        # Export
        st.divider()
        st.subheader("Export")
        export_df = result_df.copy()
        csv = export_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "Download CSV",
            data=csv,
            file_name="cutting_plan.csv",
            mime="text/csv",
        )

        # Detailed text report
        with st.expander("Text report (for printing)"):
            report = []
            report.append(f"Bar length: {stock_length} mm")
            report.append(f"End trim: {end_cut} mm")
            report.append(f"Kerf: {kerf} mm")
            report.append(f"Total bars: {total_bars}")
            report.append(f"Usage: {efficiency:.1f}%")
            report.append("")
            for idx, p in enumerate(patterns, 1):
                real = [max(0, int(round(x - kerf))) for x in p["pieces"]]
                report.append(
                    f"Pattern {idx} × {p['count']}: "
                    f"{' + '.join(map(str, real))}  "
                    f"(remainder {effective_stock - p['used']:.0f} mm)"
                )
            st.code("\n".join(report))


def show_visualization(patterns, effective_stock, kerf, end_cut):
    """Simple bar visualization using HTML."""
    colors = [
        "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
        "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
    ]

    html_parts = []
    for idx, p in enumerate(patterns):
        real_pieces = [max(0, int(round(x - kerf))) for x in p["pieces"]]
        used = p["used"]
        waste = effective_stock - used

        # Bar strip
        bar_html = f'<div style="margin-bottom:14px;">'
        bar_html += f'<div style="font-size:13px; margin-bottom:4px;"><b>Pattern {idx+1}</b> × {p["count"]} &nbsp;|&nbsp; remainder {waste:.0f} mm</div>'
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
                f'<div title="Waste {waste:.0f} mm" style="width:{pct_w}%; background:#e0e0e0; '
                f'display:flex; align-items:center; justify-content:center; '
                f'color:#666; font-size:11px;">{int(round(waste))}</div>'
            )

        bar_html += "</div></div>"
        html_parts.append(bar_html)

    st.markdown("".join(html_parts), unsafe_allow_html=True)


if __name__ == "__main__":
    main()

# Version 1.0