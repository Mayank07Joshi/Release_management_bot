import pandas as pd

# ---------------------- BUILD MATRIX ----------------------
def build_bug_matrix(bugs: pd.DataFrame, months: list, mode: str) -> pd.DataFrame:
    """
    mode = 'open_start', 'completed', 'new', 'open_end'
    Matrix:
        ROWS   = – P1, – P2, – Others, Sub-total
        COLUMNS = months + Total
    """
    data = {"P1": [], "P2": [], "Others": []}

    for m in months:
        m_start = m.to_timestamp()
        m_end = (m + 1).to_timestamp() - pd.Timedelta(seconds=1)

        def count_open(dt):
            return bugs[
                (bugs["created_date"] <= dt)
                & ((bugs["closed_date"].isna()) | (bugs["closed_date"] > dt))
            ]

        if mode == "open_start":
            d = count_open(m_start)
        elif mode == "open_end":
            d = count_open(m_end)
        elif mode == "completed":
            d = bugs[bugs["closed_date"].between(m_start, m_end, inclusive="both")]
        elif mode == "new":
            d = bugs[bugs["created_date"].between(m_start, m_end, inclusive="both")]
        else:
            raise ValueError("Invalid mode")

        data["P1"].append((d["priority"] == 1).sum())
        data["P2"].append((d["priority"] == 2).sum())
        data["Others"].append(((d["priority"] >= 3) | (d["priority"].isna())).sum())

    # Month labels
    month_labels = [m.to_timestamp().strftime("%b-%y") for m in months]
    df = pd.DataFrame(data, index=month_labels).T

    # Pretty labels
    df.index = df.index.map(lambda s: f"– {s}" if s in {"P1", "P2", "Others"} else s)

    # Subtotal row + Total column
    df.loc["Sub-total"] = df.sum(axis=0)
    df["Total"] = df.sum(axis=1)

    return df


# ---------------------- MATRIX STYLER ----------------------
def style_matrix(df: pd.DataFrame):
    """Excel-style formatting with yellow headers, bold subtotal, grey Total column."""

    def fmt_num(x):
        if pd.isna(x): return ""
        try: return f"{int(x):,}"
        except: return x

    def bold_sub(row):
        return ["font-weight: 700;" if row.name == "Sub-total" else "" for _ in row]

    def neg_red(val):
        try:
            return "color: #c62828;" if float(val) < 0 else ""
        except:
            return ""

    table_styles = [
        {"selector": "th.col_heading",
         "props": [("background-color", "#FFF59D"), ("font-weight", "700"),
                   ("text-align", "center"), ("border", "1px solid #e0e0e0")]},
        {"selector": "th.row_heading",
         "props": [("text-align", "left"), ("border", "1px solid #e0e0e0"),
                   ("padding", "6px 10px")]},
        {"selector": "td",
         "props": [("border", "1px solid #e0e0e0"), ("padding", "6px 10px")]}
    ]

    styled = (
        df.style
        .format(fmt_num)
        .set_table_styles(table_styles)
        .apply(bold_sub, axis=1)
        .applymap(neg_red)
        .set_properties(subset=pd.IndexSlice[:, ["Total"]],
                        **{"background-color": "#F5F5F5", "font-weight": "700"})
    )
    return styled

def compute_mom_delta(df: pd.DataFrame) -> pd.DataFrame:
    """Compute Month-over-Month Δ for a bug matrix."""
    df_m = df.copy()

    # Exclude Total column first
    month_cols = df_m.columns[:-1]
    delta = df_m[month_cols].diff(axis=1)

    # Add Total Δ
    delta["Total"] = delta.sum(axis=1)

    return delta