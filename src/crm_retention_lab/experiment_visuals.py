"""Display precomputed training ITT estimates and checks without re-estimation."""

import math
from html import escape

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .visuals import BLUE, GRID, INK, MUTED, ORANGE, _base


FIGURE_IDS = ("arm_profit", "profit_effects", "coupon_info_waterfall", "safety_effects", "balance")
ARMS = ("control", "info", "coupon")
ARM_LABELS = {"control": 'No contact', "info": 'Information', "coupon": 'Information + coupon'}
ARM_COLORS = {"control": "#7f91a8", "info": BLUE, "coupon": ORANGE}
CONTRASTS = ("info_vs_control", "coupon_vs_control", "coupon_vs_info")
CONTRAST_LABELS = {"info_vs_control": 'Information − no contact', "coupon_vs_control": 'Coupon − no contact',
                   "coupon_vs_info": 'Coupon − information'}
COMPONENT_LABELS = {
    "net_item_revenue": 'Merchandise after discounts', "customer_shipping_charge": 'Customer shipping charge', "refund": 'Refunds',
    "cogs": 'Cost of goods', "cogs_recovery": 'Cost recovery', "outbound_shipping": 'Outbound shipping',
    "fulfillment": 'Fulfillment', "payment_fee": 'Payment fees', "return_handling": 'Return handling',
    "send_cost": 'Sending cost',
}
FEATURE_LABELS = {
    "first_pack_grams": 'First package size', "first_quantity": 'First-order quantity', "first_paid_amount_krw": 'First payment amount',
    "first_discount_rate": 'First discount rate', "delivery_lead_days": 'Delivery lead time', "acquisition_channel": 'Acquisition channel',
    "sessions_d0_d13": 'Pre-assignment visits', "tip_views_d0_d13": 'Pre-assignment tips views', "cart_events_d0_d13": 'Pre-assignment cart events',
    "days_since_last_session": 'Time since last visit', "first_delivery_month": 'First-delivery month',
    "days_since_last_session__missing": 'Last-visit missingness',
}


def _number(value, decimals=0, signed=False):
    if value is None:
        return "NA"
    return format(value, f"{'+,' if signed else ','}.{decimals}f")


def _range(values, padding=0.22):
    values = [value for value in values if value is not None and math.isfinite(value)] + [0.0]
    low, high = min(values), max(values)
    span = max(high - low, 1.0)
    return [low - padding * span, high + padding * span]


def _frame(experiment, title, *, height=510, left=190, maturity=None):
    count = experiment["population"]["total_assigned"]
    maturity = maturity or ('60-day outcomes + 30-day settlement complete' if experiment["status"] == "ready"
                            else 'Settlement incomplete for the full assigned population')
    fig = _base({"metadata": experiment["metadata"]}, title, f'All ITT assignments: {count:,}', maturity, height)
    fig.update_layout(margin=dict(l=left, r=24), showlegend=False)
    fig.layout.annotations[0].update(xshift=8 - left, y=1, yshift=40)
    fig.layout.meta = {**fig.layout.meta, "experiment_status": experiment["status"]}
    return fig


def _footer(fig, text):
    fig.add_annotation(x=0, y=0, xref="paper", yref="paper", xanchor="left", yanchor="top",
                       xshift=8 - fig.layout.margin.l, yshift=-63,
                       text=text, showarrow=False, align="left", font=dict(size=11, color=MUTED))


def _unavailable(fig, message='Effects are not shown until all ITT customers<br>complete settlement.'):
    fig.add_annotation(x=0.5, y=0.5, xref="paper", yref="paper", text=message,
                       showarrow=False, align="center", font=dict(size=12, color=MUTED))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig


def _error(estimate, low, high, color):
    if low is None or high is None:
        return None
    return dict(type="data", symmetric=False, array=[max(0, high - estimate)],
                arrayminus=[max(0, estimate - low)], color=color, thickness=2, width=6)


def _arm_profit(experiment):
    fig = _frame(experiment, 'Contribution profit per customer')
    _footer(fig, 'Points: arm means · Lines: individual 95% intervals<br>Denominator: all originally assigned customers<br>Includes failed sends and unopened messages')
    if experiment["status"] != "ready":
        return _unavailable(fig)
    rows = {row["arm"]: row for row in experiment["arm_summaries"]}
    extent, labels = [], []
    for arm in ARMS:
        if arm not in rows:
            continue
        row, color = rows[arm], ARM_COLORS[arm]
        metric = row["primary"]
        estimate, low, high = (metric[key] for key in ("mean", "ci_lower", "ci_upper"))
        label = f"{ARM_LABELS[arm]}<br>n={row['n']:,}"
        labels.append(label)
        if estimate is None:
            fig.add_annotation(x=0.03, y=label, xref="paper", yref="y", text="NA", showarrow=False)
            continue
        extent.extend([estimate, low, high])
        fig.add_trace(go.Scatter(
            x=[estimate], y=[label], mode="markers+text", cliponaxis=False, marker=dict(size=12, color=color),
            text=[f'{_number(estimate)} KRW'], textposition="top center", textfont=dict(size=13),
            error_x=_error(estimate, low, high, color),
            customdata=[[row["n"], _number(low), _number(high)]],
            hovertemplate=(f'{ARM_LABELS[arm]}<br>Mean %{{x:,.1f}} KRW/assigned customer<br>Individual 95% interval %{{customdata[1]}}–%{{customdata[2]}} KRW<br>ITT customers %{{customdata[0]:,}}<extra></extra>'),
        ))
    fig.update_xaxes(title='Contribution profit (KRW/assigned customer)', range=_range(extent), tickformat=",.0f", nticks=4)
    fig.update_yaxes(categoryorder="array", categoryarray=labels, range=[len(labels) - 0.4, -0.7], autorange=False)
    return fig


def _profit_effects(experiment):
    fig = _frame(experiment, 'How much incremental profit?', left=190)
    _footer(fig, 'Lines: individual 95% intervals, not simultaneous<br>Hover for Holm-adjusted p-values<br>Coupon arm adds a coupon to identical information')
    if experiment["status"] != "ready":
        return _unavailable(fig)
    rows = {row["comparison"]: row for row in experiment["primary_comparisons"]}
    extent, labels = [], []
    for comparison in CONTRASTS:
        if comparison not in rows:
            continue
        row = rows[comparison]
        label, color = CONTRAST_LABELS[comparison], ARM_COLORS[row["treatment_arm"]]
        labels.append(label)
        estimate, low, high = (row[key] for key in ("estimate", "ci_lower", "ci_upper"))
        if estimate is None:
            fig.add_annotation(x=0.03, y=label, xref="paper", yref="y", text="NA", showarrow=False)
            continue
        extent.extend([estimate, low, high])
        p = row["p_value_holm"]
        fig.add_trace(go.Scatter(
            x=[estimate], y=[label], mode="markers+text", cliponaxis=False, marker=dict(size=12, color=color),
            text=[f'{_number(estimate, signed=True)} KRW'], textposition="top center", textfont=dict(size=13),
            error_x=_error(estimate, low, high, color),
            customdata=[[_number(low), _number(high), "NA" if p is None else f"{p:.4g}",
                         row["n_treatment"], row["n_reference"], row["status"]]],
            hovertemplate=(f'{label}<br>Mean difference %{{x:+,.1f}} KRW/assigned customer<br>Individual 95% interval %{{customdata[0]}}–%{{customdata[1]}} KRW<br>Holm-adjusted p=%{{customdata[2]}}<br>Treatment %{{customdata[3]:,}} / reference %{{customdata[4]:,}}<br>Calculation status %{{customdata[5]}}<extra></extra>'),
        ))
    fig.add_vline(x=0, line_color=MUTED, line_width=1.2)
    fig.update_xaxes(title='Incremental profit (KRW/assigned customer)', range=_range(extent), tickformat=",.0f", nticks=4)
    fig.update_yaxes(categoryorder="array", categoryarray=labels, range=[len(labels) - 0.4, -0.7], autorange=False)
    return fig


def _coupon_info_waterfall(experiment, checks):
    fig = _frame(experiment, 'Components of added coupon profit', height=740, left=210)
    _footer(fig, 'Information + coupon − information · Per-customer means<br>Discounts already enter revenue; no duplicate deduction<br>Accounting decomposition, not component causal effects')
    if experiment["status"] != "ready":
        return _unavailable(fig)
    finance = checks["finance_reconciliation"]
    if finance["status"] != "passed":
        return _unavailable(fig, 'Profit decomposition unavailable:<br>accounting reconciliation did not pass.')
    comparison = next((row for row in finance["comparisons"] if row["contrast"] == "coupon_vs_info"), None)
    if comparison is None:
        return _unavailable(fig, 'No information + coupon − information decomposition.')
    components = finance["components_order"]
    if set(components) - set(COMPONENT_LABELS):
        raise ValueError("Unsupported signed finance component; coupons must not be deducted twice")
    values = [comparison["components_mean_difference_krw"][component] for component in components]
    total = comparison["profit_mean_difference_krw"]
    if not math.isclose(sum(values), total, rel_tol=1e-9, abs_tol=1e-7):
        raise ValueError("Finance component mean differences do not reconcile to profit mean difference")
    arms = {row["arm"]: row for row in finance["arms"]}
    labels = [COMPONENT_LABELS[key] for key in components] + ['Incremental profit']
    custom = [[arms["coupon"]["components_mean_krw"][key], arms["info"]["components_mean_krw"][key], value]
              for key, value in zip(components, values)]
    custom.append([arms["coupon"]["mean_profit_krw"], arms["info"]["mean_profit_krw"], total])
    fig.add_trace(go.Waterfall(
        orientation="h", measure=["relative"] * len(values) + ["total"], x=values + [0], y=labels,
        text=[_number(value, signed=True) for value in values + [total]], textposition="outside",
        textfont=dict(size=11), cliponaxis=False,
        increasing=dict(marker_color=BLUE), decreasing=dict(marker_color=ORANGE), totals=dict(marker_color=INK),
        connector=dict(line=dict(color="#bbc5d2", width=1)), customdata=custom,
        hovertemplate=('%{y}<br>Information + coupon %{customdata[0]:,.2f} KRW/customer<br>Information %{customdata[1]:,.2f} KRW/customer<br>Mean difference %{customdata[2]:+,.2f} KRW/customer<extra></extra>'),
    ))
    # Cumulative endpoints determine display bounds only; the totals above are
    # supplied estimates, and the equality check prevents inconsistent plots.
    running, endpoints = 0, [0]
    for value in values:
        running += value
        endpoints.append(running)
    fig.update_xaxes(title='Cumulative difference (KRW/assigned customer)', range=_range(endpoints, padding=0.35), tickformat=",.0f", nticks=4)
    fig.update_yaxes(categoryorder="array", categoryarray=labels, autorange="reversed", tickfont=dict(size=11))
    fig.add_vline(x=0, line_color=GRID, line_width=1)
    return fig


def _safety_effects(experiment):
    base = _frame(experiment, 'Are side effects within tolerance?', height=720, left=185,
                  maturity='Versus no contact · Correction across 4 upper bounds')
    if experiment["status"] != "ready":
        _footer(base, 'Evaluate after 90-day settlement for all ITT customers<br>Do not estimate after excluding immature customers')
        return _unavailable(base)
    fig = make_subplots(rows=2, cols=1, vertical_spacing=0.30, figure=base)
    metrics = ("unsubscribe_60d", "refund_customer_flag")
    names = {"unsubscribe_60d": 'Unsubscribe', "refund_customer_flag": 'Refund customers'}
    for panel, metric in enumerate(metrics, 1):
        rows = [row for row in experiment["guardrails"] if row["metric"] == metric]
        extent = [0]
        if not rows:
            continue
        tolerance = rows[0]["tolerance"] * 100
        extent.append(tolerance)
        domain = fig.layout["yaxis" if panel == 1 else f"yaxis{panel}"].domain
        fig.add_annotation(x=0, y=domain[1], xref="paper", yref="paper", xanchor="left", yanchor="bottom",
                           yshift=12, xshift=8 - fig.layout.margin.l,
                           text=f'<b>{names[metric]}</b> · Tolerance {tolerance:g} pp', showarrow=False,
                           font=dict(size=13, color=INK))
        for row in rows:
            arm, estimate, upper = row["treatment_arm"], row["estimate"], row["ci_upper"]
            label, color = ARM_LABELS[arm], ARM_COLORS[arm]
            if estimate is None:
                continue
            point, bound = estimate * 100, None if upper is None else upper * 100
            extent.extend([point, bound])
            assessment = 'Within tolerance' if row["assessment"] == "within_tolerance" else 'Not established'
            fig.add_trace(go.Scatter(
                x=[point], y=[label], mode="markers+text", marker=dict(size=11, color=color),
                text=[f'{point:+.2f} pp'], textposition="top center", textfont=dict(size=12), cliponaxis=False,
                error_x=None if bound is None else dict(type="data", symmetric=False, array=[max(0, bound - point)],
                                                       arrayminus=[0], color=color, thickness=2, width=7),
                customdata=[[_number(bound, 2, signed=True), tolerance, row["n_treatment"], row["n_reference"],
                             row["one_sided_confidence"] * 100, assessment]],
                hovertemplate=(f'{label} − no contact<br>Risk difference %{{x:+.2f}} pp<br>Adjusted upper bound %{{customdata[0]}} pp / tolerance %{{customdata[1]:g}} pp<br>Individual one-sided confidence %{{customdata[4]:.2f}}%<br>Treatment %{{customdata[2]:,}} / control %{{customdata[3]:,}}<br>%{{customdata[5]}}<extra></extra>'),
            ), row=panel, col=1)
        fig.add_vline(x=0, line_color=GRID, line_width=1, row=panel, col=1)
        fig.add_vline(x=tolerance, line_color=MUTED, line_width=1.5, line_dash="dash", row=panel, col=1)
        fig.update_xaxes(range=_range(extent, padding=0.27), tickformat=".1f", nticks=4, showgrid=True,
                         gridcolor=GRID, zeroline=False, row=panel, col=1)
        fig.update_yaxes(categoryorder="array", categoryarray=['Information', 'Information + coupon'], autorange=False, range=[1.4, -0.4],
                         showgrid=False, automargin=True, row=panel, col=1)
    fig.update_xaxes(title='Increase vs no contact (pp)', row=2, col=1)
    _footer(fig, 'Point: risk difference · Right end: adjusted one-sided bound<br>Dashed line: prespecified tolerance; compare the upper bound<br>Safety assessment differs from two-sided 95% intervals')
    return fig


def _balance(experiment, checks):
    rows = checks["balance"]["features"]
    fig = _frame(experiment, 'Are baseline features balanced?', height=max(540, 305 + len(rows) * 33), left=210,
                 maturity='Baseline features · All assigned customers')
    _footer(fig, 'Points: maximum |SMD| across three comparisons<br>0.1 is a balance reference, not a causal validity threshold<br>Undefined values are shown as NA')
    if not rows:
        return _unavailable(fig, 'No baseline balance diagnosis available.')
    reference = checks["balance"]["reference_threshold"]
    extent, labels = [reference], []
    for row in rows:
        label = FEATURE_LABELS.get(row["feature"], row["feature"])
        labels.append(label)
        value = row["max_abs_smd"]
        if value is None:
            fig.add_annotation(x=0.03, y=label, xref="paper", yref="y", text='NA · Undefined',
                               showarrow=False, xanchor="left", font=dict(size=11, color=MUTED))
            continue
        extent.append(value)
        comparisons = []
        for item in row["comparisons"]:
            name = CONTRAST_LABELS.get(item["contrast"], item["contrast"])
            level = "" if item.get("level") is None else f" · Category {escape(str(item['level']))}"
            comparisons.append(f"{name}: {_number(item['smd'], 3, signed=True)}{level}")
        undefined = row.get("undefined_comparisons", [])
        note = '<br>Some comparisons are separately undefined' if undefined else ""
        fig.add_trace(go.Scatter(
            x=[value], y=[label], mode="markers+text", marker=dict(size=9, color=BLUE),
            text=[f"{value:.3f}"], textposition="middle right", textfont=dict(size=10),
            hovertemplate=f"{escape(label)}<br>Maximum |SMD| %{{x:.4f}}<br>{'<br>'.join(comparisons)}{note}<extra></extra>",
        ))
    fig.add_vline(x=reference, line_color=MUTED, line_dash="dash", line_width=1.3)
    maximum = max(extent)
    fig.update_xaxes(title='Maximum absolute standardized difference', range=[-0.005, max(0.14, maximum * 1.35)], tickformat=".2f", nticks=4)
    fig.update_yaxes(categoryorder="array", categoryarray=labels, autorange="reversed", tickfont=dict(size=11))
    return fig


def create_experiment_figures(experiment, checks) -> dict[str, go.Figure]:
    """Create five figures using only supplied training estimates and checks."""
    if experiment["metadata"].get("analysis_scope") != "train":
        raise ValueError("Stage 3 visuals accept training estimates only")
    return dict(zip(FIGURE_IDS, (_arm_profit(experiment), _profit_effects(experiment),
                                _coupon_info_waterfall(experiment, checks), _safety_effects(experiment),
                                _balance(experiment, checks))))
