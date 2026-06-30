"""
Flask dashboard for Competitive Content Intelligence.
Run: python3 app.py  →  open http://localhost:5000
"""

import json
import subprocess
import sys
from pathlib import Path

from flask import Flask, render_template_string, jsonify
import plotly.graph_objects as go
import plotly.utils

import analyze

app = Flask(__name__)

COMPANY_COLORS = {
    "HubSpot": "#FF7A59",
    "Salesforce": "#00A1E0",
    "Klaviyo": "#12A55C",
    "ActiveCampaign": "#356AE6",
    "Mailchimp": "#FFE01B",
}

COMPANY_TEXT_COLORS = {
    "HubSpot": "#fff",
    "Salesforce": "#fff",
    "Klaviyo": "#fff",
    "ActiveCampaign": "#fff",
    "Mailchimp": "#222",
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Competitive Content Intelligence Dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.30.0.min.js"></script>
<style>
  :root {
    --bg: #0f1117;
    --card: #1a1d2e;
    --border: #2a2d3e;
    --text: #e4e6f1;
    --muted: #8b8fa8;
    --accent: #6c63ff;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; padding: 24px; }
  h1 { font-size: 1.6rem; font-weight: 700; margin-bottom: 4px; }
  .subtitle { color: var(--muted); font-size: 0.85rem; margin-bottom: 28px; }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
  .grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin-bottom: 20px; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
  .card h2 { font-size: 0.95rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; margin-bottom: 14px; }
  .chart { width: 100%; height: 340px; }
  .chart-tall { width: 100%; height: 420px; }
  /* Stat pills */
  .pills { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 20px; }
  .pill { border-radius: 999px; padding: 6px 14px; font-size: 0.78rem; font-weight: 600; display: flex; align-items: center; gap: 6px; }
  .pill .count { font-size: 1.1rem; }
  /* Insights */
  .insights-list { list-style: none; display: flex; flex-direction: column; gap: 12px; }
  .insights-list li { background: var(--bg); border-left: 3px solid var(--accent); border-radius: 0 8px 8px 0; padding: 12px 16px; font-size: 0.88rem; line-height: 1.55; color: var(--text); }
  .insights-list li strong { color: #a5b4fc; }
  /* Trend badges */
  .trend-up   { color: #4ade80; }
  .trend-down { color: #f87171; }
  .trend-flat { color: var(--muted); }
  /* Gap table */
  table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
  th { text-align: left; padding: 8px 10px; color: var(--muted); border-bottom: 1px solid var(--border); font-weight: 500; }
  td { padding: 8px 10px; border-bottom: 1px solid var(--border); vertical-align: middle; }
  .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 4px; }
  .badge { display: inline-block; border-radius: 4px; padding: 2px 7px; font-size: 0.73rem; font-weight: 600; margin: 2px; }
  .badge-cover { background: #14532d; color: #4ade80; }
  .badge-miss  { background: #7f1d1d; color: #fca5a5; }
  /* Refresh button */
  .refresh-btn { float: right; background: var(--accent); color: #fff; border: none; border-radius: 8px; padding: 8px 16px; font-size: 0.82rem; cursor: pointer; }
  .refresh-btn:hover { opacity: .85; }
</style>
</head>
<body>

<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">
  <h1>📊 Competitive Content Intelligence</h1>
  <button class="refresh-btn" onclick="refreshData()">↺ Refresh Data</button>
</div>
<p class="subtitle">SaaS Marketing Tools — {{ meta.total_posts }} posts indexed across {{ companies|length }} companies &nbsp;·&nbsp; Last fetched: {{ meta.fetched_at[:16].replace("T"," ") }} UTC</p>

<!-- Company stat pills -->
<div class="pills">
  {% for c in companies %}
  <div class="pill" style="background:{{ colors[c] }};color:{{ text_colors[c] }}">
    <span class="count">{{ totals[c] }}</span> {{ c }}
    <span class="{{ 'trend-up' if trends[c].direction=='up' else 'trend-down' if trends[c].direction=='down' else 'trend-flat' }}">
      {% if trends[c].direction=='up' %}▲{% elif trends[c].direction=='down' %}▼{% else %}–{% endif %}
    </span>
  </div>
  {% endfor %}
</div>

<!-- Row 1: Volume bar + Monthly trend -->
<div class="grid-2">
  <div class="card">
    <h2>Total Content Volume</h2>
    <div id="chart-volume" class="chart"></div>
  </div>
  <div class="card">
    <h2>Publishing Frequency — Monthly</h2>
    <div id="chart-monthly" class="chart"></div>
  </div>
</div>

<!-- Row 2: Topic heatmap + Topic grouped bar -->
<div class="grid-2">
  <div class="card">
    <h2>Topic Distribution Heatmap</h2>
    <div id="chart-heatmap" class="chart-tall"></div>
  </div>
  <div class="card">
    <h2>Topic Coverage by Company</h2>
    <div id="chart-topics" class="chart-tall"></div>
  </div>
</div>

<!-- Row 3: Gap table + Trend comparison -->
<div class="grid-2">
  <div class="card">
    <h2>Content Gap Analysis</h2>
    <table>
      <thead>
        <tr><th>Topic</th><th>Covers</th><th>Missing</th></tr>
      </thead>
      <tbody>
        {% for topic, gap in gaps.items() %}
        <tr>
          <td><strong>{{ topic }}</strong></td>
          <td>{% for c in gap.covers %}<span class="badge badge-cover" style="border-left:3px solid {{colors[c]}}">{{ c }}</span>{% endfor %}</td>
          <td>{% for c in gap.missing %}<span class="badge badge-miss">{{ c }}</span>{% endfor %}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  <div class="card">
    <h2>90-Day Publishing Trend (Recent vs Prior)</h2>
    <div id="chart-trend" class="chart"></div>
  </div>
</div>

<!-- Insights -->
<div class="card">
  <h2>🧠 Synthesized Competitive Insights</h2>
  <ul class="insights-list" style="margin-top:8px;">
    {% for ins in insights %}
    <li>{{ ins | markdown_bold }}</li>
    {% endfor %}
  </ul>
</div>

<p style="text-align:center;color:var(--muted);font-size:0.75rem;margin-top:20px;">
  Data sourced via RSS &amp; web scraping · Not affiliated with any listed company
</p>

<script>
const charts = {{ charts_json }};

Plotly.newPlot('chart-volume',   charts.volume.data,   charts.volume.layout,   {responsive:true, displayModeBar:false});
Plotly.newPlot('chart-monthly',  charts.monthly.data,  charts.monthly.layout,  {responsive:true, displayModeBar:false});
Plotly.newPlot('chart-heatmap',  charts.heatmap.data,  charts.heatmap.layout,  {responsive:true, displayModeBar:false});
Plotly.newPlot('chart-topics',   charts.topics.data,   charts.topics.layout,   {responsive:true, displayModeBar:false});
Plotly.newPlot('chart-trend',    charts.trend.data,    charts.trend.layout,    {responsive:true, displayModeBar:false});

function refreshData() {
  fetch('/api/refresh', {method:'POST'})
    .then(r => r.json())
    .then(d => { if(d.ok) location.reload(); });
}
</script>
</body>
</html>
"""


def markdown_bold(text: str) -> str:
    """Convert **bold** to <strong>bold</strong>."""
    import re
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)


def build_charts(result: dict) -> dict:
    companies = result["companies"]
    colors = [COMPANY_COLORS[c] for c in companies]
    topic_dist = result["topic_dist"]
    all_topics = result["all_topics"]
    monthly_counts = result["monthly_counts"]
    all_months = result["all_months"]
    trends = result["trends"]

    bg = "#1a1d2e"
    text_color = "#e4e6f1"
    grid_color = "#2a2d3e"
    layout_base = dict(
        paper_bgcolor=bg,
        plot_bgcolor=bg,
        font=dict(color=text_color, family="-apple-system, sans-serif", size=11),
        margin=dict(l=10, r=10, t=30, b=40),
        legend=dict(bgcolor="rgba(0,0,0,0)", font_size=10),
    )

    def axis_style(**kwargs):
        return dict(
            gridcolor=grid_color,
            linecolor=grid_color,
            zerolinecolor=grid_color,
            **kwargs,
        )

    # 1. Volume bar
    totals = {c: sum(topic_dist[c].values()) for c in companies}
    volume = go.Figure(
        go.Bar(
            x=companies,
            y=[totals[c] for c in companies],
            marker_color=colors,
            text=[totals[c] for c in companies],
            textposition="outside",
        )
    )
    volume.update_layout(
        **layout_base,
        yaxis=axis_style(title="Posts"),
        xaxis=axis_style(),
        showlegend=False,
    )

    # 2. Monthly line chart
    monthly_fig = go.Figure()
    for c in companies:
        y = [monthly_counts[c].get(m, 0) for m in all_months]
        monthly_fig.add_trace(
            go.Scatter(
                x=all_months,
                y=y,
                name=c,
                line=dict(color=COMPANY_COLORS[c], width=2),
                mode="lines+markers",
                marker=dict(size=5),
            )
        )
    monthly_fig.update_layout(
        **layout_base,
        yaxis=axis_style(title="Posts"),
        xaxis=axis_style(tickangle=-30),
    )

    # 3. Heatmap
    z_vals = [
        [topic_dist[c].get(t, 0) for c in companies] for t in all_topics
    ]
    heatmap = go.Figure(
        go.Heatmap(
            z=z_vals,
            x=companies,
            y=all_topics,
            colorscale="Viridis",
            text=z_vals,
            texttemplate="%{text}",
            showscale=True,
            colorbar=dict(thickness=10, tickfont=dict(color=text_color)),
        )
    )
    heatmap_layout = {**layout_base, "margin": dict(l=160, r=10, t=10, b=60)}
    heatmap.update_layout(
        **heatmap_layout,
        yaxis=dict(autorange="reversed", tickfont=dict(size=10)),
        xaxis=axis_style(),
    )

    # 4. Topic grouped bar (top 8 topics)
    top_topics = sorted(
        all_topics,
        key=lambda t: sum(topic_dist[c].get(t, 0) for c in companies),
        reverse=True,
    )[:8]
    topics_fig = go.Figure()
    for c in companies:
        topics_fig.add_trace(
            go.Bar(
                name=c,
                x=top_topics,
                y=[topic_dist[c].get(t, 0) for t in top_topics],
                marker_color=COMPANY_COLORS[c],
            )
        )
    topics_fig.update_layout(
        **layout_base,
        barmode="group",
        yaxis=axis_style(title="Posts"),
        xaxis=axis_style(tickangle=-25, tickfont=dict(size=9)),
    )

    # 5. Trend grouped bar
    trend_fig = go.Figure()
    trend_fig.add_trace(
        go.Bar(
            name="Last 90 days",
            x=companies,
            y=[trends[c]["recent_90d"] for c in companies],
            marker_color=colors,
            opacity=1.0,
        )
    )
    trend_fig.add_trace(
        go.Bar(
            name="Prior 90 days",
            x=companies,
            y=[trends[c]["prior_90d"] for c in companies],
            marker_color=colors,
            opacity=0.4,
        )
    )
    trend_fig.update_layout(
        **layout_base,
        barmode="group",
        yaxis=axis_style(title="Posts"),
        xaxis=axis_style(),
    )

    return {
        "volume": json.loads(volume.to_json()),
        "monthly": json.loads(monthly_fig.to_json()),
        "heatmap": json.loads(heatmap.to_json()),
        "topics": json.loads(topics_fig.to_json()),
        "trend": json.loads(trend_fig.to_json()),
    }


@app.route("/")
def index():
    result = analyze.run()
    charts = build_charts(result)
    totals = {c: sum(result["topic_dist"][c].values()) for c in result["companies"]}

    from jinja2 import Environment
    env = Environment(autoescape=True)
    env.filters["markdown_bold"] = markdown_bold
    tmpl = env.from_string(HTML_TEMPLATE)

    return tmpl.render(
        companies=result["companies"],
        meta=result["meta"],
        totals=totals,
        trends=result["trends"],
        gaps=result["gaps"],
        insights=result["insights"],
        colors=COMPANY_COLORS,
        text_colors=COMPANY_TEXT_COLORS,
        charts_json=json.dumps(charts),
    )


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    """Re-run ingestion in the background and reload."""
    try:
        subprocess.run(
            [sys.executable, "ingest.py"],
            cwd=Path(__file__).parent,
            timeout=120,
            check=True,
        )
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, port=port)
