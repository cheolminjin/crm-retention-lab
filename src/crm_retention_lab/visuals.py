"""Plot precomputed diagnostics; never refit or read observed/oracle records.

All reported rates and intervals come from ``diagnostics``. Immature cohort
cells remain missing. HTML fragments deliberately omit Plotly.js so a report
can embed the installed bundle once; standalone export embeds it locally.
"""

import importlib.util
import re
from html import escape
from pathlib import Path

import plotly
import plotly.graph_objects as go
import plotly.io as pio


INK = "#172b4d"
MUTED = "#52637a"
BLUE = "#2563eb"
ORANGE = "#d76b2d"
GRID = "#e8edf3"
FONT = "Segoe UI, Arial, sans-serif"
PACK_COLORS = {200: BLUE, 500: ORANGE, 1000: MUTED}
PACK_DASHES = {200: "solid", 500: "dash", 1000: "dot"}
FIGURE_IDS = ("eligibility_flow", "cohort_heatmap", "pack_km", "pack_repeat_60d")
PLOTLY_CONFIG = {
    "responsive": True,
    "displaylogo": False,
    "displayModeBar": True,
    "scrollZoom": False,
    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
}


def _percent(value):
    return "NA" if value is None else f"{value:.1%}"


def _rgba(hex_color, alpha):
    values = [int(hex_color[index:index + 2], 16) for index in (1, 3, 5)]
    return f"rgba({values[0]},{values[1]},{values[2]},{alpha})"


def _base(diagnostics, title, population, maturity, height=510):
    metadata = diagnostics["metadata"]
    snapshot = metadata.get("snapshot_id", metadata.get("analysis_id", metadata.get("input_simulation_id", 'No ID')))
    as_of = str(metadata["as_of"])
    caption = (f'Synthetic data · Training · As of {escape(as_of[:10])}<br>{escape(population)}<br>{escape(maturity)}<br>Snapshot {escape(str(snapshot))}')
    fig = go.Figure()
    fig.update_layout(
        template="plotly_white", height=height, autosize=True,
        paper_bgcolor="white", plot_bgcolor="white",
        font=dict(family=FONT, size=12, color=INK),
        title=dict(text=title, x=0.01, xanchor="left", y=0.98, yanchor="top",
                   font=dict(size=21, color=INK)),
        margin=dict(l=80, r=32, t=160, b=115),
        hoverlabel=dict(bgcolor="white", bordercolor=GRID, font=dict(family=FONT, size=12)),
        legend=dict(orientation="h", x=0, y=1.02, xanchor="left", yanchor="bottom",
                    font=dict(size=11), groupclick="togglegroup"),
        meta={"input_simulation_id": metadata.get("input_simulation_id"),
              "snapshot_id": snapshot, "as_of": as_of,
              "analysis_scope": metadata.get("analysis_scope", "train"),
              "population": population, "maturity": maturity, "synthetic": True},
        uirevision=str(snapshot),
        annotations=[dict(x=0, y=1.16, xref="paper", yref="paper", xanchor="left", yanchor="bottom",
                          xshift=-72, text=caption, showarrow=False, align="left", font=dict(size=11, color=MUTED))],
    )
    fig.update_xaxes(showgrid=True, gridcolor=GRID, zeroline=False, automargin=True,
                     ticks="outside", tickcolor=GRID, title_font=dict(size=12), fixedrange=False)
    fig.update_yaxes(showgrid=False, zeroline=False, automargin=True, title_font=dict(size=12), fixedrange=False)
    return fig


def _footnote(fig, text):
    # Align captions with the canvas edge, including narrow mobile viewports.
    shift = 8 - fig.layout.margin.l
    for annotation in fig.layout.annotations:
        annotation.xshift = shift
    fig.add_annotation(x=0, y=0, xref="paper", yref="paper", xanchor="left", yanchor="top",
                       xshift=shift, yshift=-63, text=text, showarrow=False, align="left", font=dict(size=11, color=MUTED))


def _empty(fig, message):
    fig.add_annotation(x=0.5, y=0.5, xref="paper", yref="paper", text=message,
                       showarrow=False, font=dict(size=15, color=MUTED))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig


def _eligibility_flow(diagnostics):
    flow = diagnostics["eligibility_flow"]
    stages = [('First delivery', flow["first_delivery_customers"]),
              ('Reached D+14', flow["d14_reached"]),
              ('Eligible', flow["eligible"]),
              ('Randomized', flow["assigned_total"])]
    total = flow["first_delivery_customers"]
    fig = _base(diagnostics, 'How many customers are eligible?', f'First-delivery customers: {total:,}',
                'Eligibility at the reference time', height=490)
    if not total:
        return _empty(fig, 'No first-delivery customers in this scope.')
    values = [count for _, count in stages]
    fig.add_trace(go.Bar(
        x=values, y=[label for label, _ in stages], orientation="h",
        marker_color=["#b3bfcd", "#7f91a8", BLUE, INK], width=0.56,
        text=[f'{count:,} customers<br>{count / total:.1%}' for count in values],
        textposition="outside", cliponaxis=False, textfont=dict(size=13, color=INK),
        customdata=[[count / total] for count in values],
        hovertemplate='%{y}<br>%{x:,} customers<br>%{customdata[0]:.1%} of first-delivery customers<extra></extra>',
        showlegend=False,
    ))
    fig.update_xaxes(title='Customers', range=[0, max(values) * 1.5], tickformat=",", separatethousands=True)
    fig.update_yaxes(autorange="reversed")
    _footnote(fig, f"Eligibility flow, distinct from a churn rate.<br>Before D+14: {flow['d14_pending']:,} · Excluded: {flow['ineligible']:,}<br>Exclusion reasons may overlap")
    return fig


def _cohort_heatmap(diagnostics):
    cohorts = sorted(diagnostics["cohorts"], key=lambda row: row["assigned_month"])
    total = sum(row["n_control"] for row in cohorts)
    fig = _base(diagnostics, 'Repurchase by assignment month', f'No-contact assignments: {total:,}',
                'Entire cohort passes assignment+90-day freeze', height=max(490, min(900, 310 + len(cohorts) * 45)))
    if not cohorts:
        return _empty(fig, 'No assigned no-contact cohorts in this scope.')
    days = (7, 14, 30, 60)
    labels = [f"{row['assigned_month']}<br>n={row['n_control']:,}" for row in cohorts]
    z, text, custom, missing_x, missing_y, missing_custom = [], [], [], [], [], []
    for cohort, label in zip(cohorts, labels):
        cells = {cell["day"]: cell for cell in cohort["cells"]}
        row_z, row_text, row_custom = [], [], []
        for day in days:
            cell = cells.get(day, {})
            mature = cohort["is_fully_mature"] and cell.get("is_mature", False)
            rate = cell.get("rate") if mature else None
            row_z.append(rate)
            row_text.append(_percent(rate))
            row_custom.append([cell.get("n", 0), cell.get("events", 0),
                               _percent(cell.get("ci_lower")), _percent(cell.get("ci_upper"))])
            if rate is None:
                missing_x.append(f'{day} days')
                missing_y.append(label)
                missing_custom.append([cohort["n_control"], 'Before label freeze' if not mature else 'No denominator'])
        z.append(row_z)
        text.append(row_text)
        custom.append(row_custom)
    fig.add_trace(go.Heatmap(
        x=[f'{day} days' for day in days], y=labels, z=z,
        zmin=0, zmax=1, colorscale=[[0, "#fff7ed"], [0.4, "#f5b98a"], [0.7, "#e88c4a"], [1, "#b54b12"]],
        xgap=5, ygap=5, text=text, texttemplate="%{text}", textfont=dict(size=14),
        customdata=custom, hoverongaps=False,
        hovertemplate=('%{y}<br>Since assignment: %{x} · Cumulative payment rate %{z:.1%}<br>Purchasers %{customdata[1]:,} / %{customdata[0]:,} customers<br>95% interval %{customdata[2]}–%{customdata[3]}<extra></extra>'),
        colorbar=dict(title='Cumulative<br>payment rate', tickformat=".0%", thickness=10, len=0.88),
    ))
    if missing_x:
        fig.add_trace(go.Scatter(
            x=missing_x, y=missing_y, mode="markers+text", text=["NA"] * len(missing_x),
            marker=dict(size=28, color="rgba(0,0,0,0)"), textfont=dict(color=MUTED, size=13),
            customdata=missing_custom,
            hovertemplate='%{y}<br>Since assignment: %{x} · %{customdata[1]}<br>Cohort %{customdata[0]:,} customers · Distinct from 0%<extra></extra>',
            showlegend=False,
        ))
    fig.update_layout(plot_bgcolor="#f0f3f7", margin=dict(l=95, r=65))
    fig.update_xaxes(title='Days since assignment', side="bottom", showgrid=False)
    fig.update_yaxes(autorange="reversed", showgrid=False)
    _footnote(fig, 'NA: immature or no denominator; distinct from 0%<br>Entire cohort must pass the assignment+90-day freeze<br>Additional payments remain events after refunds')
    return fig


def _pack_km(diagnostics):
    curves = sorted((row for row in diagnostics["km_curves"] if row["first_pack_grams"] in PACK_COLORS),
                    key=lambda row: row["first_pack_grams"])
    total = sum(row["n"] for row in curves)
    fig = _base(diagnostics, 'When do customers repurchase?', f'No-contact assignments: {total:,}',
                'Right-censored at observation end', height=580)
    if not total:
        return _empty(fig, 'No package-size control groups in this scope.')
    for curve in curves:
        pack, points = curve["first_pack_grams"], curve["points"]
        if not curve["n"] or not points:
            continue
        group, color = str(pack), PACK_COLORS[pack]
        x = [point["day"] for point in points]
        lower = [point["cumulative_repurchase_ci_lower"] for point in points]
        upper = [point["cumulative_repurchase_ci_upper"] for point in points]
        y = [point["cumulative_repurchase"] for point in points]
        for bounds, fill in ((lower, None), (upper, "tonexty")):
            fig.add_trace(go.Scatter(x=x, y=bounds, mode="lines", line=dict(width=0, shape="hv"),
                                     fill=fill, fillcolor=_rgba(color, 0.11), connectgaps=False,
                                     legendgroup=group, showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(
            x=x, y=y, mode="lines", name=f"{pack:,}g · n={curve['n']:,}", legendgroup=group,
            line=dict(color=color, width=2.7, dash=PACK_DASHES[pack], shape="hv"), connectgaps=False,
            customdata=[[point.get("at_risk", 0), point.get("events", 0), point.get("censored", 0),
                         _percent(point["cumulative_repurchase_ci_lower"]),
                         _percent(point["cumulative_repurchase_ci_upper"])] for point in points],
            hovertemplate=(f'First package: {pack:,}g<br>%{{x:.1f}} days after assignment · Cumulative repurchase %{{y:.1%}}<br>95% interval %{{customdata[3]}}–%{{customdata[4]}}<br>Risk set immediately before time: %{{customdata[0]:,}}<br>Payments %{{customdata[1]:,}} · Censored %{{customdata[2]:,}}<extra></extra>'),
        ))
        marks = [mark for mark in curve.get("censor_marks", []) if mark.get("cumulative_repurchase") is not None]
        if marks:
            fig.add_trace(go.Scatter(
                x=[mark["day"] for mark in marks], y=[mark["cumulative_repurchase"] for mark in marks],
                mode="markers", marker=dict(symbol="line-ns", size=7, color=color, line=dict(width=1, color=color)),
                customdata=[[mark["n"]] for mark in marks], legendgroup=group, showlegend=False,
                hovertemplate=f'{pack:,}g · %{{x:.1f}} days after assignment<br>Right-censored: %{{customdata[0]:,}}<extra></extra>',
            ))
    fig.update_layout(hovermode="closest", margin=dict(t=175, b=115),
                      legend=dict(y=0.99, yanchor="top", bgcolor="rgba(255,255,255,0.88)"))
    fig.update_xaxes(title='Days since assignment', range=[0, 60], tickvals=[0, 7, 14, 30, 45, 60])
    fig.update_yaxes(title='Cumulative repurchase · 1−S(t)', tickformat=".0%", range=[0, 1], showgrid=True, gridcolor=GRID)
    _footnote(fig, 'KM 1−S(t) · Shading: pointwise 95% interval<br>Short ticks: censoring · Hover: risk-set size<br>Does not identify optimal timing or causal effects')
    return fig


def _pack_repeat_60d(diagnostics):
    segments = sorted((row for row in diagnostics["segments"]
                       if row["feature"] == "first_pack_grams" and row["value"] in PACK_COLORS),
                      key=lambda row: row["value"])
    total = sum(row["n_mature"] for row in segments)
    fig = _base(diagnostics, 'Repurchase by package size', f'Settled control customers: {total:,}',
                'Labels frozen at assignment+90 days', height=490)
    if not segments:
        return _empty(fig, 'No package-size diagnostic aggregates in this scope.')
    labels = [f"{row['value']:,}g · n={row['n_mature']:,}" for row in segments]
    for row, label in zip(segments, labels):
        rate, low, high = row["rate"], row["ci_lower"], row["ci_upper"]
        if rate is None or low is None or high is None:
            fig.add_trace(go.Scatter(x=[0.03], y=[label], mode="text", text=["NA"],
                                     textfont=dict(color=MUTED), showlegend=False,
                                     hovertemplate='No settled customers · Distinct from 0%<extra></extra>'))
            continue
        fig.add_trace(go.Scatter(
            x=[rate], y=[label], mode="markers+text", text=[_percent(rate)], textposition="top center",
            cliponaxis=False, textfont=dict(size=14, color=INK), marker=dict(size=12, color=PACK_COLORS[row["value"]]),
            error_x=dict(type="data", symmetric=False, array=[high - rate], arrayminus=[rate - low],
                         color=PACK_COLORS[row["value"]], thickness=2, width=7),
            customdata=[[row["events"], row["n_mature"], row["n_eligible_control"], low, high]],
            hovertemplate=('%{y}<br>60-day additional payment rate %{x:.1%}<br>95% interval %{customdata[3]:.1%}–%{customdata[4]:.1%}<br>Purchasers %{customdata[0]:,} / settled customers %{customdata[1]:,}<br>All control assignments in this size group: %{customdata[2]:,}<extra></extra>'),
            showlegend=False,
        ))
    fig.update_layout(margin=dict(l=125, r=40))
    fig.update_xaxes(title='Additional payment within 60 days of assignment', tickformat=".0%", range=[0, 1.12], tickvals=[0, 0.25, 0.5, 0.75, 1])
    fig.update_yaxes(categoryorder="array", categoryarray=labels, range=[len(labels) - 0.4, -0.7], autorange=False)
    _footnote(fig, 'Points: 60-day payment rate · Lines: Wilson 95% interval<br>n: customers with frozen labels · Descriptive size comparison<br>Customer-group differences are distinct from campaign effects')
    return fig


def create_figures(diagnostics: dict) -> dict[str, go.Figure]:
    """Create four control-only planning figures from a diagnostic snapshot."""
    if diagnostics["metadata"].get("analysis_scope", "train") != "train":
        raise ValueError("Stage 2 planning visuals accept the train analysis scope only")
    return dict(zip(FIGURE_IDS, (_eligibility_flow(diagnostics), _cohort_heatmap(diagnostics),
                                _pack_km(diagnostics), _pack_repeat_60d(diagnostics))))


def export_figures(figures, output_dir, *, standalone=False, static_svg=False):
    """Write deterministic local HTML/JSON; optionally inline-JS HTML and SVG.

    SVG is optional: missing Kaleido/Chrome is reported in returned metadata.
    HTML and JSON remain usable when static rendering is unavailable.
    """
    for name in figures:
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise ValueError("Figure IDs must use lowercase letters, digits, and underscores")
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    metadata = {"figures": {}, "plotly_version": plotly.__version__,
                "static_svg": {"requested": static_svg, "status": "not_requested", "errors": []}}
    static_ready = static_svg and importlib.util.find_spec("kaleido") is not None
    if static_svg and not static_ready:
        metadata["static_svg"]["errors"].append("Kaleido is not installed; SVG export was skipped.")
    for name, figure in figures.items():
        paths = {"html": str(output / f"{name}.html"), "json": str(output / f"{name}.json"),
                 "standalone_html": None, "svg": None}
        config = {**PLOTLY_CONFIG, "toImageButtonOptions": {"format": "png", "filename": name, "width": 1200, "height": 720, "scale": 2}}
        pio.write_html(figure, paths["html"], config=config, full_html=False, include_plotlyjs=False,
                       include_mathjax=False, div_id=f"crm-{name}", auto_open=False)
        Path(paths["json"]).write_text(pio.to_json(figure, pretty=True, remove_uids=True, engine="json"), encoding="utf-8")
        if standalone:
            paths["standalone_html"] = str(output / f"{name}.standalone.html")
            pio.write_html(figure, paths["standalone_html"], config=config, full_html=True, include_plotlyjs=True,
                           include_mathjax=False, div_id=f"crm-{name}", auto_open=False)
        if static_ready:
            svg = output / f"{name}.svg"
            try:
                import kaleido
                kaleido.write_fig_sync(figure, path=svg,
                                      opts={"format": "svg", "width": 1100, "height": figure.layout.height or 560},
                                      kopts={"mathjax": False, "timeout": 30})
                paths["svg"] = str(svg)
            except Exception as exc:  # Optional renderer failures do not invalidate interactive artifacts.
                metadata["static_svg"]["errors"].append(f"{name}: {type(exc).__name__}: {exc}")
        metadata["figures"][name] = paths
    if static_svg:
        exported = sum(row["svg"] is not None for row in metadata["figures"].values())
        metadata["static_svg"]["status"] = "exported" if exported == len(figures) else "partial" if exported else "unavailable"
    return metadata
