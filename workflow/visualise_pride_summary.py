#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import json
import plotly.graph_objects as go
from plotly.subplots import make_subplots

#python visualise_pride_summary.py --tsv pride_yearly_ms_filetype_counts_2000_2025.tsv --out pride_yearly_ms_filetype_counts_2000_2025.html

MS_TYPES = ["raw", "d", "baf", "tdf", "tdf_bin", "wiff", "wiff2", "mzml", "mzxml", "mgf"]


def build_summary_html() -> str:
    items = [
        ("raw", "Thermo RAW; vendor raw data"),
        ("d", 'Bruker “.d” dataset directory; vendor raw data container'),
        ("baf", "Bruker BAF; vendor raw data"),
        ("tdf", "Bruker timsTOF raw data files"),
        ("tdf_bin", "Bruker timsTOF raw data files"),
        ("wiff", "SCIEX vendor raw data"),
        ("wiff2", "SCIEX vendor raw data"),
        ("mzml", "open raw spectra format"),
        ("mzxml", "open raw spectra format"),
        ("mgf", "peak list / MS2 spectra export"),
    ]
    lis = "\n".join([f"<li><b>{k}</b> : {v}</li>" for k, v in items])
    return f"""
    <h2>Summary</h2>
    <p><b>MS data (including peak list): </b></p>
    <ul>{lis}</ul>
    """


def build_table_html(df: pd.DataFrame) -> str:
    dfx = df[["year", *MS_TYPES]].copy()
    dfx = dfx.sort_values("year").reset_index(drop=True)

    cols = [{"key": "year", "label": "year"}] + [{"key": c, "label": c} for c in MS_TYPES]
    rows = dfx.to_dict(orient="records")
    return f"""
    <h3>MS data table</h3>
    <div class="table-wrap">
      <table id="ms-table"></table>
    </div>
    <script>
      const MS_COLS = {json.dumps(cols)};
      const MS_ROWS = {json.dumps(rows)};
      function fmt(n){{ return (typeof n === "number") ? n.toLocaleString() : n; }}

      const tbl = document.getElementById("ms-table");
      const thead = document.createElement("thead");
      const trh = document.createElement("tr");
      MS_COLS.forEach(c => {{
        const th = document.createElement("th");
        th.textContent = c.label;
        th.dataset.key = c.key;
        trh.appendChild(th);
      }});
      thead.appendChild(trh);
      tbl.appendChild(thead);

      const tbody = document.createElement("tbody");
      MS_ROWS.forEach(r => {{
        const tr = document.createElement("tr");
        MS_COLS.forEach(c => {{
          const td = document.createElement("td");
          td.textContent = fmt(r[c.key]);
          td.dataset.key = c.key;
          tr.appendChild(td);
        }});
        tbody.appendChild(tr);
      }});
      tbl.appendChild(tbody);

      const state = {{key: "year", asc: true}};
      function sortRows(key) {{
        const asc = (state.key === key) ? !state.asc : true;
        state.key = key; state.asc = asc;
        MS_ROWS.sort((a,b) => {{
          const av = a[key], bv = b[key];
          if (typeof av === "number" && typeof bv === "number") return asc ? (av-bv) : (bv-av);
          return asc ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av));
        }});
        while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
        MS_ROWS.forEach(r => {{
          const tr = document.createElement("tr");
          MS_COLS.forEach(c => {{
            const td = document.createElement("td");
            td.textContent = fmt(r[c.key]);
            tr.appendChild(td);
          }});
          tbody.appendChild(tr);
        }});
        document.querySelectorAll("#ms-table th").forEach(th => {{
          th.classList.toggle("sorted", th.dataset.key === state.key);
          th.classList.toggle("desc", th.dataset.key === state.key && !state.asc);
        }});
      }}

      document.querySelectorAll("#ms-table th").forEach(th => {{
        th.addEventListener("click", () => sortRows(th.dataset.key));
      }});
      sortRows("year");
    </script>
    """


def heatmap_figure(df: pd.DataFrame, years: np.ndarray, filetypes: list[str]) -> go.Figure:
    z = df[filetypes].to_numpy().T
    z_log = np.log10(z + 1.0)
    fig = go.Figure(
        data=go.Heatmap(
            x=years,
            y=filetypes,
            z=z_log,
            colorbar=dict(title="log10(count+1)"),
            hovertemplate="year=%{x}<br>type=%{y}<br>count=%{customdata}<extra></extra>",
            customdata=z,
        )
    )
    fig.update_layout(title="Heatmap: filetype counts by year", margin=dict(l=50, r=30, t=60, b=40))
    fig.update_yaxes(autorange="reversed")
    return fig


def stacked_area_figure(df: pd.DataFrame, years: np.ndarray, filetypes: list[str]) -> go.Figure:
    fig = go.Figure()
    for ft in filetypes:
        fig.add_trace(go.Scatter(x=years, y=df[ft], mode="lines", stackgroup="one", name=ft))
    fig.update_layout(title="Composition by year", margin=dict(l=50, r=30, t=60, b=40))
    fig.update_yaxes(title="count")
    fig.update_xaxes(title="year")
    return fig


def small_multiples(df: pd.DataFrame, years: np.ndarray) -> go.Figure:
    total_ms = df[MS_TYPES].sum(axis=1)
    raw = df["raw"]
    bruker = df[["d", "baf", "tdf", "tdf_bin"]].sum(axis=1)
    mz_open = df[["mzml", "mzxml"]].sum(axis=1)
    mgf = df["mgf"]
    sciex = df[["wiff", "wiff2"]].sum(axis=1)

    fig = make_subplots(
        rows=2,
        cols=3,
        subplot_titles=(
            "Total MS submissions per year",
            "Total RAW files per year",
            "Total Bruker files per year (d+baf+tdf+tdf_bin)",
            "Total mzML+mzXML per year",
            "Total MGF per year",
            "Total WIFF+WIFF2 per year",
        ),
        horizontal_spacing=0.08,
        vertical_spacing=0.16,
    )

    series = [total_ms, raw, bruker, mz_open, mgf, sciex]
    positions = [(1, 1), (1, 2), (1, 3), (2, 1), (2, 2), (2, 3)]

    for s, (r, c) in zip(series, positions):
        fig.add_trace(go.Scatter(x=years, y=s, mode="lines+markers", name=""), row=r, col=c)

    fig.update_layout(title="", showlegend=False, margin=dict(l=50, r=30, t=80, b=40), height=700)
    for r in (1, 2):
        for c in (1, 2, 3):
            fig.update_xaxes(title="year", row=r, col=c)
            fig.update_yaxes(title="count", row=r, col=c)
    return fig


def histogram_figure(df: pd.DataFrame, years: np.ndarray) -> go.Figure:
    agg = pd.DataFrame(
        {
            "raw": df["raw"],
            "bruker": df[["d", "baf", "tdf", "tdf_bin"]].sum(axis=1),
            #"mzml+mzxml": df[["mzml", "mzxml"]].sum(axis=1),
            #"mgf": df["mgf"],
            "wiff+wiff2": df[["wiff", "wiff2"]].sum(axis=1),
        }
    )

    fig = go.Figure()
    for col in agg.columns:
        fig.add_trace(go.Bar(x=years, y=agg[col], name=col))

    fig.update_layout(
        title="Yearly counts of different MS filetypes",
        barmode="group",
        margin=dict(l=50, r=30, t=60, b=40),
        height=420,
    )
    fig.update_xaxes(title="year")
    fig.update_yaxes(title="count")
    return fig


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tsv", required=True)
    ap.add_argument("--out", default="pride_ms_filetypes_report.html")
    ap.add_argument("--title", default="PRIDE MS filetypes by year (2000–2025)")
    args = ap.parse_args()

    df = pd.read_csv(Path(args.tsv), sep="\t")
    if "year" not in df.columns:
        raise SystemExit("TSV must have a 'year' column")

    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["year"]).copy()
    df["year"] = df["year"].astype(int)
    df = df.sort_values("year").reset_index(drop=True)

    for c in MS_TYPES:
        if c not in df.columns:
            df[c] = 0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)

    years = df["year"].to_numpy()

    summary_html = build_summary_html()
    table_html = build_table_html(df)
    hist = histogram_figure(df, years)
    heat = heatmap_figure(df, years, MS_TYPES)
    area = stacked_area_figure(df, years, MS_TYPES)
    small = small_multiples(df, years)

    plotly_cdn = '<script src="https://cdn.plot.ly/plotly-2.30.0.min.js"></script>'

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{args.title}</title>
{plotly_cdn}
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:24px;line-height:1.35}}
h1{{margin:0 0 12px 0}}
.card{{border:1px solid #ddd;border-radius:10px;padding:16px;margin:16px 0}}
.table-wrap{{overflow:auto;border-radius:10px;border:1px solid #eee}}
table{{border-collapse:separate;border-spacing:0;width:max-content;min-width:100%}}
th,td{{padding:10px 12px;border-bottom:1px solid #eee;white-space:nowrap}}
th{{position:sticky;top:0;background:#fafafa;cursor:pointer;border-bottom:1px solid #ddd;font-weight:600}}
tr:nth-child(even) td{{background:#fcfcfc}}
th.sorted::after{{content:" ▲";font-size:12px}}
th.sorted.desc::after{{content:" ▼";font-size:12px}}
td{{text-align:right}}
td[data-key="year"]{{text-align:left;font-variant-numeric:tabular-nums}}
</style>
</head>
<body>
<h1>{args.title}</h1>

<div class="card">
{summary_html}
{table_html}
</div>

<div class="card">
<div id="hist"></div>
</div>

<div class="card">
<div id="heatmap"></div>
</div>

<div class="card">
<div id="stacked"></div>
</div>

<div class="card">
<div id="multiples"></div>
</div>

<script>
const hist = {hist.to_json()};
const heat = {heat.to_json()};
const area = {area.to_json()};
const small = {small.to_json()};
Plotly.newPlot("hist", hist.data, hist.layout, {{responsive:true}});
Plotly.newPlot("heatmap", heat.data, heat.layout, {{responsive:true}});
Plotly.newPlot("stacked", area.data, area.layout, {{responsive:true}});
Plotly.newPlot("multiples", small.data, small.layout, {{responsive:true}});
</script>

</body>
</html>
"""

    out_path = Path(args.out)
    out_path.write_text(html, encoding="utf-8")
    print(str(out_path.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
