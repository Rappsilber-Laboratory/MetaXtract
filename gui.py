from __future__ import annotations

import csv
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
import traceback
from PySide6.QtCore import QObject, Signal, Slot, QThread, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QListWidget,
    QListWidgetItem
)

from raw_parser import MetaXtract
from plotly_visualizer import (
    PlotlyMS1Visualizer,
    PlotlyMS2Visualizer,
    write_comparison_html,
    write_comparison_html_multi,
    write_comparison_html_with_boxplots,
)

from anndata_export import export_ms2_to_h5ad

class MS1Visualizer:
    def __init__(self, single_file_name: str, output_dir: str):
        self.single_file_name = single_file_name
        self.output_dir = Path(output_dir)
        self.ms1_scans = []
        self.ms1_data = {
            "Retention Time (s)": [],
            "Elapsed Scan Time (sec)": [],
            "Total Ion Current": [],
            "Total Number of Peaks": [],
            "Base Peak Intensity": [],
            "Base Peak Mass": [],
            "Ion Injection Time (ms)": [],
        }

    def generate_pdf_report(self, output_pdf_report: str):
        pass


class MS2Visualizer:
    def __init__(self, single_file_name: str, output_dir: str):
        self.single_file_name = single_file_name
        self.output_dir = Path(output_dir)
        self.ms2_scans = []
        self.ms2_data = {
            "Retention Time (s)": [],
            "Elapsed Scan Time (sec)": [],
            "Total Ion Current": [],
            "Total Number of Peaks": [],
            "Precursor Intensity": [],
            "Charge State": [],
            "Ion Injection Time (ms)": [],
        }

    def generate_pdf_report(self, output_pdf_report: str):
        pass



_NUM_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?")

def _tsv_safe(v):
    if v is None:
        return ""
    if isinstance(v, (dict, list, tuple)):
        return json.dumps(v, ensure_ascii=False)
    s = str(v)
    return s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")

def write_info_tsv(raw_parser, out_tsv_path: str):
    raw_parser.CountMS2()

    instrument_details = raw_parser.GetInstrumentDetails() or {}
    sample_information = raw_parser.GetSampleInformation() or {}

    rows = []

    rows += [
        ("File", "RAW File Name", raw_parser.GetRAWFileName()),
        ("File", "User ID", raw_parser.GetUserID()),
        ("File", "File Creation Date", raw_parser.GetFileCreationDate()),
        ("Instrument", "Instrument Name", raw_parser.GetInstrumentName()),
        ("Counts", "Number of MS2 Scans (centroid)", raw_parser.NumMS2Centroid),
        ("Counts", "Number of MS2 Scans (profile)", raw_parser.NumMS2Profile),
        ("Counts", "Number of MS1 Scans", raw_parser.NumMS1),
        ("Counts", "Total Number of Scans", raw_parser.NumSpectra),
        ("Run", "Start Time", raw_parser.StartTime),
        ("Run", "End Time", raw_parser.EndTime),
        ("Run", "Lowest Mass", raw_parser.LowMass),
        ("Run", "Highest Mass", raw_parser.HighMass),
        ("Run", "Mass Resolution", raw_parser.MassResolution),
        ("Run", "Highest Integrated Intensity", raw_parser.GetMaxIntegratedIntensity()),
        ("Run", "Highest Base Peak", raw_parser.GetHighestBasePeakOfRawFile()),
    ]

    for k, v in instrument_details.items():
        rows.append(("Instrument Details", k, v))

    for k, v in sample_information.items():
        rows.append(("Sample", k, v))

    with open(out_tsv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["Section", "Key", "Value"])
        for sec, key, val in rows:
            w.writerow([_tsv_safe(sec), _tsv_safe(key), _tsv_safe(val)])


def to_float(x):

    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if not s:
        return None
    s = s.replace("\u00a0", " ").strip()
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

def safe_call(fn, default=None):

    try:
        return fn()
    except Exception:
        return default

def td_get(trailer_data, key):

    if not trailer_data:
        return None
    #print(trailer_data)
    return trailer_data.get(key, None)


class LogWindow(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MetaXtract Log")
        self.setMinimumSize(820, 520)
        lay = QVBoxLayout(self)
        self.text = QTextEdit(self)
        self.text.setReadOnly(True)
        lay.addWidget(self.text)

    @Slot(str)
    def append_log(self, msg: str):
        self.text.append(str(msg))


class _ExtractionWorker(QObject):
    progress = Signal(int)
    log = Signal(str)
    finished = Signal()
    failed = Signal(str)

    def __init__(
        self,
        selected_files: list[str],
        output_dir_raw: str,
        selected_options: list[str],
        selected_header_options_ms2: list[str],
        selected_header_options_ms1: list[str],
        plotly_enabled: bool,
        export_fmt: str | None,
        multi_cmp: bool,
        cmp_files: list[str] | None,
        hdf5_export: bool = False,
        ms2_peaklist_export: bool = False,
        ms1_peaklist_export: bool = False
        
    ):
        super().__init__()
        self.selected_files = selected_files
        self.output_dir_raw = output_dir_raw
        self.selected_options = selected_options
        self.selected_header_options_ms2 = selected_header_options_ms2
        self.selected_header_options_ms1 = selected_header_options_ms1
        self.plotly_enabled = plotly_enabled
        self.export_fmt = export_fmt
        self.multi_cmp = bool(multi_cmp)
        self.hdf5_export = bool(hdf5_export)
        self.ms2_peaklist_export = bool(ms2_peaklist_export)
        self.ms1_peaklist_export = bool(ms1_peaklist_export)
        self.cmp_files = (cmp_files or [])
        self._stop = False

    @Slot()
    def stop(self):

        self._stop = True

    def _remove_empty_lines(self, input_file: str) -> None:
        try:
            with open(input_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            with open(input_file, "w", encoding="utf-8", errors="replace") as f:
                for line in lines:
                    if line.strip():
                        f.write(line)
        except Exception:
            return

    def _write_plotly(self, ms1_vis: PlotlyMS1Visualizer | None, ms2_vis: PlotlyMS2Visualizer | None) -> None:

        if not self.plotly_enabled:
            return
        try:
            if ms1_vis is not None:
                idx = ms1_vis.write_html_report()
                self.log.emit(f"[VIS] MS1 report: {idx}")
                if self.export_fmt:
                    outs = ms1_vis.export_images(self.export_fmt)
                    self.log.emit(f"[VIS] MS1 exported {len(outs)} images as {self.export_fmt}")
            if ms2_vis is not None:
                idx = ms2_vis.write_html_report()
                self.log.emit(f"[VIS] MS2 report: {idx}")
                if self.export_fmt:
                    outs = ms2_vis.export_images(self.export_fmt)
                    self.log.emit(f"[VIS] MS2 exported {len(outs)} images as {self.export_fmt}")
        except Exception as e:
            self.log.emit(f"[VIS][WARN] {e}")

    def _extract_ms2_scan_header(
        self,
        raw_parser,
        out_dir: Path,
        selected_options: list[str],
        base: str,
        plotly_vis: PlotlyMS2Visualizer | None,
    ):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = out_dir / f"{base}_scan_header_ms2_{ts}.csv"

        with open(csv_path, "w", newline="", encoding="utf-8", errors="replace") as f:
            w = csv.writer(f)
            w.writerow(["Scan Number", "RAW File"] + selected_options)

            num_scans = int(getattr(raw_parser, "NumSpectra", 0) or 0)
            last_ui = 0

            for scan_number in range(1, num_scans + 1):
                if self._stop:
                    break

                ms_order = safe_call(lambda: int(raw_parser.GetMSOrder(scan_number)), 0)
                if ms_order != 2:
                    continue
                #if not safe_call(lambda: raw_parser.CheckMS2Centroid(scan_number), False):
                #    continue

                trailer_data = safe_call(lambda: raw_parser.GetTrailerExtraInformaionEdited(scan_number), {}) or {}

                def opt_value(opt: str):
                    if trailer_data and opt in trailer_data:
                        v = trailer_data.get(opt, None)
                        return v if v not in (None, "") else "N/A"

                    if opt == "Retention Time (s)":
                        v = safe_call(lambda: raw_parser.GetRetentionTimeFromScanNumber(scan_number))
                        return v if v not in (None, "") else "N/A"

                    if opt == "Total Ion Current":
                        v = safe_call(lambda: raw_parser.GetTICForScanNumber(scan_number))
                        return v if v not in (None, "") else "N/A"

                    if opt == "Total Number of Peaks":
                        v = safe_call(lambda: raw_parser.GetNumPeaksForScanNumber(scan_number))
                        return v if v not in (None, "") else "N/A"

                    if opt == "Base Peak Mass":
                        bp = safe_call(lambda: raw_parser.GetBasePeakForScanNumber(scan_number), (None, None))
                        return bp[0] if isinstance(bp, (list, tuple)) and len(bp) >= 2 and bp[0] not in (None, "") else "N/A"

                    if opt == "Base Peak Intensity":
                        bp = safe_call(lambda: raw_parser.GetBasePeakForScanNumber(scan_number), (None, None))
                        return bp[1] if isinstance(bp, (list, tuple)) and len(bp) >= 2 and bp[1] not in (None, "") else "N/A"

                    if opt == "Precursor Intensity":
                        v = safe_call(lambda: raw_parser.GetPrecursorIntensityFromScanNumber(scan_number))
                        return v if v not in (None, "") else "N/A"

                    if opt == "Mass Ranges":
                        n = safe_call(lambda: raw_parser.GetNumberOfMassRangesFromScanNumber(scan_number), 0) or 0
                        ranges = []
                        for i in range(n):
                            lo, hi = safe_call(lambda i=i: raw_parser.GetMassRangeFromScanNumber(scan_number, i), (None, None))
                            if lo is None or hi is None:
                                continue
                            ranges.append(f"{lo}-{hi}")
                        return "; ".join(ranges) if ranges else "N/A"

                    if opt == "Scan Description":
                        v = safe_call(lambda: raw_parser.GetScanEventStringForScanNumber(scan_number))
                        return v if v not in (None, "") else "N/A"

                    if opt == "Detector Type":
                        return safe_call(lambda: raw_parser.GetDetectorTypeFromScanNumber(scan_number), "N/A")
                    if opt == "Mass Analyzer Type":
                        return safe_call(lambda: raw_parser.GetMassAnalyzerTypeFromScanNumber(scan_number), "N/A")
                    if opt == "Activation Type":
                        return safe_call(lambda: raw_parser.GetActivationTypeForScanNumber(scan_number), "N/A")
                    if opt == "Collision Energy":
                        return safe_call(lambda: raw_parser.GetCollisionEnergyForScanNumber(scan_number), "N/A")
                    if opt == "Frequency":
                        return safe_call(lambda: raw_parser.GetFrequencyForScanNumber(scan_number), "N/A")
                    if opt == "Number of Channels":
                        return safe_call(lambda: raw_parser.GetNumChannelsForScanNumber(scan_number), "N/A")

                    return "N/A"

                w.writerow([scan_number, base] + [opt_value(o) for o in selected_options])

                if plotly_vis is not None:
                    #rt = to_float(td_get(trailer_data, "Retention Time (s)"))
                    rt = to_float(safe_call(lambda: raw_parser.GetRetentionTimeFromScanNumber(scan_number)))
                    est = to_float(td_get(trailer_data, "Elapsed Scan Time (sec)"))
                    #tic = to_float(td_get(trailer_data, "Total Ion Current"))
                    tic = to_float(safe_call(lambda: raw_parser.GetTICForScanNumber(scan_number)))
                    #tnp = to_int(td_get(trailer_data, "Total Number of Peaks"))
                    #prec_i = to_float(td_get(trailer_data, "Precursor Intensity"))
                    tnp = to_int(safe_call(lambda: raw_parser.GetNumPeaksForScanNumber(scan_number)))
                    cs = to_int(td_get(trailer_data, "Charge State"))
                    iit = to_float(td_get(trailer_data, "Ion Injection Time (ms)"))
                    prec_i = to_float(safe_call(lambda: raw_parser.GetPrecursorIntensityFromScanNumber(scan_number)))
                    
                    if rt is None:
                        rt = to_float(safe_call(lambda: raw_parser.GetRetentionTimeFromScanNumber(scan_number)))
                    if est is None:
                        est = to_float(safe_call(lambda: raw_parser.GetElaspedScanTimeFromScanNumber(scan_number)))
                    if tic is None:
                        tic = to_float(safe_call(lambda: raw_parser.GetTICForScanNumber(scan_number)))
                    if tnp is None:
                        tnp = to_int(safe_call(lambda: raw_parser.GetNumPeaksForScanNumber(scan_number)))
                    if prec_i is None:
                        prec_i = to_float(safe_call(lambda: raw_parser.GetPrecursorIntensityFromScanNumber(scan_number)))
                    if cs is None:
                        cs = to_int(safe_call(lambda: raw_parser.GetMS2ChargeFromScanNumber(scan_number)))
                    if iit is None:
                        iit = to_float(safe_call(lambda: raw_parser.GetIonInjectionTimeFromScanNumber(scan_number)))
                        
                    bp = safe_call(lambda: raw_parser.GetBasePeakForScanNumber(scan_number), None)
                    bp_int = to_float(bp[1]) if isinstance(bp, (list, tuple)) and len(bp) >= 2 else 0.0
                    plotly_vis.ms2_data["Base Peak Intensity"].append(bp_int or 0.0)
                    plotly_vis.ms2_scans.append(scan_number)
                    plotly_vis.ms2_data["Retention Time (s)"].append(rt if rt is not None else 0.0)
                    plotly_vis.ms2_data["Elapsed Scan Time (sec)"].append(est or 0.0)
                    plotly_vis.ms2_data["Total Ion Current"].append(tic or 0.0)
                    plotly_vis.ms2_data["Total Number of Peaks"].append(tnp or 0)
                    plotly_vis.ms2_data["Precursor Intensity"].append(prec_i or 0.0)
                    plotly_vis.ms2_data["Charge State"].append(cs or 0)
                    plotly_vis.ms2_data["Ion Injection Time (ms)"].append(iit or 0.0)

                if scan_number - last_ui >= 300:
                    last_ui = scan_number
                    self.progress.emit(int((scan_number / max(1, num_scans)) * 100))

        self.log.emit(f"[INFO] MS2 scan header CSV: {csv_path}")

    def _extract_ms1_scan_header(
        self,
        raw_parser,
        out_dir: Path,
        selected_options: list[str],
        base: str,
        plotly_vis: PlotlyMS1Visualizer | None,
    ):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = out_dir / f"{base}_scan_header_ms1_{ts}.csv"

        with open(csv_path, "w", newline="", encoding="utf-8", errors="replace") as f:
            w = csv.writer(f)
            w.writerow(["Scan Number", "RAW File"] + selected_options)

            num_scans = int(getattr(raw_parser, "NumSpectra", 0) or 0)
            last_ui = 0

            for scan_number in range(1, num_scans + 1):
                if self._stop:
                    break

                ms_order = safe_call(lambda: int(raw_parser.GetMSOrder(scan_number)), 0)
                if ms_order != 1:
                    continue

                trailer_data = safe_call(lambda: raw_parser.GetTrailerExtraInformaionEdited(scan_number), {}) or {}

                def opt_value(opt: str):
                    if trailer_data and opt in trailer_data:
                        v = trailer_data.get(opt, None)
                        return v if v not in (None, "") else "N/A"

                    if opt == "Retention Time (s)":
                        v = safe_call(lambda: raw_parser.GetRetentionTimeFromScanNumber(scan_number))
                        return v if v not in (None, "") else "N/A"

                    if opt == "Total Ion Current":
                        v = safe_call(lambda: raw_parser.GetTICForScanNumber(scan_number))
                        return v if v not in (None, "") else "N/A"

                    if opt == "Total Number of Peaks":
                        v = safe_call(lambda: raw_parser.GetNumPeaksForScanNumber(scan_number))
                        return v if v not in (None, "") else "N/A"

                    if opt == "Base Peak Mass":
                        bp = safe_call(lambda: raw_parser.GetBasePeakForScanNumber(scan_number), (None, None))
                        return bp[0] if isinstance(bp, (list, tuple)) and len(bp) >= 2 and bp[0] not in (None, "") else "N/A"

                    if opt == "Base Peak Intensity":
                        bp = safe_call(lambda: raw_parser.GetBasePeakForScanNumber(scan_number), (None, None))
                        return bp[1] if isinstance(bp, (list, tuple)) and len(bp) >= 2 and bp[1] not in (None, "") else "N/A"

                    if opt == "Ion Injection Time (ms)":
                        v = safe_call(lambda: raw_parser.GetIonInjectionTimeFromScanNumber(scan_number))
                        return v if v not in (None, "") else "N/A"

                    return "N/A"

                w.writerow([scan_number, base] + [opt_value(o) for o in selected_options])

                if plotly_vis is not None:
                    #rt = to_float(td_get(trailer_data, "Retention Time (s)"))
                    rt = to_float(safe_call(lambda: raw_parser.GetRetentionTimeFromScanNumber(scan_number)))
                    est = to_float(td_get(trailer_data, "Elapsed Scan Time (sec)"))
                    #tic = to_float(td_get(trailer_data, "Total Ion Current"))
                    tic = to_float(safe_call(lambda: raw_parser.GetTICForScanNumber(scan_number)))
                    #tnp = to_int(td_get(trailer_data, "Total Number of Peaks"))
                    tnp = to_int(safe_call(lambda: raw_parser.GetNumPeaksForScanNumber(scan_number)))
                    #print(tnp)
                    iit = to_float(td_get(trailer_data, "Ion Injection Time (ms)"))

                    if rt is None:
                        rt = to_float(safe_call(lambda: raw_parser.GetRetentionTimeFromScanNumber(scan_number)))
                    if est is None:
                        est = to_float(safe_call(lambda: raw_parser.GetElaspedScanTimeFromScanNumber(scan_number)))
                    if tic is None:
                        tic = to_float(safe_call(lambda: raw_parser.GetTICForScanNumber(scan_number)))
                    if tnp is None:
                        tnp = to_int(safe_call(lambda: raw_parser.GetNumPeaksForScanNumber(scan_number)))
                       # print(tnp)
                    if iit is None:
                        iit = to_float(safe_call(lambda: raw_parser.GetIonInjectionTimeFromScanNumber(scan_number)))

                    bp = safe_call(lambda: raw_parser.GetBasePeakForScanNumber(scan_number), None)
                    bp_mass = to_float(bp[0]) if isinstance(bp, (list, tuple)) and len(bp) >= 2 else 0.0
                    bp_int = to_float(bp[1]) if isinstance(bp, (list, tuple)) and len(bp) >= 2 else 0.0

                    plotly_vis.ms1_scans.append(scan_number)
                    plotly_vis.ms1_data["Retention Time (s)"].append(rt if rt is not None else 0.0)
                    plotly_vis.ms1_data["Elapsed Scan Time (sec)"].append(est or 0.0)
                    plotly_vis.ms1_data["Total Ion Current"].append(tic or 0.0)
                    plotly_vis.ms1_data["Total Number of Peaks"].append(tnp or 0)
                    plotly_vis.ms1_data["Base Peak Mass"].append(bp_mass or 0.0)
                    plotly_vis.ms1_data["Base Peak Intensity"].append(bp_int or 0.0)
                    plotly_vis.ms1_data["Ion Injection Time (ms)"].append(iit or 0.0)

                if scan_number - last_ui >= 300:
                    last_ui = scan_number
                    self.progress.emit(int((scan_number / max(1, num_scans)) * 100))

        self.log.emit(f"[INFO] MS1 scan header CSV: {csv_path}")

    @Slot()
    def run(self):
        try:
            all_ms1_tic = []
            all_ms1_bpi = []
            all_ms1_tnp = []

            all_ms2_tic = []
            all_ms2_tnp = []
            all_ms2_prec = []
            
            ms1_box_tic, ms1_box_bpi, ms1_box_tnp = {}, {}, {}
            ms2_box_tic, ms2_box_bpi, ms2_box_tnp = {}, {}, {}

            global_out = Path(self.output_dir_raw)
            global_out.mkdir(parents=True, exist_ok=True)
            cmp_set = set(self.cmp_files) if (self.multi_cmp and self.cmp_files) else None

            for selected_file in self.selected_files:
                if cmp_set is not None and selected_file not in cmp_set:
                    continue
                if self._stop:
                    break

                self.log.emit(f"[INFO] Processing: {selected_file}")

                raw_parser = MetaXtract(selected_file)
                base = os.path.splitext(os.path.basename(selected_file))[0]
                out_dir = Path(self.output_dir_raw) / base
                out_dir.mkdir(parents=True, exist_ok=True)

                plotly_ms1 = PlotlyMS1Visualizer(base, str(out_dir)) if self.plotly_enabled else None
                plotly_ms2 = PlotlyMS2Visualizer(base, str(out_dir)) if self.plotly_enabled else None

                if self.plotly_enabled and not self.selected_header_options_ms2:
                    self.selected_header_options_ms2 = ["Retention Time (s)"]
                if self.plotly_enabled and not self.selected_header_options_ms1:
                    self.selected_header_options_ms1 = ["Retention Time (s)"]
                    
                info_tsv_path = None
                if "File-based Details" in self.selected_options:
                    info_tsv = out_dir / f"{base}_info_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tsv"
                    write_info_tsv(raw_parser, info_tsv)
                    info_tsv_path = str(info_tsv)
                    self.log.emit(f"[INFO] Wrote: {info_tsv}")
                    # info_file = out_dir / f"{base}_info_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                    # safe_call(lambda: raw_parser.CountMS2(), None)
                    # sample_information = safe_call(lambda: raw_parser.GetSampleInformation(), {}) or {}
                    # instrument_details = safe_call(lambda: raw_parser.GetInstrumentDetails(), {}) or {}
                    # with open(info_file, "w", encoding="utf-8", errors="replace") as f:
                    #     f.write(f"- RAW File Name: {safe_call(lambda: raw_parser.GetRAWFileName(), 'N/A')}\n")
                    #     f.write("- Instrument Details:\n")
                    #     for k, v in instrument_details.items():
                    #         f.write(f"{k}: {v}\n")
                    #     f.write("\n")
                    #     f.write(f"- User ID: {safe_call(lambda: raw_parser.GetUserID(), 'N/A')}\n")
                    #     f.write(f"- File Creation Date: {safe_call(lambda: raw_parser.GetFileCreationDate(), 'N/A')}\n")
                    #     f.write(f"- Instrument Name: {safe_call(lambda: raw_parser.GetInstrumentName(), 'N/A')}\n")
                    #     f.write(f"- Number of MS2 Scans (centroid): {getattr(raw_parser, 'NumMS2Centroid', 'N/A')}\n")
                    #     f.write(f"- Number of MS2 Scans (profile): {getattr(raw_parser, 'NumMS2Profile', 'N/A')}\n")
                    #     f.write(f"- Number of MS1 Scans: {getattr(raw_parser, 'NumMS1', 'N/A')}\n")
                    #     f.write(f"- Total Number of Scans: {getattr(raw_parser, 'NumSpectra', 'N/A')}\n")
                    #     f.write(f"- Start Time: {getattr(raw_parser, 'StartTime', 'N/A')}\n")
                    #     f.write(f"- End Time: {getattr(raw_parser, 'EndTime', 'N/A')}\n")
                    #     f.write(f"- Lowest Mass: {getattr(raw_parser, 'LowMass', 'N/A')}\n")
                    #     f.write(f"- Highest Mass: {getattr(raw_parser, 'HighMass', 'N/A')}\n")
                    #     f.write(f"- Mass Resolution: {getattr(raw_parser, 'MassResolution', 'N/A')}\n")
                    #     f.write(f"- Highest Integrated Intensity: {safe_call(lambda: raw_parser.GetMaxIntegratedIntensity(), 'N/A')}\n")
                    #     f.write(f"- Highest Base Peak: {safe_call(lambda: raw_parser.GetHighestBasePeakOfRawFile(), 'N/A')}\n\n")
                    #     f.write("Sample Information\n")
                    #     for k, v in sample_information.items():
                    #         f.write(f"{k}: {v}\n")
                    # self.log.emit(f"[INFO] Wrote: {info_file}")

                if "MS-Method" in self.selected_options:
                    ms_method_file = out_dir / f"{base}_MS_method_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                    with open(ms_method_file, "w", encoding="utf-8", errors="replace") as f:
                        f.write(f"{safe_call(lambda: raw_parser.GetMSMethod(), '')}\n")
                    self._remove_empty_lines(str(ms_method_file))
                    self.log.emit(f"[INFO] Wrote: {ms_method_file}")

                if "LC-Method" in self.selected_options:
                    lc_method_file = out_dir / f"{base}_LC_method_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                    with open(lc_method_file, "w", encoding="utf-8", errors="replace") as f:
                        f.write(f"{safe_call(lambda: raw_parser.GetLCMethod(), '')}\n")
                    self._remove_empty_lines(str(lc_method_file))
                    self.log.emit(f"[INFO] Wrote: {lc_method_file}")

                if self.selected_header_options_ms2:
                    self._extract_ms2_scan_header(raw_parser, out_dir, self.selected_header_options_ms2, base, plotly_ms2)
                    
                if self.hdf5_export:
                    out_h5ad = out_dir / f"{base}_MS2.h5ad"
                    export_ms2_to_h5ad(raw_parser, out_h5ad, info_tsv_path=info_tsv_path)
                    self.log.emit(f"[INFO] Wrote: {out_h5ad}")
                    
                if self.ms2_peaklist_export:
                    out_pq = out_dir / f"{base}_ms2_peaklist.parquet"
                    raw_parser.ExportPeakList(str(out_pq))
                    self.log.emit(f"[INFO] Wrote: {out_pq}")
                    
                if self.ms1_peaklist_export:
                    out_pq = out_dir / f"{base}_ms1_peaklist.parquet"
                    raw_parser.ExportMS1PeakList(str(out_pq))
                    self.log.emit(f"[INFO] Wrote: {out_pq}")
                    

                if self.selected_header_options_ms1:
                    self._extract_ms1_scan_header(raw_parser, out_dir, self.selected_header_options_ms1, base, plotly_ms1)

                self._write_plotly(plotly_ms1, plotly_ms2)
                if plotly_ms1 is not None:
                    ms1_box_tic[base] = list(plotly_ms1.ms1_data.get("Total Ion Current", []))
                    ms1_box_bpi[base] = list(plotly_ms1.ms1_data.get("Base Peak Intensity", []))
                    ms1_box_tnp[base] = list(plotly_ms1.ms1_data.get("Total Number of Peaks", []))

                if plotly_ms2 is not None:
                    ms2_box_tic[base] = list(plotly_ms2.ms2_data.get("Total Ion Current", []))
                    ms2_box_tnp[base] = list(plotly_ms2.ms2_data.get("Total Number of Peaks", []))
                    ms2_box_bpi[base] = list(plotly_ms2.ms2_data.get("Base Peak Intensity", [])) 


                if plotly_ms1 is not None:
                    x, y = plotly_ms1.tic_trace()
                    all_ms1_tic.append((base, x, y))
                    x, y = plotly_ms1.bpi_trace()
                    all_ms1_bpi.append((base, x, y))
                    x, y = plotly_ms1.tnp_trace()
                    all_ms1_tnp.append((base, x, y))

                if plotly_ms2 is not None:
                    x, y = plotly_ms2.tic_trace()
                    all_ms2_tic.append((base, x, y))
                    x, y = plotly_ms2.tnp_trace()
                    all_ms2_tnp.append((base, x, y))
                    x, y = plotly_ms2.prec_trace()
                    all_ms2_prec.append((base, x, y))


                safe_call(lambda: raw_parser.CloseRAWFile(), None)
                self.progress.emit(100)
                self.log.emit(f"[INFO] Finished: {selected_file}\n")

            if self.plotly_enabled and len(all_ms1_tic) >= 2:
                out = global_out / "MS1_compare.html"
                write_comparison_html_with_boxplots(
                    out,
                    "MS1 Comparison",
                    overlay_panels=[
                        ("Overlay TIC (MS1)", "TIC", all_ms1_tic),
                        ("Overlay BPI (MS1)", "BPI", all_ms1_bpi),
                        ("Overlay Total Peaks (MS1)", "Total Peaks", all_ms1_tnp),
                    ],
                    box_panels=[
                        ("MS1 TIC Boxplot (across samples)", "log10(TIC+1)", ms1_box_tic, True),
                        ("MS1 BPI Boxplot (across samples)", "log10(BPI+1)", ms1_box_bpi, True),
                        ("MS1 TNP Boxplot (across samples)", "Total Peaks", ms1_box_tnp, False),
                    ],
                )
                self.log.emit(f"[VIS] MS1 comparison: {out}")


            if self.plotly_enabled and len(all_ms2_tic) >= 2:
                out = global_out / "MS2_compare.html"
                write_comparison_html_with_boxplots(
                    out,
                    "MS2 Comparison",
                    overlay_panels=[
                        ("Overlay TIC (MS2)", "TIC", all_ms2_tic),
                        ("Overlay Total Peaks (MS2)", "Total Peaks", all_ms2_tnp),
                        ("Overlay Precursor Intensity (MS2)", "Precursor Intensity", all_ms2_prec),
                    ],
                    box_panels=[
                        ("MS2 TIC Boxplot (across samples)", "log10(TIC+1)", ms2_box_tic, True),
                        ("MS2 TNP Boxplot (across samples)", "Total Peaks", ms2_box_tnp, False),
                        ("MS2 BPI Boxplot (across samples)", "log10(BPI+1)", ms2_box_bpi, True),
                    ],
                )
                self.log.emit(f"[VIS] MS2 comparison: {out}")


            self.finished.emit()
        except Exception as e:
            #self.failed.emit(str(e))
            tb = traceback.format_exc()
            try:
                self.log.emit(tb)
            except Exception:
                pass
            self.failed.emit(f"{e}\n\n{tb}")

class TwoFilePickerDialog(QDialog):
    def __init__(self, files: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select 2 files to compare")
        self.setMinimumSize(760, 420)
        self._files = files
        self.selected: list[str] = []

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Pick exactly 2 files:", self))

        self.listw = QListWidget(self)
        self.listw.setSelectionMode(QListWidget.MultiSelection)
        for fp in files:
            it = QListWidgetItem(fp)
            self.listw.addItem(it)
        lay.addWidget(self.listw, 1)

        btns = QHBoxLayout()
        btn_cancel = QPushButton("Cancel", self)
        btn_ok = QPushButton("OK", self)
        btns.addStretch(1)
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        lay.addLayout(btns)

        btn_cancel.clicked.connect(self.reject)
        btn_ok.clicked.connect(self._accept_checked)

    def _accept_checked(self):
        picked = [it.text() for it in self.listw.selectedItems()]
        if len(picked) != 2:
            QMessageBox.critical(self, "Error", "Select exactly 2 files.")
            return
        self.selected = picked
        self.accept()

class MetaXtract_GUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MetaXtract")
        self.setMinimumSize(1020, 760)
        self._thread: QThread | None = None
        self._worker: _ExtractionWorker | None = None
        self.selected_files: list[str] = []

        self.setStyleSheet( #https://doc.qt.io/qt-6/stylesheet-examples.html
            """
            QMainWindow { background: #0f1115; }
            QLabel, QCheckBox { color: #e9eef5; font-size: 12px; }
            QLineEdit {
                background: #161a22; color: #e9eef5; border: 1px solid #2a3242;
                border-radius: 10px; padding: 7px 10px;
            }
            QPushButton {
                background: #7a001a; color: #ffffff; border: 1px solid #a00023;
                border-radius: 12px; padding: 9px 14px; font-weight: 700;
            }
            QPushButton:hover { background: #920020; }
            QPushButton:disabled { background: #2a3242; border: 1px solid #2a3242; color: #8fa0b6; }
            QGroupBox {
                border: 1px solid #2a3242; border-radius: 14px; margin-top: 10px;
                padding: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #ffffff;
                font-weight: 900;
            }
            QProgressBar {
                border: 1px solid #2a3242; border-radius: 10px;
                text-align: center; color: #e9eef5; background: #161a22; height: 18px;
            }
            QProgressBar::chunk { background: #7a001a; border-radius: 10px; }
            QScrollArea { border: none; background: transparent; }
            QScrollArea QWidget { background: transparent; }
            QScrollArea QWidget#qt_scrollarea_viewport { background: #0b0d12; border-radius: 12px; }
            QGroupBox { background: #0b0d12; }
            QCheckBox { spacing: 10px; }
            QCheckBox::indicator { width: 16px; height: 16px; }
            QCheckBox::indicator:unchecked { border: 1px solid #2a3242; background: #161a22; border-radius: 4px; }
            QCheckBox::indicator:checked { border: 1px solid #a00023; background: #7a001a; border-radius: 4px; }
            QTextEdit {
                background: #0b0d12; color: #e9eef5; border: 1px solid #2a3242;
                border-radius: 12px; padding: 8px;
            }
            """
        )

        root = QWidget(self)
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(16, 16, 16, 16)
        main.setSpacing(12)

        gb_io = QGroupBox("Inputs", self)
        io = QVBoxLayout(gb_io)

        r1 = QHBoxLayout()
        self.file_field = QLineEdit(self)
        self.file_field.setReadOnly(True)
        btn_files = QPushButton("Select RAW files", self)
        btn_files.clicked.connect(self.select_files)
        r1.addWidget(QLabel("RAW files", self))
        r1.addWidget(self.file_field, 1)
        r1.addWidget(btn_files)
        io.addLayout(r1)

        r2 = QHBoxLayout()
        self.output_field = QLineEdit(self)
        btn_out = QPushButton("Select output dir", self)
        btn_out.clicked.connect(self.select_output_dir)
        r2.addWidget(QLabel("Output dir", self))
        r2.addWidget(self.output_field, 1)
        r2.addWidget(btn_out)
        io.addLayout(r2)

        main.addWidget(gb_io)

        gb_opt = QGroupBox("Outputs", self)
        opt = QVBoxLayout(gb_opt)
        self.cb_file_details = QCheckBox("File-based Details", self)
        self.cb_ms_method = QCheckBox("MS-Method", self)
        self.cb_lc_method = QCheckBox("LC-Method", self)
        self.cb_plotly = QCheckBox("Visualisations", self)
        self.cb_ms2_peaklist = QCheckBox("Export MS2 extended peak list (parquet)", self)
        self.cb_ms1_peaklist = QCheckBox("Export MS1 peak list (parquet)", self)
        #self.cb_hdf5 = QCheckBox("AnnData (HDF5 .h5ad) [MS2 only]", self)
        
        self.cb_multi_cmp = QCheckBox("Multi sample comparison (2 files selection)", self)
        self.cb_multi_cmp.setEnabled(True)
        opt.addWidget(self.cb_multi_cmp)
        opt.addWidget(self.cb_file_details)
        opt.addWidget(self.cb_ms_method)
        opt.addWidget(self.cb_lc_method)
        opt.addWidget(self.cb_plotly)
        opt.addWidget(self.cb_ms2_peaklist)
        opt.addWidget(self.cb_ms1_peaklist)
        #opt.addWidget(self.cb_hdf5)
        main.addWidget(gb_opt)

        gb_cols = QGroupBox("Scan Header Columns", self)
        cols = QHBoxLayout(gb_cols)

        self.scan_header_options = []
        ms2_box = QGroupBox("MS2", self)
        ms2_l = QVBoxLayout(ms2_box)
        ms2_select_all = QPushButton("Select All (MS2)", self)
        ms2_select_all.clicked.connect(lambda: [cb.setChecked(True) for cb in self.scan_header_options])
        ms2_l.addWidget(ms2_select_all)
        ms2_scroll = QScrollArea(self)
        ms2_scroll.setWidgetResizable(True)
        ms2_inner = QWidget(self)
        ms2_inner_l = QVBoxLayout(ms2_inner)

        ms2_cols = [
            "Total Ion Current", "Total Number of Peaks", "Number of Channels", "Frequency",
            "Collision Energy", "Retention Time (s)", "Mass Ranges", "Precursor Intensity",
            "Scan Description", "AGC", "Micro Scan Count", "Ion Injection Time (ms)",
            "Elapsed Scan Time (sec)", "Activation Type", "Mass Analyzer Type", "Detector Type",
            "Base Peak Mass", "Average Scan by Inst", "Orbitrap Resolution", "API Process Delay",
            "Dependency Type", "Multi Inject Info", "Base Peak Intensity", "Master Scan Number",
            "Monoisotopic M/Z", "Charge State", "HCD Energy", "HCD Energy eV",
            "MS2 Isolation Width", "Access ID", "Conversion Parameter I", "Conversion Parameter A",
            "Conversion Parameter B", "Conversion Parameter C", "Conversion Parameter D",
            "Conversion Parameter E", "Temperature Comp. (ppm)", "RF Comp. (ppm)",
            "Space Charge Comp. (ppm)", "Resolution Comp. (ppm)", "Number of LM Found",
            "LM Correction (ppm)", "RawOvFtT", "Injection t0", "Reagent Ion Injection Time (ms)",
            "FAIMS Voltage On", "FAIMS CV",
        ]
        for c in ms2_cols:
            cb = QCheckBox(c, self)
            self.scan_header_options.append(cb)
            ms2_inner_l.addWidget(cb)
        ms2_inner_l.addItem(QSpacerItem(10, 10, QSizePolicy.Minimum, QSizePolicy.Expanding))
        ms2_scroll.setWidget(ms2_inner)
        ms2_l.addWidget(ms2_scroll)

        self.scan_header_options_ms1 = []
        ms1_box = QGroupBox("MS1", self)
        ms1_l = QVBoxLayout(ms1_box)
        ms1_select_all = QPushButton("Select All (MS1)", self)
        ms1_select_all.clicked.connect(lambda: [cb.setChecked(True) for cb in self.scan_header_options_ms1])
        ms1_l.addWidget(ms1_select_all)
        ms1_scroll = QScrollArea(self)
        ms1_scroll.setWidgetResizable(True)
        ms1_inner = QWidget(self)
        ms1_inner_l = QVBoxLayout(ms1_inner)

        ms1_cols = [
            "Ion Injection Time (ms)", "Total Number of Peaks", "Total Ion Current",
            "Retention Time (s)", "Base Peak Intensity", "Base Peak Mass",
            "Multi Inject Info", "Multiple Injection",
        ]
        for c in ms1_cols:
            cb = QCheckBox(c, self)
            self.scan_header_options_ms1.append(cb)
            ms1_inner_l.addWidget(cb)
        ms1_inner_l.addItem(QSpacerItem(10, 10, QSizePolicy.Minimum, QSizePolicy.Expanding))
        ms1_scroll.setWidget(ms1_inner)
        ms1_l.addWidget(ms1_scroll)

        cols.addWidget(ms2_box, 1)
        cols.addWidget(ms1_box, 1)
        main.addWidget(gb_cols, 1)

        gb_run = QGroupBox("Run", self)
        run = QVBoxLayout(gb_run)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        run.addWidget(self.progress_bar)

        rr = QHBoxLayout()
        self.btn_run = QPushButton("Run", self)
        self.btn_run.clicked.connect(self.extract_information)
        self.btn_stop = QPushButton("Stop", self)
        self.btn_stop.clicked.connect(self.stop_processing)
        self.btn_stop.setEnabled(False)
        rr.addStretch(1)
        rr.addWidget(self.btn_stop)
        rr.addWidget(self.btn_run)
        run.addLayout(rr)

        main.addWidget(gb_run)

    def show_error(self, msg: str):
        QMessageBox.critical(self, "Error", str(msg))

    def select_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select RAW files", "", "RAW Files (*.raw);;All Files (*)")
        if files:
            self.selected_files = files
            self.file_field.setText("; ".join(map(str, files)))

    def select_output_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select output directory")
        if d:
            self.output_field.setText(d)

    @Slot()
    def _on_done(self):
        if getattr(self, "log_window", None) is not None:
            self.log_window.append_log("Done.")
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._shutdown_thread(wait=True)

    @Slot(str)
    def _on_fail(self, msg: str):
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.show_error(msg)
        self._shutdown_thread(wait=True)

    def _shutdown_thread(self, wait: bool):
        t = self._thread
        w = self._worker
        self._thread = None
        self._worker = None

        if w is not None:
            try:
                w.stop()
            except Exception:
                pass
            w.deleteLater()

        if t is not None:
            try:
                t.quit()
            except Exception:
                pass
            if wait and QThread.currentThread() != t:
                t.wait()
            t.deleteLater()

    def stop_processing(self):
        if self._worker is not None:
            try:
                self._worker.stop()
            except Exception:
                pass
        self.btn_stop.setEnabled(False)

    def extract_information(self):
        selected_files = getattr(self, "selected_files", None)
        output_dir_raw = self.output_field.text().strip()

        selected_options = []
        if self.cb_file_details.isChecked():
            selected_options.append("File-based Details")
        if self.cb_ms_method.isChecked():
            selected_options.append("MS-Method")
        if self.cb_lc_method.isChecked():
            selected_options.append("LC-Method")

        plotly_enabled = self.cb_plotly.isChecked()
        ms2_peaklist_export = self.cb_ms2_peaklist.isChecked()
        ms1_peaklist_export = self.cb_ms1_peaklist.isChecked()
        #hdf5_export = self.cb_hdf5.isChecked()
        hdf5_export = False
        export_fmt = None

        if not selected_files:
            self.show_error("Select at least one RAW file.")
            return
        if not output_dir_raw:
            self.show_error("Select an output directory.")
            return
        
        multi_cmp = self.cb_plotly.isChecked() and self.cb_multi_cmp.isChecked()
        cmp_files = None
        
        if multi_cmp:
            if len(selected_files) < 2:
                self.show_error("Multi sample comparison requires at least 2 selected RAW files.")
                return
            if len(selected_files) == 2:
                cmp_files = list(selected_files)
            else:
                dlg = TwoFilePickerDialog(list(selected_files), self)
                if dlg.exec() != QDialog.Accepted:
                    return
                cmp_files = dlg.selected

        if self._thread is not None and self._thread.isRunning():
            self.show_error("Processing already running.")
            return

        scan_header_options_ms2 = [cb.text() for cb in self.scan_header_options if cb.isChecked()]
        scan_header_options_ms1 = [cb.text() for cb in self.scan_header_options_ms1 if cb.isChecked()]

        self.log_window = LogWindow(self)
        self.log_window.show()

        self.progress_bar.setValue(0)
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)

        self._thread = QThread()
        self._worker = _ExtractionWorker(
            selected_files=selected_files,
            output_dir_raw=output_dir_raw,
            selected_options=selected_options,
            selected_header_options_ms2=scan_header_options_ms2,
            selected_header_options_ms1=scan_header_options_ms1,
            plotly_enabled=plotly_enabled,
            export_fmt=export_fmt,
            multi_cmp=multi_cmp,
            cmp_files=cmp_files,
            hdf5_export=hdf5_export, 
            ms2_peaklist_export=ms2_peaklist_export,
            ms1_peaklist_export=ms1_peaklist_export,
        )
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress_bar.setValue, Qt.QueuedConnection)
        self._worker.log.connect(self.log_window.append_log, Qt.QueuedConnection)
        self._worker.finished.connect(self._on_done, Qt.QueuedConnection)
        self._worker.failed.connect(self._on_fail, Qt.QueuedConnection)

        self._thread.start()

    def closeEvent(self, event):
        if self._thread is not None and self._thread.isRunning():
            self.stop_processing()
            self._shutdown_thread(wait=True)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    w = MetaXtract_GUI()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
