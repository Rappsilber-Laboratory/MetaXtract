from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import re

import numpy as np
import plotly.graph_objects as go
import plotly.io as pio


_NUM_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?")

def to_float(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if not s:
        return None
    m = _NUM_RE.search(s)
    if not m:
        return None
    token = m.group(0).replace(",", ".")
    try:
        return float(token)
    except Exception:
        return None

def to_int(x):
    v = to_float(x)
    return int(v) if v is not None else None

def _farr(xs) -> np.ndarray:
    if xs is None:
        return np.asarray([], dtype=float)
    out = []
    for v in xs:
        fv = to_float(v)
        out.append(fv if fv is not None else 0.0)
    return np.asarray(out, dtype=float)

def _iarr(xs) -> np.ndarray:
    if xs is None:
        return np.asarray([], dtype=int)
    out = []
    for v in xs:
        iv = to_int(v)
        out.append(iv if iv is not None else 0)
    return np.asarray(out, dtype=int)

def _safe_log10(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        y = np.where(x > 0, np.log10(x), 0.0)
    return y

def _as_float_list(vals):
    if vals is None:
        return []
    out = []
    for v in vals:
        try:
            if v is None:
                continue
            fv = float(v)
            if np.isfinite(fv):
                out.append(fv)
        except Exception:
            continue
    return out

def _log10p1(vals):
    arr = np.asarray(vals, dtype=float)
    arr = np.where(arr < 0, 0, arr)
    return np.log10(arr + 1.0)


def _selected_ion_intensity_note(sources) -> str:
    sources = list(sources or [])
    if not sources:
        return ""
    trailer_count = sources.count("trailer")
    computed_count = sources.count("computed")
    missing_count = sources.count("missing")
    if computed_count == 0 and missing_count == 0:
        return ""
    parts = [
        f"{trailer_count} scans used RAW trailer metadata",
        f"{computed_count} scans used computed precursor-intensity fallback",
    ]
    if missing_count:
        parts.append(f"{missing_count} scans had no usable value")
    return "Selected Ion Intensity source: " + "; ".join(parts) + "."


def _add_bottom_note(fig: go.Figure, note: str) -> go.Figure:
    if not note:
        return fig
    fig.add_annotation(
        text=note,
        xref="paper",
        yref="paper",
        x=0,
        y=-0.22,
        showarrow=False,
        align="left",
        xanchor="left",
        yanchor="top",
        font=dict(size=12, color="#4b5563"),
    )
    fig.update_layout(margin=dict(b=100))
    return fig


def make_boxplot_figure(title: str, y_label: str, sample_to_values: dict, log10p1: bool = False) -> go.Figure:
    fig = go.Figure()
    for sample, values in (sample_to_values or {}).items():
        y = _as_float_list(values)
        if not y:
            continue
        if log10p1:
            y = _log10p1(y)
        fig.add_trace(go.Box(y=y, name=str(sample), boxpoints=False))
    fig.update_layout(title=title, yaxis_title=y_label, xaxis_title="Sample")
    return fig

PLOTLY_CONFIG = {"displaylogo": False, "responsive": True}


@dataclass
class _Fig:
    title: str
    fig: go.Figure


def _write_single_html(out_path: Path, title: str, figs: List[_Fig]) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    html_parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>{title}</title>",
        "<style>",
        "body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;margin:0;background:#0f1115;color:#e9eef5}",
        ".top{position:sticky;top:0;z-index:10;background:#0f1115;border-bottom:1px solid #2a3242;padding:10px 14px;display:flex;gap:10px;align-items:center}",
        "select{background:#161a22;color:#e9eef5;border:1px solid #2a3242;border-radius:10px;padding:8px 10px;font-weight:600}",
        ".wrap{padding:14px;max-width:1400px;margin:0 auto}",
        ".card{background:#0b0d12;border:1px solid #2a3242;border-radius:14px;margin:14px 0;padding:10px}",
        ".h{font-weight:800;font-size:16px;margin:6px 6px 10px 6px}",
        "</style>",
        "</head><body>",
        "<div class='top'>",
        f"<div style='font-weight:900'>{title}</div>",
        "<select id='picker'></select>",
        "</div>",
        "<div class='wrap' id='container'></div>",
        "<script src='https://cdn.plot.ly/plotly-2.30.0.min.js'></script>",
        "<script>",
        "const items = [];",
    ]

    for i, f in enumerate(figs):
        js = pio.to_json(f.fig, validate=False)
        html_parts.append(f"items.push({{title:{f.title!r}, spec:{js}}});")

    html_parts += [
        "const picker = document.getElementById('picker');",
        "const container = document.getElementById('container');",
        "function render(ix){",
        "  container.innerHTML='';",
        "  const it = items[ix];",
        "  const card = document.createElement('div'); card.className='card';",
        "  const h = document.createElement('div'); h.className='h'; h.textContent = it.title;",
        "  const d = document.createElement('div'); d.id = 'plot'; d.style.height='720px';",
        "  card.appendChild(h); card.appendChild(d); container.appendChild(card);",
        "  const obj = it.spec;",
        "  Plotly.newPlot(d, obj.data, obj.layout, Object.assign({}, obj.config||{}, {displaylogo:false, responsive:true}));",
        "}",
        "items.forEach((it, i)=>{ const o=document.createElement('option'); o.value=i; o.textContent=it.title; picker.appendChild(o); });",
        "picker.addEventListener('change', ()=>render(parseInt(picker.value,10)));",
        "if(items.length){ render(0); }",
        "</script>",
        "</body></html>",
    ]

    out_path.write_text("\n".join(html_parts), encoding="utf-8")
    return out_path


class PlotlyMS1Visualizer:
    def __init__(self, single_file_name: str, output_dir: str):
        self.single_file_name = single_file_name
        self.output_dir = Path(output_dir)
        self.ms1_scans: List[int] = []
        self.ms1_data: Dict[str, List] = {
            "Scan Start Time (min)": [],
            "Elapsed Scan Time (sec)": [],
            "Total Ion Current": [],
            "Total Number of Peaks": [],
            "Base Peak Intensity": [],
            "Base Peak m/z": [],
            "Ion Injection Time (ms)": [],
        }

    def _figs(self) -> List[_Fig]:
        figs: List[_Fig] = []
        rt_s = _farr(self.ms1_data["Scan Start Time (min)"])
        if rt_s.size == 0:
            return figs

        rt_min = rt_s #/ 60.0
        tic = _farr(self.ms1_data["Total Ion Current"])
        bpi = _farr(self.ms1_data["Base Peak Intensity"])
        bpm = _farr(self.ms1_data["Base Peak m/z"])
        iit_ms = _farr(self.ms1_data["Ion Injection Time (ms)"])
        tnp = _farr(self.ms1_data["Total Number of Peaks"])

        if tic.size:
            figs.append(_Fig(
                "TIC vs RT (min)",
                go.Figure(
                    data=[go.Scatter(x=rt_min, y=tic, mode="lines", name=self.single_file_name)],
                    layout=go.Layout(title="MS1 TIC vs RT (min)", xaxis_title="RT (min)", yaxis_title="TIC"),
                )
            ))

        if bpi.size:
            figs.append(_Fig(
                "BPI vs RT (min)",
                go.Figure(
                    data=[go.Scatter(x=rt_min, y=bpi, mode="lines", name=self.single_file_name)],
                    layout=go.Layout(title="MS1 BPI vs RT (min)", xaxis_title="RT (min)", yaxis_title="BPI"),
                )
            ))

        if bpm.size:
            figs.append(_Fig(
                "Base Peak m/z vs RT (min)",
                go.Figure(
                    data=[go.Scatter(x=rt_min, y=bpm, mode="lines", name=self.single_file_name)],
                    layout=go.Layout(title="MS1 Base Peak m/z vs RT (min)", xaxis_title="RT (min)", yaxis_title="m/z"),
                )
            ))
            figs.append(_Fig(
                "log10(Base Peak m/z + 1) scatter vs RT (min)",
                go.Figure(
                    data=[go.Scatter(x=rt_min, y=np.log10(bpm + 1.0), mode="markers", marker=dict(size=4, opacity=0.6), name=self.single_file_name)],
                    layout=go.Layout(title="MS1 log10(Base Peak m/z + 1) vs RT (min)", xaxis_title="RT (min)", yaxis_title="log10(m/z+1)"),
                )
            ))

        if iit_ms.size:
            iit_s = iit_ms / 1000.0
            figs.append(_Fig(
                "Ion Injection Time (s) vs Scan Start Time (min)",
                go.Figure(
                    data=[go.Scatter(x=rt_s, y=iit_s, mode="lines", name=self.single_file_name)],
                    layout=go.Layout(title="MS1 IIT (s) vs Scan Start Time (min)", xaxis_title="Scan Start Time (min)", yaxis_title="IIT (s)"),
                )
            ))

        if iit_ms.size and bpi.size:
            iit_s = iit_ms / 1000.0
            figs.append(_Fig(
                "2D hist: log10(BPI) vs IIT (s)",
                go.Figure(
                    data=[go.Histogram2d(x=iit_s, y=_safe_log10(bpi), nbinsx=60, nbinsy=60)],
                    layout=go.Layout(title="MS1 log10(BPI) vs IIT (s)", xaxis_title="IIT (s)", yaxis_title="log10(BPI)"),
                )
            ))

        if tnp.size:
            figs.append(_Fig(
                "Total Number of Peaks vs RT (min)",
                go.Figure(
                    data=[go.Scatter(x=rt_min, y=tnp, mode="lines", name=self.single_file_name)],
                    layout=go.Layout(title="MS1 Total Number of Peaks vs RT (min)", xaxis_title="RT (min)", yaxis_title="Total Peaks"),
                )
            ))

        return figs

    def write_html_report(self) -> Path:
        out = self.output_dir / f"{self.single_file_name}_MS1.html"
        return _write_single_html(out, f"MS1 Vis Report: {self.single_file_name}", self._figs())

    def export_images(self, fmt: str = "png") -> List[Path]:
        fmt = fmt.lower().strip()
        if fmt not in {"png", "svg"}:
            raise ValueError("fmt must be 'png' or 'svg'")
        outs: List[Path] = []
        for i, f in enumerate(self._figs()):
            out = self.output_dir / f"{self.single_file_name}_MS1_{i:02d}.{fmt}"
            f.fig.write_image(str(out))
            outs.append(out)
        return outs

    def tic_trace(self) -> Tuple[np.ndarray, np.ndarray]:
        rt_s = _farr(self.ms1_data["Scan Start Time (min)"])
        tic = _farr(self.ms1_data["Total Ion Current"])
        if rt_s.size == 0 or tic.size == 0:
            return np.asarray([], dtype=float), np.asarray([], dtype=float)
        return rt_s, tic #/ 60.0, tic
    
    def bpi_trace(self):
        rt_s = _farr(self.ms1_data["Scan Start Time (min)"])
        bpi = _farr(self.ms1_data["Base Peak Intensity"])
        if rt_s.size == 0 or bpi.size == 0:
            return np.asarray([], dtype=float), np.asarray([], dtype=float)
        return rt_s, bpi #/ 60.0, bpi

    def tnp_trace(self):
        rt_s = _farr(self.ms1_data["Scan Start Time (min)"])
        tnp = _farr(self.ms1_data["Total Number of Peaks"])
        if rt_s.size == 0 or tnp.size == 0:
            return np.asarray([], dtype=float), np.asarray([], dtype=float)
        return rt_s, tnp # / 60.0, tnp



class PlotlyMS2Visualizer:
    def __init__(self, single_file_name: str, output_dir: str):
        self.single_file_name = single_file_name
        self.output_dir = Path(output_dir)
        self.ms2_scans: List[int] = []
        self.ms2_data: Dict[str, List] = {
            "Scan Start Time (min)": [],
            "Elapsed Scan Time (sec)": [],
            "Total Ion Current": [],
            "Total Number of Peaks": [],
            "Selected Ion Intensity": [],
            "Selected Ion Intensity Source": [],
            "Charge State": [],
            "Ion Injection Time (ms)": [],
            "Base Peak Intensity": [],
        }

    def _figs(self) -> List[_Fig]:
        figs: List[_Fig] = []
        rt_s = _farr(self.ms2_data["Scan Start Time (min)"])
        if rt_s.size == 0:
            return figs

        rt_min = rt_s #/ 60.0
        tic = _farr(self.ms2_data["Total Ion Current"])
        tnp = _farr(self.ms2_data["Total Number of Peaks"])
        prec = _farr(self.ms2_data["Selected Ion Intensity"])
        prec_note = _selected_ion_intensity_note(
            self.ms2_data.get("Selected Ion Intensity Source", [])
        )
        cs = _iarr(self.ms2_data["Charge State"])
        iit_ms = _farr(self.ms2_data["Ion Injection Time (ms)"])
        est = _farr(self.ms2_data["Elapsed Scan Time (sec)"])

        if tic.size:
            figs.append(_Fig(
                "TIC vs RT (min)",
                go.Figure(
                    data=[go.Scatter(x=rt_min, y=tic, mode="lines", name=self.single_file_name)],
                    layout=go.Layout(title="MS2 TIC vs RT (min)", xaxis_title="RT (min)", yaxis_title="TIC"),
                )
            ))

        if tnp.size:
            figs.append(_Fig(
                "Total Number of Peaks vs RT (min)",
                go.Figure(
                    data=[go.Scatter(x=rt_min, y=tnp, mode="lines", name=self.single_file_name)],
                    layout=go.Layout(title="MS2 Total Number of Peaks vs RT (min)", xaxis_title="RT (min)", yaxis_title="Total Peaks"),
                )
            ))

        if prec.size:
            figs.append(_Fig(
                "Selected Ion Intensity vs RT (min)",
                _add_bottom_note(go.Figure(
                    data=[go.Scatter(x=rt_min, y=prec, mode="lines", name=self.single_file_name)],
                    layout=go.Layout(title="MS2 Selected Ion Intensity vs RT (min)", xaxis_title="RT (min)", yaxis_title="Selected Ion Intensity"),
                ), prec_note)
            ))

        if iit_ms.size and prec.size:
            iit_s = iit_ms / 1000.0
            figs.append(_Fig(
                "2D hist: log10(Selected Ion Intensity) vs IIT (s)",
                _add_bottom_note(go.Figure(
                    data=[go.Histogram2d(x=iit_s, y=_safe_log10(prec), nbinsx=60, nbinsy=60)],
                    layout=go.Layout(title="MS2 log10(Selected Ion Intensity) vs IIT (s)", xaxis_title="IIT (s)", yaxis_title="log10(Selected Ion Intensity)"),
                ), prec_note)
            ))

        if tnp.size and prec.size:
            figs.append(_Fig(
                "2D hist: log10(Selected Ion Intensity) vs Total Peaks",
                _add_bottom_note(go.Figure(
                    data=[go.Histogram2d(x=tnp, y=_safe_log10(prec), nbinsx=60, nbinsy=60)],
                    layout=go.Layout(title="MS2 log10(Selected Ion Intensity) vs Total Peaks", xaxis_title="Total Peaks", yaxis_title="log10(Selected Ion Intensity)"),
                ), prec_note)
            ))

        if cs.size:
            vals, counts = np.unique(cs, return_counts=True)
            figs.append(_Fig(
                "Charge State Distribution",
                go.Figure(
                    data=[go.Bar(x=vals.tolist(), y=counts.tolist(), name=self.single_file_name)],
                    layout=go.Layout(title="MS2 Charge State Distribution", xaxis_title="Charge State", yaxis_title="Count"),
                )
            ))

        if iit_ms.size:
            iit_s = iit_ms / 1000.0
            figs.append(_Fig(
                "Ion Injection Time (s) vs RT (s)",
                go.Figure(
                    data=[go.Scatter(x=rt_s, y=iit_s, mode="lines", name=self.single_file_name)],
                    layout=go.Layout(title="MS2 IIT (s) vs RT (s)", xaxis_title="RT (s)", yaxis_title="IIT (s)"),
                )
            ))

        if est.size:
            figs.append(_Fig(
                "Elapsed Scan Time (s) vs RT (s)",
                go.Figure(
                    data=[go.Scatter(x=rt_s, y=est, mode="lines", name=self.single_file_name)],
                    layout=go.Layout(title="MS2 Elapsed Scan Time (s) vs RT (s)", xaxis_title="RT (s)", yaxis_title="Elapsed Scan Time (s)"),
                )
            ))

        return figs

    def write_html_report(self) -> Path:
        out = self.output_dir / f"{self.single_file_name}_MS2.html"
        return _write_single_html(out, f"MS2 Vis Report: {self.single_file_name}", self._figs())

    def export_images(self, fmt: str = "png") -> List[Path]:
        fmt = fmt.lower().strip()
        if fmt not in {"png", "svg"}:
            raise ValueError("fmt must be 'png' or 'svg'")
        outs: List[Path] = []
        for i, f in enumerate(self._figs()):
            out = self.output_dir / f"{self.single_file_name}_MS2_{i:02d}.{fmt}"
            f.fig.write_image(str(out))
            outs.append(out)
        return outs

    def tic_trace(self) -> Tuple[np.ndarray, np.ndarray]:
        rt_s = _farr(self.ms2_data["Scan Start Time (min)"])
        tic = _farr(self.ms2_data["Total Ion Current"])
        if rt_s.size == 0 or tic.size == 0:
            return np.asarray([], dtype=float), np.asarray([], dtype=float)
        return rt_s, tic # / 60.0, tic
    
    def tnp_trace(self):
        rt_s = _farr(self.ms2_data["Scan Start Time (min)"])
        tnp = _farr(self.ms2_data["Total Number of Peaks"])
        if rt_s.size == 0 or tnp.size == 0:
            return np.asarray([], dtype=float), np.asarray([], dtype=float)
        return rt_s, tnp # / 60.0, tnp

    def prec_trace(self):
        rt_s = _farr(self.ms2_data["Scan Start Time (min)"])
        prec = _farr(self.ms2_data["Selected Ion Intensity"])
        if rt_s.size == 0 or prec.size == 0:
            return np.asarray([], dtype=float), np.asarray([], dtype=float)
        return rt_s, prec # / 60.0, prec



def write_comparison_html(out_path: Path, title: str, traces: List[Tuple[str, np.ndarray, np.ndarray]]) -> Path:
    fig = go.Figure()
    for name, x, y in traces:
        if x.size and y.size:
            fig.add_trace(go.Scatter(x=x, y=y, mode="lines", name=name))
    fig.update_layout(title=title, xaxis_title="RT (min)", yaxis_title="TIC")
    return _write_single_html(out_path, title, [_Fig("Overlay TIC (all samples)", fig)])

def write_comparison_html_with_boxplots(
    out_path,
    title: str,
    overlay_panels,  
    box_panels, 
):
    figs = []

    for panel_title, y_label, traces in overlay_panels:
        fig = go.Figure()
        for name, x, y in traces:
            if hasattr(x, "size") and hasattr(y, "size"):
                if x.size and y.size:
                    fig.add_trace(go.Scatter(x=x, y=y, mode="lines", name=name))
            else:
                if x and y:
                    fig.add_trace(go.Scatter(x=x, y=y, mode="lines", name=name))
        fig.update_layout(title=panel_title, xaxis_title="RT (min)", yaxis_title=y_label)
        figs.append((panel_title, fig))

    for panel_title, y_label, sample_dict, do_log10p1 in box_panels:
        fig = make_boxplot_figure(panel_title, y_label, sample_dict, log10p1=do_log10p1)
        figs.append((panel_title, fig))

    return _write_single_html(out_path, title, [_Fig(t, f) for (t, f) in figs])

def write_comparison_html_multi(
    out_path: Path,
    title: str,
    panels: List[Tuple[str, str, List[Tuple[str, np.ndarray, np.ndarray]]]],
) -> Path:
    figs: List[_Fig] = []
    for panel_title, y_label, traces in panels:
        fig = go.Figure()
        for name, x, y in traces:
            if x.size and y.size:
                fig.add_trace(go.Scatter(x=x, y=y, mode="lines", name=name))
        fig.update_layout(title=panel_title, xaxis_title="RT (min)", yaxis_title=y_label)
        figs.append(_Fig(panel_title, fig))
    return _write_single_html(out_path, title, figs)
