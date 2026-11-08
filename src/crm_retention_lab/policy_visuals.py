"""Aggregate-only views of validation selection and a locked final policy."""

from html import escape

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .visuals import BLUE, GRID, INK, MUTED, ORANGE, _base


FIGURE_IDS = ("policy_validation", "policy_profit", "policy_allocation", "policy_guardrails", "policy_segments")
COLORS = {"control": "#9aa9bb", "info": BLUE, "coupon": ORANGE}
ARMS = {"control": 'No contact', "info": 'Information', "coupon": 'Information + coupon'}


def _label(row, selected=None):
    spec = row["policy_spec"]
    labels = {"control": 'No contact', "random_info": 'Random information', "random_coupon": 'Random coupon',
              "rule": 'Package/tips rule', "risk_coupon": 'Non-repurchase risk'}
    if spec["kind"] == "uplift":
        label = f"{spec['model'].upper()} λ={spec['penalty_lambda']:g}"
    else:
        label = labels[spec["kind"]]
    return ('Selected · ' if row["policy_id"] == selected else "") + label


def _frame(analysis, scope, title, n, height=550, left=190):
    metadata = dict(analysis["metadata"]["splits"][scope])
    metadata["analysis_scope"] = scope
    split = 'Validation · Candidate selection' if scope == "validation" else 'Final evaluation · After policy lock'
    fig = _base({"metadata": metadata}, title, f'Eligible customers: {n:,}', split, height)
    fig.update_layout(margin=dict(l=left, r=35, t=155, b=115), showlegend=False)
    snapshot = metadata.get("input_simulation_id", 'No ID')
    fig.layout.annotations[0].update(
        text=f"Synthetic data · {split}<br>As of {escape(str(metadata['as_of'])[:10])} · Eligible customers: {n:,}<br>Snapshot {escape(str(snapshot))}",
        xshift=8-left, y=1, yshift=65,
    )
    return fig


def _footer(fig, text):
    fig.add_annotation(x=0, y=0, xref="paper", yref="paper", xshift=8-fig.layout.margin.l, yshift=-65,
                       xanchor="left", yanchor="top", text=text, showarrow=False,
                       align="left", font=dict(size=11, color=MUTED))


def _extent(values):
    values = [value for value in values if value is not None] + [0]
    low, high = min(values), max(values)
    margin = max(high-low, 1) * 0.24
    return [low-margin, high+margin]


def _error(point, lower, upper, color):
    if lower is None or upper is None:
        return None
    return dict(type="data", symmetric=False, array=[max(0, upper-point)], arrayminus=[max(0, point-lower)],
                color=color, thickness=1.8, width=6)


def _validation(analysis):
    rows = analysis["validation"]
    chosen = analysis["selection"]["chosen_policy"]["id"]
    fig = _frame(analysis, "validation", 'Which policy was selected?', rows[0]["n"] if rows else 0,
                 height=max(580, 305+36*len(rows)))
    values, labels = [], []
    for row in rows:
        label = _label(row, chosen)
        labels.append(label)
        point, lower = row["primary"]["estimate"], row["primary"]["ci_lower"]
        values.extend([point, lower])
        color = ORANGE if row["policy_id"] == chosen else BLUE if row["screen"]["eligible"] else "#9aa9bb"
        fig.add_trace(go.Scatter(
            x=[point], y=[label], mode="markers+text", text=[f'{point:+,.0f} KRW'], textposition="top center",
            marker=dict(size=11, color=color), cliponaxis=False,
            error_x=None if lower is None else dict(type="data", symmetric=False, array=[0], arrayminus=[max(0, point-lower)],
                                                   color=color, thickness=1.7, width=6),
            customdata=[["NA" if lower is None else f"{lower:+,.1f}", row["screen"]["profit_pass"], row["screen"]["harm_pass"]]],
            hovertemplate=(f'{label}<br>Validation DR incremental profit %{{x:+,.1f}} KRW/eligible customer<br>Approximate 95% selection lower bound %{{customdata[0]}} KRW<br>Profit criterion %{{customdata[1]}} · Safety criterion %{{customdata[2]}}<extra></extra>'),
        ))
    constraints = analysis["constraints"]
    setup = constraints["fixed_setup_cost_krw_per_rollout"] / constraints["rollout_eligible_customers"]
    fig.add_vline(x=setup, line_dash="dash", line_color=MUTED)
    fig.update_xaxes(title='Validation DR incremental profit (KRW/eligible customer)', range=_extent(values+[setup]), tickformat=",.0f", nticks=5)
    fig.update_yaxes(categoryorder="array", categoryarray=labels, autorange="reversed")
    _footer(fig, 'Point: validation DR · Left end: selection lower bound<br>Orange: selected · Blue: feasible · Gray: infeasible<br>Used for candidate selection; final performance is separate')
    return fig


def _final_rows(analysis):
    chosen = analysis["selection"]["chosen_policy"]["id"]
    rows = list(analysis["final"])
    if len({row["policy_id"] for row in rows}) != len(rows):
        raise ValueError("Final comparison policies must be deduplicated")
    if not any(row["policy_id"] == chosen for row in rows):
        raise ValueError("The locked chosen policy is missing from final aggregates")
    return sorted(rows, key=lambda row: row["policy_id"] != chosen), chosen


def _profit(analysis, rows, chosen):
    fig = _frame(analysis, "final_test", 'Does the locked policy add profit?', rows[0]["n"], height=max(540, 310+44*len(rows)))
    labels, values = [], []
    for index, row in enumerate(rows):
        label, metric = _label(row, chosen), row["primary"]
        point, lower, upper = (metric[key] for key in ("estimate", "ci_lower", "ci_upper"))
        labels.append(label)
        values.extend([point, lower, upper, row["ipw_check"]["estimate"]])
        color = ORANGE if row["policy_id"] == chosen else MUTED
        fig.add_trace(go.Scatter(
            x=[point], y=[label], mode="markers+text", text=[f'{point:+,.0f} KRW'], textposition="top center",
            marker=dict(size=11, color=color), error_x=_error(point, lower, upper, color), cliponaxis=False,
            name='DR · 95% interval', showlegend=index == 0,
            customdata=[[lower, upper, row["bootstrap"]["repetitions"]]],
            hovertemplate=(f'{label}<br>DR incremental profit %{{x:+,.1f}} KRW/eligible customer<br>95% interval %{{customdata[0]:+,.1f}}–%{{customdata[1]:+,.1f}} KRW<br>Batch-reallocation bootstrap %{{customdata[2]:,}} repetitions<extra></extra>'),
        ))
    fig.add_trace(go.Scatter(x=[row["ipw_check"]["estimate"] for row in rows], y=labels, mode="markers",
                             marker=dict(symbol="diamond-open", size=10, color=INK), name='IPW check', showlegend=True,
                             hovertemplate='%{y}<br>IPW incremental profit %{x:+,.1f} KRW/eligible customer<extra></extra>'))
    fig.update_layout(showlegend=True, legend=dict(y=1.01, yanchor="bottom"))
    fig.add_vline(x=0, line_color=MUTED, line_width=1)
    fig.update_xaxes(title='Incremental profit vs no contact (KRW/eligible customer)', range=_extent(values), tickformat=",.0f", nticks=5)
    fig.update_yaxes(categoryorder="array", categoryarray=labels, autorange="reversed")
    _footer(fig, 'DR: primary estimator · IPW: check estimator<br>Differences already include actual coupon and sending costs<br>Intervals do not establish multiple-baseline superiority')
    return fig


def _allocation(analysis, rows, chosen):
    fig = make_subplots(rows=2, cols=1, vertical_spacing=0.27,
                        figure=_frame(analysis, "final_test", 'How are customers and resources allocated?', rows[0]["n"], height=850))
    labels = [_label(row, chosen) for row in rows]
    for arm, label in ARMS.items():
        counts = [row["exposure"]["counts"][arm] for row in rows]
        rates = [count/row["n"] if row["n"] else None for count, row in zip(counts, rows)]
        fig.add_trace(go.Bar(x=rates, y=labels, orientation="h", marker_color=COLORS[arm], name=label,
                             customdata=[[count, row["n"]] for count, row in zip(counts, rows)],
                             hovertemplate=f'%{{y}}<br>{label} %{{x:.1%}}<br>%{{customdata[0]:,}} / %{{customdata[1]:,}} customers<extra></extra>'), row=1, col=1)
    for key, denominator, label, color in (("reservation_total_krw", "budget_cap_total_krw", 'Reserved-budget use', INK),
                                          ("contact_n", "contact_cap_total", 'Contact-cap use', "#71a4f4")):
        rates = [row["exposure"][key]/row["exposure"][denominator] if row["exposure"][denominator] else None for row in rows]
        fig.add_trace(go.Scatter(x=rates, y=labels, mode="markers", name=label,
                                 marker=dict(size=11, color=color, symbol="square-open" if key == "contact_n" else "circle"),
                                 customdata=[[row["exposure"][key], row["exposure"][denominator]] for row in rows],
                                 hovertemplate=f"%{{y}}<br>{label} %{{x:.1%}}<br>%{{customdata[0]:,}} / %{{customdata[1]:,}}<extra></extra>"), row=2, col=1)
    fig.update_layout(barmode="stack", showlegend=True, legend=dict(y=1.02, yanchor="bottom", font=dict(size=10), traceorder="normal"))
    for panel in (1, 2):
        fig.update_yaxes(categoryorder="array", categoryarray=labels, autorange="reversed", row=panel, col=1)
        fig.update_xaxes(range=[0, 1.06], tickformat=".0%", gridcolor=GRID, row=panel, col=1)
    fig.update_xaxes(title='Share of customers by recommended action', row=1, col=1)
    fig.update_xaxes(title='Use / sum of daily caps', row=2, col=1)
    fig.add_vline(x=1, line_dash="dash", line_color=MUTED, row=2, col=1)
    _footer(fig, 'Top: allocation · Bottom: budget/contact-cap use<br>Coupon face value is fully reserved regardless of redemption<br>Daily batch caps are checked separately from totals')
    return fig


def _guardrails(analysis, selected):
    fig = _frame(analysis, "final_test", 'Side effects of the selected policy', selected["n"], height=510, left=155)
    values, labels = [], []
    names = {"unsubscribe_60d": 'Unsubscribe', "refund_customer_flag": 'Refund customers'}
    for index, row in enumerate(selected["guardrails"]):
        label = names[row["metric"]]
        labels.append(label)
        point = row["estimate"]*100
        upper = None if row["ci_upper"] is None else row["ci_upper"]*100
        tolerance = row["tolerance"]*100
        values.extend([point, upper, tolerance])
        fig.add_trace(go.Scatter(
            x=[point], y=[label], mode="markers+text", text=[f'{point:+.2f} pp'], textposition="top center",
            marker=dict(size=12, color=ORANGE), error_x=_error(point, point, upper, ORANGE), cliponaxis=False,
            name='IPW risk difference / upper bound', showlegend=index == 0,
            customdata=[[upper, tolerance, row["one_sided_confidence"]*100]],
            hovertemplate=(f'{label}<br>IPW risk difference %{{x:+.2f}} pp<br>Upper bound %{{customdata[0]:+.2f}} pp · Tolerance %{{customdata[1]:g}} pp<br>One-sided confidence %{{customdata[2]:.2f}}%<extra></extra>'),
        ))
        fig.add_trace(go.Scatter(x=[tolerance], y=[label], mode="markers", marker=dict(symbol="line-ns", size=27, color=INK, line_width=2),
                                 name='Prespecified tolerance', showlegend=index == 0,
                                 hovertemplate=f'{label} tolerance %{{x:g}} pp<extra></extra>'))
    fig.update_layout(showlegend=True, legend=dict(y=1.02, yanchor="bottom", font=dict(size=10)))
    fig.add_vline(x=0, line_color=GRID)
    fig.update_xaxes(title='Increase vs no contact (pp)', range=_extent(values), tickformat=".2f", nticks=5)
    fig.update_yaxes(categoryorder="array", categoryarray=labels, autorange=False, range=[1.4, -0.4])
    _footer(fig, 'Full-policy IPW risk difference · Two-metric correction<br>Compare each right-end upper bound with its tolerance<br>Not a simple rate among selected customers only')
    return fig


def _segments(analysis, selected):
    rows = sorted(selected["segments"], key=lambda row: row["first_pack_grams"])
    fig = _frame(analysis, "final_test", 'Recommended actions by package', selected["n"], height=510, left=130)
    labels = [f"{row['first_pack_grams']:,}g<br>n={row['n']:,}" for row in rows]
    for arm, label in ARMS.items():
        rates = [row[arm]/row["n"] if row["n"] else None for row in rows]
        fig.add_trace(go.Bar(x=rates, y=labels, orientation="h", name=label, marker_color=COLORS[arm],
                             text=[f"{rate:.1%}" if rate is not None and rate >= 0.09 else "" for rate in rates],
                             textposition="inside", textangle=0, customdata=[[row[arm], row["n"]] for row in rows],
                             hovertemplate=f'%{{y}}<br>{label} %{{x:.1%}}<br>%{{customdata[0]:,}} / %{{customdata[1]:,}} customers<extra></extra>'))
    fig.update_layout(barmode="stack", showlegend=True, legend=dict(y=1.02, yanchor="bottom", traceorder="normal"))
    fig.update_xaxes(title='Recommended action share within first-package group', range=[0, 1], tickformat=".0%")
    fig.update_yaxes(categoryorder="array", categoryarray=labels, autorange="reversed")
    _footer(fig, 'First package size is a pre-assignment feature<br>Recommendations, distinct from actual sending performance<br>Does not establish true individual effects')
    return fig


def create_policy_figures(analysis) -> dict[str, go.Figure]:
    """Build five plots from frozen aggregate results; no policy selection here."""
    if analysis["metadata"].get("synthetic") is not True:
        raise ValueError("This report requires explicit synthetic-data metadata")
    rows, chosen = _final_rows(analysis)
    selected = next(row for row in rows if row["policy_id"] == chosen)
    return dict(zip(FIGURE_IDS, (_validation(analysis), _profit(analysis, rows, chosen),
                                _allocation(analysis, rows, chosen), _guardrails(analysis, selected),
                                _segments(analysis, selected))))
