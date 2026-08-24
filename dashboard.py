#!/usr/bin/env python
"""Generate an HTML dashboard from a solved MMS optimization output JSON."""

import argparse
import html
import json
from pathlib import Path


PRODUCTION_GROUPS = {
    "thermal": ("Thermal units", "#1f77b4"),
    "wind": ("Wind parks", "#2ca02c"),
    "pv": ("PVs", "#ffbf00"),
}

RESERVE_SERIES = {
    "Primary upward": ("Primary_Active_Power_Reserves(MW)", 0, "#7b2cbf"),
    "Primary downward": ("Primary_Active_Power_Reserves(MW)", 1, "#b185db"),
    "Secondary upward": ("Secondary_Active_Power_Reserves(MW)", 0, "#d62728"),
    "Secondary downward": ("Secondary_Active_Power_Reserves(MW)", 1, "#ff9896"),
    "Tertiary upward": ("Tertiary_Active_Power_Reserves(MW)", 0, "#8c564b"),
    "Tertiary downward": ("Tertiary_Active_Power_Reserves(MW)", 1, "#c49c94"),
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Create an HTML dashboard from optimization_output.json."
    )
    parser.add_argument(
        "output_json",
        nargs="?",
        default="optimization_output.json",
        help="Solved optimization output JSON. Defaults to optimization_output.json.",
    )
    parser.add_argument(
        "-o",
        "--dashboard",
        default="dashboard.html",
        help="HTML dashboard path. Defaults to dashboard.html.",
    )
    return parser.parse_args()


def numeric_series(values):
    if not isinstance(values, list):
        return []
    return [float(value or 0.0) for value in values]


def add_series(left, right):
    size = max(len(left), len(right))
    total = [0.0] * size
    for index, value in enumerate(left):
        total[index] += float(value)
    for index, value in enumerate(right):
        total[index] += float(value)
    return total


def unit_group(unit):
    comments = str(unit.get("comments", "")).strip().lower()
    if comments.startswith("thermo"):
        return "thermal"
    if comments.startswith("res"):
        return "wind"
    if comments.startswith("pv"):
        return "pv"
    return None


def aggregate_output(data):
    units = data.get("Generating_Units", [])
    periods = max((len(numeric_series(unit.get("Power"))) for unit in units), default=0)

    production = {key: [0.0] * periods for key in PRODUCTION_GROUPS}
    reserves = {name: [0.0] * periods for name in RESERVE_SERIES}

    for unit in units:
        group = unit_group(unit)
        if group in production:
            production[group] = add_series(production[group], numeric_series(unit.get("Power")))

        for label, (field, direction_index, _color) in RESERVE_SERIES.items():
            reserve_pair = unit.get(field, [])
            if isinstance(reserve_pair, list) and len(reserve_pair) > direction_index:
                reserves[label] = add_series(
                    reserves[label], numeric_series(reserve_pair[direction_index])
                )

    return production, reserves


def nice_max(series_by_name):
    values = [value for series in series_by_name.values() for value in series]
    maximum = max(values, default=0.0)
    return maximum if maximum > 0 else 1.0


def svg_line_chart(title, series_by_name, colors_by_name, y_label):
    width = 980
    height = 360
    pad_left = 62
    pad_right = 24
    pad_top = 42
    pad_bottom = 54
    plot_width = width - pad_left - pad_right
    plot_height = height - pad_top - pad_bottom
    periods = max((len(series) for series in series_by_name.values()), default=0)
    y_max = nice_max(series_by_name)

    def x_pos(index):
        if periods <= 1:
            return pad_left
        return pad_left + (index / (periods - 1)) * plot_width

    def y_pos(value):
        return pad_top + plot_height - (float(value) / y_max) * plot_height

    y_ticks = []
    for step in range(5):
        value = y_max * step / 4
        y = y_pos(value)
        y_ticks.append(
            f'<line x1="{pad_left}" x2="{width - pad_right}" y1="{y:.2f}" y2="{y:.2f}" />'
            f'<text x="{pad_left - 10}" y="{y + 4:.2f}" text-anchor="end">{value:.1f}</text>'
        )

    lines = []
    for name, series in series_by_name.items():
        if not series:
            continue
        points = " ".join(f"{x_pos(i):.2f},{y_pos(value):.2f}" for i, value in enumerate(series))
        color = colors_by_name[name]
        lines.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" '
            'stroke-width="3" stroke-linejoin="round" stroke-linecap="round" />'
        )

    x_ticks = []
    for index in range(periods):
        if periods > 12 and index not in {0, periods - 1} and (index + 1) % 4 != 0:
            continue
        x = x_pos(index)
        x_ticks.append(
            f'<line x1="{x:.2f}" x2="{x:.2f}" y1="{height - pad_bottom}" '
            f'y2="{height - pad_bottom + 5}" />'
            f'<text x="{x:.2f}" y="{height - 22}" text-anchor="middle">{index + 1}</text>'
        )

    legend = []
    legend_x = pad_left
    legend_y = 18
    for name, color in colors_by_name.items():
        legend.append(
            f'<span class="legend-item"><span class="swatch" '
            f'style="background:{color}"></span>{html.escape(name)}</span>'
        )

    return f"""
    <section class="panel">
      <div class="panel-title">
        <h2>{html.escape(title)}</h2>
        <span>{html.escape(y_label)}</span>
      </div>
      <div class="legend">{"".join(legend)}</div>
      <svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">
        <g class="grid">{"".join(y_ticks)}</g>
        <g class="axis">
          <line x1="{pad_left}" x2="{width - pad_right}" y1="{height - pad_bottom}" y2="{height - pad_bottom}" />
          <line x1="{pad_left}" x2="{pad_left}" y1="{pad_top}" y2="{height - pad_bottom}" />
          {"".join(x_ticks)}
        </g>
        <text class="axis-label" x="{width / 2:.0f}" y="{height - 4}" text-anchor="middle">Dispatch period</text>
        <text class="axis-label" x="16" y="{height / 2:.0f}" transform="rotate(-90 16 {height / 2:.0f})" text-anchor="middle">{html.escape(y_label)}</text>
        {"".join(lines)}
      </svg>
    </section>
    """


def summary_cards(production, reserves, status):
    cards = []
    for key, (label, color) in PRODUCTION_GROUPS.items():
        cards.append((label, sum(production[key]), "period-MW", color))
    for label in ("Primary upward", "Secondary upward", "Tertiary upward"):
        cards.append((label, sum(reserves[label]), "period-MW", RESERVE_SERIES[label][2]))

    card_html = [
        f"""
        <article class="card" style="border-top-color:{color}">
          <span>{html.escape(label)}</span>
          <strong>{value:,.2f}</strong>
          <em>{unit}</em>
        </article>
        """
        for label, value, unit, color in cards
    ]
    card_html.insert(
        0,
        f"""
        <article class="card status">
          <span>Solution status</span>
          <strong>{html.escape(str(status))}</strong>
          <em>from output JSON</em>
        </article>
        """,
    )
    return "\n".join(card_html)


def build_dashboard(data, production, reserves):
    production_names = {key: label for key, (label, _color) in PRODUCTION_GROUPS.items()}
    production_series = {
        production_names[key]: values for key, values in production.items()
    }
    production_colors = {
        label: color for label, color in (value for value in PRODUCTION_GROUPS.values())
    }
    reserve_colors = {label: color for label, (_field, _direction, color) in RESERVE_SERIES.items()}
    status = data.get("Solution_Status", "unknown")

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MMS Optimization Dashboard</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #172033;
      --muted: #667085;
      --line: #d9dee8;
      --panel: #ffffff;
      --page: #f5f7fb;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--page);
      color: var(--ink);
      font-family: "Segoe UI", Arial, sans-serif;
    }}
    main {{
      width: min(1180px, calc(100vw - 32px));
      margin: 28px auto 40px;
    }}
    header {{
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 20px;
      margin-bottom: 18px;
    }}
    h1, h2, p {{ margin: 0; }}
    h1 {{ font-size: 28px; line-height: 1.2; }}
    header p {{ color: var(--muted); margin-top: 6px; }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-top: 4px solid #8a94a6;
      border-radius: 8px;
      padding: 12px 14px;
      min-height: 104px;
    }}
    .card span, .card em {{
      display: block;
      color: var(--muted);
      font-size: 13px;
      font-style: normal;
    }}
    .card strong {{
      display: block;
      margin: 10px 0 6px;
      font-size: 24px;
      line-height: 1.1;
    }}
    .status strong {{
      font-size: 20px;
      text-transform: capitalize;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      margin-top: 16px;
    }}
    .panel-title {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 16px;
      margin-bottom: 8px;
    }}
    .panel-title h2 {{ font-size: 18px; }}
    .panel-title span {{ color: var(--muted); font-size: 13px; }}
    .legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px 16px;
      margin: 6px 0 10px;
      color: var(--muted);
      font-size: 13px;
    }}
    .legend-item {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      white-space: nowrap;
    }}
    .swatch {{
      width: 11px;
      height: 11px;
      border-radius: 50%;
      display: inline-block;
    }}
    svg {{
      display: block;
      width: 100%;
      height: auto;
    }}
    .grid line {{
      stroke: #e7ebf2;
      stroke-width: 1;
    }}
    .grid text, .axis text, .axis-label {{
      fill: var(--muted);
      font-size: 12px;
    }}
    .axis line {{
      stroke: #98a2b3;
      stroke-width: 1;
    }}
    @media (max-width: 760px) {{
      main {{ width: min(100vw - 20px, 1180px); margin-top: 16px; }}
      header {{ display: block; }}
      h1 {{ font-size: 23px; }}
      .card strong {{ font-size: 20px; }}
      .panel {{ padding: 12px; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>MMS Optimization Dashboard</h1>
        <p>Aggregated production and active power reserves after solution.</p>
      </div>
    </header>
    <section class="cards">
      {summary_cards(production, reserves, status)}
    </section>
    {svg_line_chart("Aggregated Production", production_series, production_colors, "MW")}
    {svg_line_chart("Active Power Reserves", reserves, reserve_colors, "MW")}
  </main>
</body>
</html>
"""


def main():
    args = parse_args()
    output_json = Path(args.output_json)
    dashboard_path = Path(args.dashboard)

    with output_json.open("r", encoding="utf-8") as f:
        data = json.load(f)

    production, reserves = aggregate_output(data)
    dashboard_path.write_text(build_dashboard(data, production, reserves), encoding="utf-8")
    print(f"Dashboard written to: {dashboard_path}")


if __name__ == "__main__":
    main()
