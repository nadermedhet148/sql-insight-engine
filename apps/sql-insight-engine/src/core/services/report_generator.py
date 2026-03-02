"""
Report Generator Service

Converts SQL query results into a standalone interactive HTML report
with Chart.js visualizations and a client-side PDF download button.
"""

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from jinja2 import Template

_FALLBACK_CHART_CONFIG: Dict[str, Any] = {
    "chart_type": "table_only",
    "title": "Query Results",
    "x_field": None,
    "y_fields": [],
    "description": "",
}

_CHART_COLORS = [
    "#4361ee", "#f72585", "#4cc9f0", "#90be6d",
    "#f3722c", "#7209b7", "#4895ef", "#43aa8b",
]

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SQL Insight Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"></script>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f0f4f8; color: #1a202c; }
  #report-content { max-width: 1100px; margin: 0 auto; padding: 24px; }

  header { background: linear-gradient(135deg, #4361ee 0%, #7209b7 100%); color: #fff; border-radius: 12px; padding: 28px 32px; margin-bottom: 24px; }
  .header-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
  header h1 { font-size: 1.75rem; font-weight: 700; margin-bottom: 8px; }
  .question-label { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.08em; opacity: 0.75; margin-bottom: 4px; }
  .question-text { font-size: 1.05rem; opacity: 0.95; line-height: 1.4; }
  .report-date { font-size: 0.8rem; opacity: 0.7; margin-top: 8px; }

  #download-btn {
    flex-shrink: 0; background: rgba(255,255,255,0.2); color: #fff;
    border: 2px solid rgba(255,255,255,0.5); border-radius: 8px;
    padding: 10px 18px; font-size: 0.9rem; font-weight: 600;
    cursor: pointer; white-space: nowrap; transition: background 0.2s;
  }
  #download-btn:hover { background: rgba(255,255,255,0.35); }

  section { background: #fff; border-radius: 12px; padding: 24px 28px; margin-bottom: 24px; box-shadow: 0 1px 4px rgba(0,0,0,0.07); }
  section h2 { font-size: 1.1rem; font-weight: 600; color: #4361ee; margin-bottom: 14px; padding-bottom: 8px; border-bottom: 2px solid #e8ecff; }

  #summary-content { font-size: 0.97rem; line-height: 1.7; color: #2d3748; white-space: pre-wrap; }

  #chart-description { font-size: 0.88rem; color: #718096; margin-bottom: 16px; }
  .chart-container { position: relative; height: 340px; }

  .table-wrapper { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
  thead th { background: #4361ee; color: #fff; padding: 10px 14px; text-align: left; font-weight: 600; white-space: nowrap; }
  tbody tr:nth-child(even) { background: #f7f9ff; }
  tbody td { padding: 9px 14px; border-bottom: 1px solid #e8ecff; color: #2d3748; }
  tbody tr:hover { background: #eef1ff; }

  @media print {
    body { background: #fff; }
    #download-btn { display: none !important; }
    section { box-shadow: none; border: 1px solid #e2e8f0; }
  }
</style>
</head>
<body>
<div id="report-content">
  <header>
    <div class="header-top">
      <div>
        <h1>SQL Insight Report</h1>
        <div class="question-label">Question</div>
        <div class="question-text" id="header-question"></div>
        <div class="report-date">Generated: {{ report_date }}</div>
      </div>
      <button id="download-btn" onclick="downloadPDF()">&#11015; Download PDF</button>
    </div>
  </header>

  <section>
    <h2>Executive Summary</h2>
    <div id="summary-content"></div>
  </section>

  <section id="chart-section" style="display:none">
    <h2 id="chart-title"></h2>
    <div id="chart-description"></div>
    <div class="chart-container">
      <canvas id="main-chart"></canvas>
    </div>
  </section>

  <section>
    <h2>Data</h2>
    <div class="table-wrapper">
      <table>
        <thead id="table-head"></thead>
        <tbody id="table-body"></tbody>
      </table>
    </div>
  </section>
</div>

<script>
var DATA = {
  question:    {{ question_json }},
  summary:     {{ summary_json }},
  columns:     {{ columns_json }},
  rows:        {{ rows_json }},
  chartType:   {{ chart_type_json }},
  chartTitle:  {{ chart_title_json }},
  chartData:   {{ chart_data_json }},
  showChart:   {{ show_chart_json }},
  chartDesc:   {{ chart_description_json }}
};

// Header question
document.getElementById('header-question').textContent = DATA.question;

// Executive summary
document.getElementById('summary-content').textContent = DATA.summary;

// Table header
var thead = document.getElementById('table-head');
if (DATA.columns.length) {
  var tr = document.createElement('tr');
  DATA.columns.forEach(function(col) {
    var th = document.createElement('th');
    th.textContent = col;
    tr.appendChild(th);
  });
  thead.appendChild(tr);
}

// Table body
var tbody = document.getElementById('table-body');
DATA.rows.forEach(function(row) {
  var tr = document.createElement('tr');
  DATA.columns.forEach(function(col) {
    var td = document.createElement('td');
    var val = row[col];
    td.textContent = (val !== null && val !== undefined) ? String(val) : '';
    tr.appendChild(td);
  });
  tbody.appendChild(tr);
});

// Chart
if (DATA.showChart && DATA.chartData) {
  document.getElementById('chart-section').style.display = 'block';
  document.getElementById('chart-title').textContent = DATA.chartTitle;
  document.getElementById('chart-description').textContent = DATA.chartDesc;
  var ctx = document.getElementById('main-chart').getContext('2d');
  new Chart(ctx, {
    type: DATA.chartType,
    data: DATA.chartData,
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: 'top' } },
      scales: DATA.chartType === 'pie' ? {} : { y: { beginAtZero: true } }
    }
  });
}

// PDF download
function downloadPDF() {
  var btn = document.getElementById('download-btn');
  btn.disabled = true;
  btn.textContent = 'Generating…';
  var opt = {
    margin: [0.4, 0.4],
    filename: 'sql-insight-report.pdf',
    image: { type: 'jpeg', quality: 0.97 },
    html2canvas: { scale: 2, useCORS: true },
    jsPDF: { unit: 'in', format: 'a4', orientation: 'portrait' }
  };
  html2pdf().set(opt).from(document.getElementById('report-content')).save()
    .then(function() { btn.disabled = false; btn.textContent = '\\u2B07 Download PDF'; });
}
</script>
</body>
</html>
"""


def get_chart_config(question: str, raw_results: str, gemini_client) -> Dict[str, Any]:
    """Ask Gemini to analyze the data shape and return a chart configuration."""
    try:
        data = json.loads(raw_results)
        if not isinstance(data, list) or len(data) == 0:
            return _FALLBACK_CHART_CONFIG

        columns = list(data[0].keys())
        sample = data[:3]

        prompt = (
            f"You are a data visualization expert. Analyze this dataset and pick the best chart.\n\n"
            f"Question: \"{question}\"\n"
            f"Columns: {json.dumps(columns)}\n"
            f"Sample rows: {json.dumps(sample)}\n\n"
            "Return ONLY a valid JSON object with exactly these fields:\n"
            "{\n"
            '  "chart_type": "bar" | "line" | "pie" | "scatter" | "table_only",\n'
            '  "title": "descriptive chart title",\n'
            '  "x_field": "column name for X axis (or null)",\n'
            '  "y_fields": ["column name(s) for Y axis — must be numeric"],\n'
            '  "description": "one sentence describing what the chart shows"\n'
            "}\n\n"
            "Rules:\n"
            "- Use 'bar' for comparisons across categories.\n"
            "- Use 'line' for trends over time or ordered sequences.\n"
            "- Use 'pie' for proportions (max 10 distinct slices).\n"
            "- Use 'scatter' for correlations between two numeric fields.\n"
            "- Use 'table_only' if there are no numeric columns or only 1 row.\n"
            "- x_field and y_fields MUST be exact column names from the dataset.\n"
            "- y_fields must contain only numeric columns.\n"
            "Return ONLY the JSON object, no markdown, no explanation."
        )

        response = gemini_client.generate_content(prompt)
        if not response:
            return _FALLBACK_CHART_CONFIG

        text = response.text if hasattr(response, "text") else str(response)
        # Strip markdown fences if Gemini wraps in ```json ... ```
        text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()

        config = json.loads(text)
        if "chart_type" not in config:
            return _FALLBACK_CHART_CONFIG
        return config

    except Exception as exc:
        print(f"[ReportGenerator] Chart config generation failed: {exc}")
        return _FALLBACK_CHART_CONFIG


def build_html_report(
    question: str,
    executive_summary: str,
    raw_results: str,
    chart_config: Dict[str, Any],
) -> str:
    """Render a standalone HTML report with Chart.js chart and data table."""
    try:
        data = json.loads(raw_results)
    except Exception:
        data = []
    if not isinstance(data, list):
        data = []

    columns: List[str] = list(data[0].keys()) if data else []
    chart_type: str = chart_config.get("chart_type", "table_only")
    chart_title: str = chart_config.get("title", "Query Results")
    x_field: Optional[str] = chart_config.get("x_field")
    y_fields: List[str] = chart_config.get("y_fields") or []

    chart_data = None
    show_chart = False

    if chart_type != "table_only" and x_field and y_fields and data:
        labels = [str(row.get(x_field, "")) for row in data]

        def _safe_float(val: Any) -> float:
            try:
                return float(val) if val is not None else 0.0
            except (TypeError, ValueError):
                return 0.0

        if chart_type == "pie":
            y_field = y_fields[0]
            values = [_safe_float(row.get(y_field)) for row in data]
            chart_data = {
                "labels": labels,
                "datasets": [{
                    "label": y_field,
                    "data": values,
                    "backgroundColor": (_CHART_COLORS * ((len(labels) // len(_CHART_COLORS)) + 1))[:len(labels)],
                }],
            }
        else:
            datasets = []
            for i, y_field in enumerate(y_fields):
                color = _CHART_COLORS[i % len(_CHART_COLORS)]
                datasets.append({
                    "label": y_field,
                    "data": [_safe_float(row.get(y_field)) for row in data],
                    "backgroundColor": color + "cc",
                    "borderColor": color,
                    "borderWidth": 2,
                    "fill": False,
                    "tension": 0.4,
                })
            chart_data = {"labels": labels, "datasets": datasets}

        show_chart = True

    chartjs_type_map = {"bar": "bar", "line": "line", "pie": "pie", "scatter": "scatter"}
    chartjs_type = chartjs_type_map.get(chart_type, "bar")

    template = Template(_HTML_TEMPLATE)
    return template.render(
        report_date=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        question_json=json.dumps(question),
        summary_json=json.dumps(executive_summary),
        columns_json=json.dumps(columns),
        rows_json=json.dumps(data),
        chart_type_json=json.dumps(chartjs_type),
        chart_title_json=json.dumps(chart_title),
        chart_data_json=json.dumps(chart_data),
        show_chart_json="true" if show_chart else "false",
        chart_description_json=json.dumps(chart_config.get("description", "")),
    )
