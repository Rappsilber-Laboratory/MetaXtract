from __future__ import annotations

import csv
import json
import os
import re
import signal
import sys
import threading
from datetime import datetime
from pathlib import Path
import traceback
from PySide6.QtCore import QObject, Signal, Slot, QThread, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QInputDialog,
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
    QTableWidget,
    QTableWidgetItem,
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
from runtime_metrics import (
    FileUsageMonitor,
    append_runtime_usage_tsv,
    format_bytes,
    format_file_usage,
)
from sdrf_columns import column_group
from sdrf_export import (
    available_sdrf_columns,
    enrich_sdrf_rows_for_file,
    validate_sdrf_metadata,
    write_sdrf,
)

class MS1Visualizer:
    def __init__(self, single_file_name: str, output_dir: str):
        self.single_file_name = single_file_name
        self.output_dir = Path(output_dir)
        self.ms1_scans = []
        self.ms1_data = {
            "Scan Start Time (min)": [],
            "Elapsed Scan Time (sec)": [],
            "Total Ion Current": [],
            "Total Number of Peaks": [],
            "Base Peak Intensity": [],
            "Base Peak m/z": [],
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
            "Scan Start Time (min)": [],
            "Elapsed Scan Time (sec)": [],
            "Total Ion Current": [],
            "Total Number of Peaks": [],
            "Selected Ion Intensity": [],
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

def write_info_tsv(raw_parser, out_tsv_path: str, should_stop=None):
    raw_parser.CountMS2(should_stop=should_stop)

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


COLUMN_SOURCE_ALIASES = {
    "Scan Start Time (min)": ("Retention Time (min)", "Retention Time (s)"),
    "Base Peak m/z": ("Base Peak Mass",),
    "Selected Ion Intensity": ("Precursor Intensity",),
    "Scan Window m/z Range": ("Mass Ranges",),
    "Filter String": ("Scan Description",),
    "Dissociation Method": ("Activation Type",),
    "Sampling Frequency": ("Frequency",),
    "Experimental Precursor Monoisotopic m/z": ("Monoisotopic M/Z",),
    "Isolation Window Width (m/z)": ("MS2 Isolation Width",),
    "Normalized Collision Energy (%)": ("HCD Energy",),
    "Collision Energy (eV)": ("HCD Energy eV",),
    "FAIMS Compensation Voltage": ("FAIMS CV",),
    "thermo_Number of Channels": ("Number of Channels",),
    "thermo_AGC": ("AGC",),
    "thermo_Micro Scan Count": ("Micro Scan Count",),
    "thermo_Elapsed Scan Time (sec)": ("Elapsed Scan Time (sec)",),
    "thermo_Average Scan by Inst": ("Average Scan by Inst",),
    "thermo_Orbitrap Resolution": ("Orbitrap Resolution",),
    "thermo_API Process Delay": ("API Process Delay",),
    "thermo_Dependency Type": ("Dependency Type",),
    "thermo_Multi Inject Info": ("Multi Inject Info",),
    "thermo_Master Scan Number": ("Master Scan Number",),
    "thermo_Access ID": ("Access ID",),
    "thermo_Conversion Parameter I": ("Conversion Parameter I",),
    "thermo_Conversion Parameter A": ("Conversion Parameter A",),
    "thermo_Conversion Parameter B": ("Conversion Parameter B",),
    "thermo_Conversion Parameter C": ("Conversion Parameter C",),
    "thermo_Conversion Parameter D": ("Conversion Parameter D",),
    "thermo_Conversion Parameter E": ("Conversion Parameter E",),
    "thermo_Temperature Comp. (ppm)": ("Temperature Comp. (ppm)",),
    "thermo_RF Comp. (ppm)": ("RF Comp. (ppm)",),
    "thermo_Space Charge Comp. (ppm)": ("Space Charge Comp. (ppm)",),
    "thermo_Resolution Comp. (ppm)": ("Resolution Comp. (ppm)",),
    "thermo_Number of LM Found": ("Number of LM Found",),
    "thermo_LM Correction (ppm)": ("LM Correction (ppm)",),
    "thermo_RawOvFtT": ("RawOvFtT",),
    "thermo_Injection t0": ("Injection t0",),
    "thermo_Reagent Ion Injection Time (ms)": ("Reagent Ion Injection Time (ms)",),
    "thermo_FAIMS Voltage On": ("FAIMS Voltage On",),
    "thermo_Multiple Injection": ("Multiple Injection",),
}


def trailer_value(trailer_data, output_label: str):
    if not trailer_data:
        return None
    for key in (output_label, *COLUMN_SOURCE_ALIASES.get(output_label, ())):
        value = trailer_data.get(key, None)
        if value not in (None, ""):
            return value
    return None


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
        sdrf_payload: dict | None = None,
        hdf5_export: bool = False,
        ms2_peaklist_export: bool = False,
        ms1_peaklist_export: bool = False,
        ms2_technical_details_export: bool = False,
        ms1_technical_details_export: bool = False
        
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
        self.ms2_technical_details_export = bool(ms2_technical_details_export)
        self.ms1_technical_details_export = bool(ms1_technical_details_export)
        self.cmp_files = (cmp_files or [])
        self.sdrf_payload = sdrf_payload or {}
        self._stop_event = threading.Event()
        self._current_raw_parser = None
        self._file_usage_monitor: FileUsageMonitor | None = None
        self._file_usage_path: str | None = None
        self._runtime_log_path: Path | None = None

    @Slot()
    def stop(self):
        self._stop_event.set()

    def should_stop(self) -> bool:
        return self._stop_event.is_set() or QThread.currentThread().isInterruptionRequested()

    def _close_current_raw_file(self) -> None:
        raw_parser = self._current_raw_parser
        self._current_raw_parser = None
        if raw_parser is not None:
            safe_call(lambda: raw_parser.CloseRAWFile(), None)

    def _start_file_usage(self, selected_file: str) -> None:
        self._file_usage_path = selected_file
        self._file_usage_monitor = FileUsageMonitor().start()
        self.log.emit(
            f"[METRICS] Started: {selected_file} | "
            f"Memory RSS: {format_bytes(self._file_usage_monitor.start_rss_bytes)}"
        )

    def _finish_file_usage(self, status: str) -> None:
        monitor = self._file_usage_monitor
        selected_file = self._file_usage_path
        self._file_usage_monitor = None
        self._file_usage_path = None
        if monitor is None or selected_file is None:
            return
        usage = monitor.stop()
        self.log.emit(f"[METRICS] {status}: {selected_file} | {format_file_usage(usage)}")
        if self._runtime_log_path is not None:
            try:
                append_runtime_usage_tsv(self._runtime_log_path, selected_file, status, usage)
            except Exception as e:
                self.log.emit(f"[METRICS][WARN] Could not write runtime TSV: {e}")

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
                if self.should_stop():
                    break

                ms_order = safe_call(lambda: int(raw_parser.GetMSOrder(scan_number)), 0)
                if ms_order != 2:
                    continue
                #if not safe_call(lambda: raw_parser.CheckMS2Centroid(scan_number), False):
                #    continue

                trailer_data = safe_call(lambda: raw_parser.GetTrailerExtraInformaionEdited(scan_number), {}) or {}

                def opt_value(opt: str):
                    v = trailer_value(trailer_data, opt)
                    if v is not None:
                        return v

                    if opt in ("Scan Start Time (min)", "Retention Time (min)", "Retention Time (s)"):
                        v = safe_call(lambda: raw_parser.GetRetentionTimeFromScanNumber(scan_number))
                        return v if v not in (None, "") else "N/A"

                    if opt == "Total Ion Current":
                        v = safe_call(lambda: raw_parser.GetTICForScanNumber(scan_number))
                        return v if v not in (None, "") else "N/A"

                    if opt == "Total Number of Peaks":
                        v = safe_call(lambda: raw_parser.GetNumPeaksForScanNumber(scan_number))
                        return v if v not in (None, "") else "N/A"

                    if opt in ("Base Peak m/z", "Base Peak Mass"):
                        bp = safe_call(lambda: raw_parser.GetBasePeakForScanNumber(scan_number), (None, None))
                        return bp[0] if isinstance(bp, (list, tuple)) and len(bp) >= 2 and bp[0] not in (None, "") else "N/A"

                    if opt == "Base Peak Intensity":
                        bp = safe_call(lambda: raw_parser.GetBasePeakForScanNumber(scan_number), (None, None))
                        return bp[1] if isinstance(bp, (list, tuple)) and len(bp) >= 2 and bp[1] not in (None, "") else "N/A"

                    if opt in ("Selected Ion Intensity", "Precursor Intensity"):
                        v = safe_call(lambda: raw_parser.GetPrecursorIntensityFromScanNumber(scan_number))
                        return v if v not in (None, "") else "N/A"

                    if opt in ("Scan Window m/z Range", "Mass Ranges"):
                        n = safe_call(lambda: raw_parser.GetNumberOfMassRangesFromScanNumber(scan_number), 0) or 0
                        ranges = []
                        for i in range(n):
                            lo, hi = safe_call(lambda i=i: raw_parser.GetMassRangeFromScanNumber(scan_number, i), (None, None))
                            if lo is None or hi is None:
                                continue
                            ranges.append(f"{lo}-{hi}")
                        return "; ".join(ranges) if ranges else "N/A"

                    if opt in ("Filter String", "Scan Description"):
                        v = safe_call(lambda: raw_parser.GetScanEventStringForScanNumber(scan_number))
                        return v if v not in (None, "") else "N/A"

                    if opt == "Scan Mode":
                        v = safe_call(lambda: raw_parser.GetScanModeFromScanNumber(scan_number))
                        return v if v not in (None, "") else "N/A"

                    if opt == "Detector Type":
                        return safe_call(lambda: raw_parser.GetDetectorTypeFromScanNumber(scan_number), "N/A")
                    if opt == "Mass Analyzer Type":
                        return safe_call(lambda: raw_parser.GetMassAnalyzerTypeFromScanNumber(scan_number), "N/A")
                    if opt in ("Dissociation Method", "Activation Type"):
                        return safe_call(lambda: raw_parser.GetActivationTypeForScanNumber(scan_number), "N/A")
                    if opt == "Collision Energy":
                        return safe_call(lambda: raw_parser.GetCollisionEnergyForScanNumber(scan_number), "N/A")
                    if opt in ("Sampling Frequency", "Frequency"):
                        return safe_call(lambda: raw_parser.GetFrequencyForScanNumber(scan_number), "N/A")
                    if opt in ("thermo_Number of Channels", "Number of Channels"):
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
                    plotly_vis.ms2_data["Scan Start Time (min)"].append(rt if rt is not None else 0.0)
                    plotly_vis.ms2_data["Elapsed Scan Time (sec)"].append(est or 0.0)
                    plotly_vis.ms2_data["Total Ion Current"].append(tic or 0.0)
                    plotly_vis.ms2_data["Total Number of Peaks"].append(tnp or 0)
                    plotly_vis.ms2_data["Selected Ion Intensity"].append(prec_i or 0.0)
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
                if self.should_stop():
                    break

                ms_order = safe_call(lambda: int(raw_parser.GetMSOrder(scan_number)), 0)
                if ms_order != 1:
                    continue

                trailer_data = safe_call(lambda: raw_parser.GetTrailerExtraInformaionEdited(scan_number), {}) or {}

                def opt_value(opt: str):
                    v = trailer_value(trailer_data, opt)
                    if v is not None:
                        return v

                    if opt in ("Scan Start Time (min)", "Retention Time (min)", "Retention Time (s)"):
                        v = safe_call(lambda: raw_parser.GetRetentionTimeFromScanNumber(scan_number))
                        return v if v not in (None, "") else "N/A"

                    if opt == "Total Ion Current":
                        v = safe_call(lambda: raw_parser.GetTICForScanNumber(scan_number))
                        return v if v not in (None, "") else "N/A"

                    if opt == "Total Number of Peaks":
                        v = safe_call(lambda: raw_parser.GetNumPeaksForScanNumber(scan_number))
                        return v if v not in (None, "") else "N/A"

                    if opt in ("Base Peak m/z", "Base Peak Mass"):
                        bp = safe_call(lambda: raw_parser.GetBasePeakForScanNumber(scan_number), (None, None))
                        return bp[0] if isinstance(bp, (list, tuple)) and len(bp) >= 2 and bp[0] not in (None, "") else "N/A"

                    if opt == "Base Peak Intensity":
                        bp = safe_call(lambda: raw_parser.GetBasePeakForScanNumber(scan_number), (None, None))
                        return bp[1] if isinstance(bp, (list, tuple)) and len(bp) >= 2 and bp[1] not in (None, "") else "N/A"

                    if opt == "Ion Injection Time (ms)":
                        v = safe_call(lambda: raw_parser.GetIonInjectionTimeFromScanNumber(scan_number))
                        return v if v not in (None, "") else "N/A"

                    if opt == "Scan Mode":
                        v = safe_call(lambda: raw_parser.GetScanModeFromScanNumber(scan_number))
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
                    plotly_vis.ms1_data["Scan Start Time (min)"].append(rt if rt is not None else 0.0)
                    plotly_vis.ms1_data["Elapsed Scan Time (sec)"].append(est or 0.0)
                    plotly_vis.ms1_data["Total Ion Current"].append(tic or 0.0)
                    plotly_vis.ms1_data["Total Number of Peaks"].append(tnp or 0)
                    plotly_vis.ms1_data["Base Peak m/z"].append(bp_mass or 0.0)
                    plotly_vis.ms1_data["Base Peak Intensity"].append(bp_int or 0.0)
                    plotly_vis.ms1_data["Ion Injection Time (ms)"].append(iit or 0.0)

                if scan_number - last_ui >= 300:
                    last_ui = scan_number
                    self.progress.emit(int((scan_number / max(1, num_scans)) * 100))

        self.log.emit(f"[INFO] MS1 scan header CSV: {csv_path}")

    def _extract_technical_details(
        self,
        raw_parser,
        out_dir: Path,
        base: str,
        ms_order: int,
    ):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ms_label = f"ms{ms_order}"
        csv_path = out_dir / f"{base}_technical_details_{ms_label}_{ts}.csv"

        rows = []
        columns = ["Scan Number", "RAW File"]
        seen_columns = set(columns)

        num_scans = int(getattr(raw_parser, "NumSpectra", 0) or 0)
        last_ui = 0

        for scan_number in range(1, num_scans + 1):
            if self.should_stop():
                break

            scan_ms_order = safe_call(lambda: int(raw_parser.GetMSOrder(scan_number)), 0)
            if scan_ms_order != ms_order:
                continue

            info = safe_call(lambda: raw_parser.GetMoreMSInfos(scan_number), {}) or {}
            if not isinstance(info, dict):
                info = {}

            row = {"Scan Number": scan_number, "RAW File": base}
            for key, value in info.items():
                if key in ("Scan Number", "RAW File"):
                    continue
                if key not in seen_columns:
                    seen_columns.add(key)
                    columns.append(key)
                row[key] = value
            rows.append(row)

            if scan_number - last_ui >= 300:
                last_ui = scan_number
                self.progress.emit(int((scan_number / max(1, num_scans)) * 100))

        with open(csv_path, "w", newline="", encoding="utf-8", errors="replace") as f:
            w = csv.writer(f)
            w.writerow(columns)
            for row in rows:
                w.writerow([_tsv_safe(row.get(col, "N/A")) for col in columns])

        self.log.emit(f"[INFO] MS{ms_order} technical details CSV: {csv_path}")

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
            sdrf_rows = []

            global_out = Path(self.output_dir_raw)
            global_out.mkdir(parents=True, exist_ok=True)
            self._runtime_log_path = global_out / f"runtime_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tsv"
            self.log.emit(f"[METRICS] Runtime TSV: {self._runtime_log_path}")
            cmp_set = set(self.cmp_files) if (self.multi_cmp and self.cmp_files) else None

            for selected_file in self.selected_files:
                if cmp_set is not None and selected_file not in cmp_set:
                    continue
                if self.should_stop():
                    break

                self.log.emit(f"[INFO] Processing: {selected_file}")
                self._start_file_usage(selected_file)

                raw_parser = MetaXtract(selected_file)
                self._current_raw_parser = raw_parser
                base = os.path.splitext(os.path.basename(selected_file))[0]
                out_dir = Path(self.output_dir_raw) / base
                out_dir.mkdir(parents=True, exist_ok=True)

                if self.sdrf_payload:
                    instrument_details = safe_call(lambda: raw_parser.GetInstrumentDetails(), {}) or {}
                    instrument_candidates = (
                        instrument_details.get("Instrument Model"),
                        instrument_details.get("Instrument Name"),
                        safe_call(lambda: raw_parser.GetInstrumentName(), ""),
                    )
                    instrument = next(
                        (
                            str(value).strip()
                            for value in instrument_candidates
                            if value
                            and str(value).strip().casefold()
                            not in {"unknown", "n/a", "not available"}
                        ),
                        "",
                    )
                    acquisition_date = safe_call(lambda: raw_parser.GetFileCreationDate(), "")
                    file_rows = enrich_sdrf_rows_for_file(
                        self.sdrf_payload.get("rows", []),
                        selected_file,
                        instrument,
                        acquisition_date,
                    )
                    if any(not row.get("instrument") for row in file_rows):
                        raise ValueError(
                            f"No instrument model was found for {selected_file}. "
                            "Provide an instrument override in the SDRF editor."
                        )
                    sdrf_rows.extend(file_rows)

                plotly_ms1 = PlotlyMS1Visualizer(base, str(out_dir)) if self.plotly_enabled else None
                plotly_ms2 = PlotlyMS2Visualizer(base, str(out_dir)) if self.plotly_enabled else None

                if self.plotly_enabled and not self.selected_header_options_ms2:
                    self.selected_header_options_ms2 = ["Scan Start Time (min)"]
                if self.plotly_enabled and not self.selected_header_options_ms1:
                    self.selected_header_options_ms1 = ["Scan Start Time (min)"]
                    
                info_tsv_path = None
                if "File-based Details" in self.selected_options:
                    info_tsv = out_dir / f"{base}_info_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tsv"
                    write_info_tsv(raw_parser, info_tsv, should_stop=self.should_stop)
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

                if self.should_stop():
                    break

                if "MS-Method" in self.selected_options:
                    ms_method_file = out_dir / f"{base}_MS_method_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                    with open(ms_method_file, "w", encoding="utf-8", errors="replace") as f:
                        f.write(f"{safe_call(lambda: raw_parser.GetMSMethod(), '')}\n")
                    self._remove_empty_lines(str(ms_method_file))
                    self.log.emit(f"[INFO] Wrote: {ms_method_file}")

                if self.should_stop():
                    break

                if "LC-Method" in self.selected_options:
                    lc_method_file = out_dir / f"{base}_LC_method_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                    with open(lc_method_file, "w", encoding="utf-8", errors="replace") as f:
                        f.write(f"{safe_call(lambda: raw_parser.GetLCMethod(), '')}\n")
                    self._remove_empty_lines(str(lc_method_file))
                    self.log.emit(f"[INFO] Wrote: {lc_method_file}")

                if self.should_stop():
                    break

                if self.selected_header_options_ms2:
                    self._extract_ms2_scan_header(raw_parser, out_dir, self.selected_header_options_ms2, base, plotly_ms2)

                if self.should_stop():
                    break

                if self.ms2_technical_details_export:
                    self._extract_technical_details(raw_parser, out_dir, base, 2)
                    
                if self.should_stop():
                    break

                if self.hdf5_export:
                    out_h5ad = out_dir / f"{base}_MS2.h5ad"
                    export_ms2_to_h5ad(raw_parser, out_h5ad, info_tsv_path=info_tsv_path, should_stop=self.should_stop)
                    self.log.emit(f"[INFO] Wrote: {out_h5ad}")
                    
                if self.should_stop():
                    break

                if self.ms2_peaklist_export:
                    out_pq = out_dir / f"{base}_ms2_peaklist.parquet"
                    raw_parser.ExportPeakList(str(out_pq), should_stop=self.should_stop)
                    self.log.emit(f"[INFO] Wrote: {out_pq}")
                    
                if self.should_stop():
                    break

                if self.ms1_peaklist_export:
                    out_pq = out_dir / f"{base}_ms1_peaklist.parquet"
                    raw_parser.ExportMS1PeakList(str(out_pq), should_stop=self.should_stop)
                    self.log.emit(f"[INFO] Wrote: {out_pq}")
                    

                if self.should_stop():
                    break

                if self.selected_header_options_ms1:
                    self._extract_ms1_scan_header(raw_parser, out_dir, self.selected_header_options_ms1, base, plotly_ms1)

                if self.should_stop():
                    break

                if self.ms1_technical_details_export:
                    self._extract_technical_details(raw_parser, out_dir, base, 1)

                if self.should_stop():
                    break

                self._write_plotly(plotly_ms1, plotly_ms2)
                if self.should_stop():
                    break

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
                self._current_raw_parser = None
                self.progress.emit(100)
                self.log.emit(f"[INFO] Finished: {selected_file}")
                self._finish_file_usage("Finished")
                self.log.emit("")

            if self.should_stop():
                self._close_current_raw_file()
                self._finish_file_usage("Stopped")
                self.log.emit("[INFO] Processing stopped.")

            if not self.should_stop() and self.plotly_enabled and len(all_ms1_tic) >= 2:
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


            if not self.should_stop() and self.plotly_enabled and len(all_ms2_tic) >= 2:
                out = global_out / "MS2_compare.html"
                write_comparison_html_with_boxplots(
                    out,
                    "MS2 Comparison",
                    overlay_panels=[
                        ("Overlay TIC (MS2)", "TIC", all_ms2_tic),
                        ("Overlay Total Peaks (MS2)", "Total Peaks", all_ms2_tnp),
                        ("Overlay Selected Ion Intensity (MS2)", "Selected Ion Intensity", all_ms2_prec),
                    ],
                    box_panels=[
                        ("MS2 TIC Boxplot (across samples)", "log10(TIC+1)", ms2_box_tic, True),
                        ("MS2 TNP Boxplot (across samples)", "Total Peaks", ms2_box_tnp, False),
                        ("MS2 BPI Boxplot (across samples)", "log10(BPI+1)", ms2_box_bpi, True),
                    ],
                )
                self.log.emit(f"[VIS] MS2 comparison: {out}")

            if not self.should_stop() and self.sdrf_payload:
                out = write_sdrf(
                    global_out / "metadata.sdrf.tsv",
                    sdrf_rows,
                    factor_name=self.sdrf_payload.get("factor_name", ""),
                    extra_columns=self.sdrf_payload.get("extra_columns", []),
                )
                self.log.emit(f"[INFO] SDRF-Proteomics metadata: {out}")
            self.finished.emit()
        except InterruptedError:
            self._close_current_raw_file()
            self._finish_file_usage("Stopped")
            self.log.emit("[INFO] Processing stopped.")
            self.finished.emit()
        except Exception as e:
            self._close_current_raw_file()
            self._finish_file_usage("Failed")
            #self.failed.emit(str(e))
            tb = traceback.format_exc()
            try:
                self.log.emit(tb)
            except Exception:
                pass
            self.failed.emit(f"{e}\n\n{tb}")

class ComparisonSamplePickerDialog(QDialog):
    def __init__(self, files: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select samples to compare")
        self.setMinimumSize(760, 420)
        self._files = files
        self.selected: list[str] = []

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Select at least 2 samples for the comparison:", self))

        self.listw = QListWidget(self)
        self.listw.setSelectionMode(QListWidget.MultiSelection)
        for fp in files:
            it = QListWidgetItem(fp)
            self.listw.addItem(it)
        lay.addWidget(self.listw, 1)

        btns = QHBoxLayout()
        btn_all = QPushButton("Select all", self)
        btn_clear = QPushButton("Clear", self)
        btn_cancel = QPushButton("Cancel", self)
        btn_ok = QPushButton("OK", self)
        btns.addWidget(btn_all)
        btns.addWidget(btn_clear)
        btns.addStretch(1)
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        lay.addLayout(btns)

        btn_all.clicked.connect(self.listw.selectAll)
        btn_clear.clicked.connect(self.listw.clearSelection)
        btn_cancel.clicked.connect(self.reject)
        btn_ok.clicked.connect(self._accept_checked)

    def _accept_checked(self):
        picked = [it.text() for it in self.listw.selectedItems()]
        if len(picked) < 2:
            QMessageBox.critical(self, "Error", "Select at least 2 samples.")
            return
        self.selected = picked
        self.accept()


class SdrfColumnPickerDialog(QDialog):
    CUSTOM_FACTOR = "factor value[custom factor]"

    def __init__(self, headers: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add SDRF columns")
        self.setMinimumSize(760, 580)
        self.selected_headers: list[str] = []

        layout = QVBoxLayout(self)
        help_text = QLabel(
            "Search the official SDRF registry, select one or more known column names, "
            "then click Add selected columns.",
            self,
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Search, e.g. disease, treatment, collision energy...")
        layout.addWidget(self.search)

        self.listw = QListWidget(self)
        self.listw.setSelectionMode(QAbstractItemView.ExtendedSelection)
        factor_item = QListWidgetItem(
            f"{self.CUSTOM_FACTOR}    —    Experimental factors"
        )
        factor_item.setData(Qt.UserRole, self.CUSTOM_FACTOR)
        factor_item.setToolTip("Adds factor value[your factor name] after asking for its name.")
        self.listw.addItem(factor_item)
        for header in headers:
            group = column_group(header)
            item = QListWidgetItem(f"{header}    —    {group}")
            item.setData(Qt.UserRole, header)
            item.setToolTip(f"Official SDRF column: {header}")
            self.listw.addItem(item)
        layout.addWidget(self.listw, 1)

        self.count_label = QLabel(self)
        layout.addWidget(self.count_label)

        buttons = QHBoxLayout()
        btn_cancel = QPushButton("Cancel", self)
        btn_add = QPushButton("Add selected columns", self)
        buttons.addStretch(1)
        buttons.addWidget(btn_cancel)
        buttons.addWidget(btn_add)
        layout.addLayout(buttons)

        self.search.textChanged.connect(self._filter_items)
        btn_cancel.clicked.connect(self.reject)
        btn_add.clicked.connect(self._accept_selected)
        self._filter_items("")

    def _filter_items(self, query: str) -> None:
        words = query.casefold().split()
        visible = 0
        for index in range(self.listw.count()):
            item = self.listw.item(index)
            matches = all(word in item.text().casefold() for word in words)
            item.setHidden(not matches)
            if matches:
                visible += 1
        self.count_label.setText(f"{visible} columns shown")

    def _accept_selected(self) -> None:
        self.selected_headers = [
            item.data(Qt.UserRole) for item in self.listw.selectedItems()
        ]
        if not self.selected_headers:
            QMessageBox.information(self, "SDRF columns", "Select at least one column.")
            return
        self.accept()


class SdrfMetadataDialog(QDialog):
    REQUIRED_COLUMNS = [
        ("RAW file", "file", "comment[data file]", False),
        ("source name", "source_name", "source name", False),
        ("assay name", "assay_name", "assay name", False),
        ("characteristics[organism]", "organism", "characteristics[organism]", False),
        ("characteristics[organism part]", "organism_part", "characteristics[organism part]", False),
        ("characteristics[biological replicate]", "biological_replicate", "characteristics[biological replicate]", False),
        ("comment[proteomics data acquisition method]", "acquisition_method", "comment[proteomics data acquisition method]", False),
        ("comment[label]", "label", "comment[label]", False),
        ("comment[cleavage agent details]", "cleavage_agent", "comment[cleavage agent details]", False),
        ("comment[fraction identifier]", "fraction_identifier", "comment[fraction identifier]", False),
        ("comment[technical replicate]", "technical_replicate", "comment[technical replicate]", False),
        ("comment[instrument] (auto / override)", "instrument_override", "comment[instrument]", False),
    ]

    def __init__(self, files: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("SDRF-Proteomics metadata")
        self.setMinimumSize(1050, 620)
        self.files = list(files)
        self.payload: dict = {}
        self.columns = list(self.REQUIRED_COLUMNS)
        self.setStyleSheet(
            """
            QDialog {
                background: #0f1115;
                color: #e9eef5;
            }
            QLabel {
                color: #e9eef5;
                font-size: 12px;
            }
            QLineEdit, QComboBox {
                background: #161a22;
                color: #e9eef5;
                border: 1px solid #364158;
                border-radius: 7px;
                padding: 6px 8px;
                selection-background-color: #7a001a;
                selection-color: #ffffff;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 1px solid #c21f45;
            }
            QLineEdit::placeholder {
                color: #8fa0b6;
            }
            QComboBox::drop-down {
                background: #202737;
                border: none;
                border-left: 1px solid #364158;
                border-top-right-radius: 7px;
                border-bottom-right-radius: 7px;
                width: 24px;
            }
            QComboBox QAbstractItemView {
                background: #161a22;
                color: #e9eef5;
                border: 1px solid #364158;
                selection-background-color: #7a001a;
                selection-color: #ffffff;
                outline: none;
            }
            QTableWidget, QListWidget {
                background: #121620;
                alternate-background-color: #171c27;
                color: #e9eef5;
                gridline-color: #30394c;
                border: 1px solid #364158;
                border-radius: 9px;
                selection-background-color: #7a001a;
                selection-color: #ffffff;
                outline: none;
            }
            QTableWidget::item, QListWidget::item {
                color: #e9eef5;
                padding: 6px;
                border: none;
            }
            QTableWidget::item:selected, QListWidget::item:selected {
                background: #7a001a;
                color: #ffffff;
            }
            QHeaderView::section {
                background: #202737;
                color: #ffffff;
                border: none;
                border-right: 1px solid #364158;
                border-bottom: 1px solid #48556f;
                padding: 8px 6px;
                font-weight: 700;
            }
            QTableCornerButton::section {
                background: #202737;
                border: none;
                border-right: 1px solid #364158;
                border-bottom: 1px solid #48556f;
            }
            QPushButton {
                background: #7a001a;
                color: #ffffff;
                border: 1px solid #a00023;
                border-radius: 10px;
                padding: 8px 13px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: #920020;
                border-color: #c21f45;
            }
            QPushButton:pressed {
                background: #600014;
            }
            QScrollBar:vertical, QScrollBar:horizontal {
                background: #0b0d12;
                border: none;
                margin: 0;
            }
            QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
                background: #48556f;
                border-radius: 5px;
                min-height: 24px;
                min-width: 24px;
            }
            QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
                background: #65738e;
            }
            QScrollBar::add-line, QScrollBar::sub-line,
            QScrollBar::add-page, QScrollBar::sub-page {
                background: transparent;
                border: none;
            }
            QToolTip {
                background: #202737;
                color: #ffffff;
                border: 1px solid #48556f;
                padding: 5px;
            }
            """
        )

        layout = QVBoxLayout(self)
        instructions = QLabel(
            "Only required MS-proteomics fields are shown initially. Complete them, then use "
            "Add column for any optional, recommended, or specialized SDRF field. "
            "MetaXtract fills the data filename, instrument, acquisition date, SDRF version, and template. "
            "Use DDA/DIA/PRM/SRM and Trypsin/Lys-C shorthand if desired.",
            self,
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        self.table = QTableWidget(0, len(self.columns), self)
        self.table.setHorizontalHeaderLabels([column[0] for column in self.columns])
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        self.table.setColumnWidth(0, 280)
        self.table.setColumnWidth(1, 140)
        self.table.setColumnWidth(2, 140)
        for file_path in self.files:
            self._append_row(self._defaults_for_file(file_path))
        layout.addWidget(self.table, 1)

        edit_buttons = QHBoxLayout()
        btn_add = QPushButton("Add sample row", self)
        btn_remove = QPushButton("Remove selected rows", self)
        btn_copy = QPushButton("Copy selected metadata to all rows", self)
        btn_add_column = QPushButton("Add column", self)
        btn_remove_column = QPushButton("Remove optional column", self)
        edit_buttons.addWidget(btn_add)
        edit_buttons.addWidget(btn_remove)
        edit_buttons.addWidget(btn_copy)
        edit_buttons.addWidget(btn_add_column)
        edit_buttons.addWidget(btn_remove_column)
        edit_buttons.addStretch(1)
        layout.addLayout(edit_buttons)

        dialog_buttons = QHBoxLayout()
        btn_cancel = QPushButton("Cancel", self)
        btn_export = QPushButton("Use this metadata", self)
        dialog_buttons.addStretch(1)
        dialog_buttons.addWidget(btn_cancel)
        dialog_buttons.addWidget(btn_export)
        layout.addLayout(dialog_buttons)

        btn_add.clicked.connect(self._add_sample_row)
        btn_remove.clicked.connect(self._remove_selected_rows)
        btn_copy.clicked.connect(self._copy_selected_metadata)
        btn_add_column.clicked.connect(self._add_columns)
        btn_remove_column.clicked.connect(self._remove_optional_column)
        btn_cancel.clicked.connect(self.reject)
        btn_export.clicked.connect(self._accept_metadata)

    def _defaults_for_file(self, file_path: str) -> dict:
        base = os.path.splitext(os.path.basename(file_path))[0]
        return {
            "file": file_path,
            "source_name": base,
            "assay_name": base,
            "organism": "",
            "organism_part": "not available",
            "biological_replicate": "1",
            "acquisition_method": "",
            "label": "",
            "cleavage_agent": "",
            "fraction_identifier": "1",
            "technical_replicate": "1",
            "instrument_override": "",
        }

    def _append_row(self, values: dict) -> None:
        row_index = self.table.rowCount()
        self.table.insertRow(row_index)
        for column_index, (_, key, _, _) in enumerate(self.columns):
            value = str(values.get(key, ""))
            if key == "file":
                combo = QComboBox(self.table)
                combo.addItems(self.files)
                combo.setCurrentText(value)
                self.table.setCellWidget(row_index, column_index, combo)
            else:
                self.table.setItem(row_index, column_index, QTableWidgetItem(value))

    def _value(self, row_index: int, column_index: int) -> str:
        widget = self.table.cellWidget(row_index, column_index)
        if isinstance(widget, QComboBox):
            return widget.currentText().strip()
        item = self.table.item(row_index, column_index)
        return item.text().strip() if item is not None else ""

    def _row_values(self, row_index: int) -> dict:
        return {
            key: self._value(row_index, column_index)
            for column_index, (_, key, _, _) in enumerate(self.columns)
        }

    def _add_sample_row(self) -> None:
        source_row = self.table.currentRow()
        if source_row >= 0:
            values = self._row_values(source_row)
            values["source_name"] = ""
            values["label"] = ""
            for _, key, header, removable in self.columns:
                if removable and header.startswith("factor value["):
                    values[key] = ""
        else:
            values = self._defaults_for_file(self.files[0])
        self._append_row(values)
        self.table.setCurrentCell(self.table.rowCount() - 1, 1)

    def _remove_selected_rows(self) -> None:
        selected_rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row_index in selected_rows:
            self.table.removeRow(row_index)

    def _copy_selected_metadata(self) -> None:
        source_row = self.table.currentRow()
        if source_row < 0:
            QMessageBox.information(self, "SDRF metadata", "Select a row to copy first.")
            return
        values = self._row_values(source_row)
        for row_index in range(self.table.rowCount()):
            if row_index == source_row:
                continue
            for column_index in range(3, len(self.columns)):
                key = self.columns[column_index][1]
                item = self.table.item(row_index, column_index)
                if item is None:
                    item = QTableWidgetItem()
                    self.table.setItem(row_index, column_index, item)
                item.setText(values.get(key, ""))

    def _add_columns(self) -> None:
        existing_headers = [column[2] for column in self.columns]
        picker = SdrfColumnPickerDialog(
            available_sdrf_columns(existing_headers),
            self,
        )
        if picker.exec() != QDialog.Accepted:
            return

        for selected_header in picker.selected_headers:
            header = selected_header
            if header == SdrfColumnPickerDialog.CUSTOM_FACTOR:
                factor_name, accepted = QInputDialog.getText(
                    self,
                    "Experimental factor",
                    "Factor name (for example: disease, treatment, time):",
                )
                factor_name = factor_name.strip().casefold()
                if not accepted:
                    continue
                if not factor_name or any(char in factor_name for char in "[]\t\r\n"):
                    QMessageBox.critical(
                        self,
                        "Invalid factor name",
                        "Enter a factor name without brackets, tabs, or line breaks.",
                    )
                    continue
                header = f"factor value[{factor_name}]"

            if header in {column[2] for column in self.columns}:
                QMessageBox.information(
                    self,
                    "SDRF columns",
                    f"{header} is already present.",
                )
                continue
            self._append_optional_column(header)

    def _append_optional_column(self, header: str) -> None:
        column_index = self.table.columnCount()
        self.table.insertColumn(column_index)
        self.columns.append((header, header, header, True))
        header_item = QTableWidgetItem(header)
        header_item.setToolTip(f"SDRF column: {header}")
        self.table.setHorizontalHeaderItem(column_index, header_item)
        self.table.setColumnWidth(column_index, max(180, min(360, len(header) * 8)))
        for row_index in range(self.table.rowCount()):
            self.table.setItem(row_index, column_index, QTableWidgetItem(""))
        self.table.setCurrentCell(0, column_index)

    def _remove_optional_column(self) -> None:
        column_index = self.table.currentColumn()
        if column_index < 0:
            QMessageBox.information(self, "SDRF columns", "Select a column first.")
            return
        label, _, header, removable = self.columns[column_index]
        if not removable:
            QMessageBox.information(
                self,
                "SDRF columns",
                f"{label} is a required column and cannot be removed.",
            )
            return
        self.table.removeColumn(column_index)
        self.columns.pop(column_index)

    def _accept_metadata(self) -> None:
        rows = [self._row_values(row_index) for row_index in range(self.table.rowCount())]
        extra_columns = [header for _, _, header, removable in self.columns if removable]
        errors = validate_sdrf_metadata(
            rows,
            self.files,
            extra_columns=extra_columns,
        )
        if errors:
            shown = errors[:12]
            if len(errors) > len(shown):
                shown.append(f"...and {len(errors) - len(shown)} more errors")
            QMessageBox.critical(self, "Invalid SDRF metadata", "\n".join(shown))
            return
        self.payload = {
            "factor_name": "",
            "extra_columns": extra_columns,
            "rows": rows,
        }
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
        self.cb_ms2_technical_details = QCheckBox("Export MS2 technical details", self)
        self.cb_ms1_technical_details = QCheckBox("Export MS1 technical details", self)
        self.cb_sdrf = QCheckBox("Export SDRF-Proteomics metadata (.sdrf.tsv)", self)
        #self.cb_hdf5 = QCheckBox("AnnData (HDF5 .h5ad) [MS2 only]", self)
        
        self.cb_multi_cmp = QCheckBox("Multi-sample comparison (choose 2 or more samples)", self)
        self.cb_multi_cmp.setEnabled(True)
        opt.addWidget(self.cb_multi_cmp)
        opt.addWidget(self.cb_file_details)
        opt.addWidget(self.cb_ms_method)
        opt.addWidget(self.cb_lc_method)
        opt.addWidget(self.cb_plotly)
        opt.addWidget(self.cb_ms2_peaklist)
        opt.addWidget(self.cb_ms1_peaklist)
        opt.addWidget(self.cb_ms2_technical_details)
        opt.addWidget(self.cb_ms1_technical_details)
        opt.addWidget(self.cb_sdrf)
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
            "Total Ion Current", "Total Number of Peaks", "thermo_Number of Channels", "Sampling Frequency",
            "Collision Energy", "Scan Start Time (min)", "Scan Window m/z Range", "Selected Ion Intensity",
            "Filter String", "Scan Mode", "thermo_AGC", "thermo_Micro Scan Count", "Ion Injection Time (ms)",
            "thermo_Elapsed Scan Time (sec)", "Dissociation Method", "Mass Analyzer Type", "Detector Type",
            "Base Peak m/z", "thermo_Average Scan by Inst", "thermo_Orbitrap Resolution", "thermo_API Process Delay",
            "thermo_Dependency Type", "thermo_Multi Inject Info", "Base Peak Intensity", "thermo_Master Scan Number",
            "Experimental Precursor Monoisotopic m/z", "Charge State", "Normalized Collision Energy (%)", "Collision Energy (eV)",
            "Isolation Window Width (m/z)", "thermo_Access ID", "thermo_Conversion Parameter I", "thermo_Conversion Parameter A",
            "thermo_Conversion Parameter B", "thermo_Conversion Parameter C", "thermo_Conversion Parameter D",
            "thermo_Conversion Parameter E", "thermo_Temperature Comp. (ppm)", "thermo_RF Comp. (ppm)",
            "thermo_Space Charge Comp. (ppm)", "thermo_Resolution Comp. (ppm)", "thermo_Number of LM Found",
            "thermo_LM Correction (ppm)", "thermo_RawOvFtT", "thermo_Injection t0", "thermo_Reagent Ion Injection Time (ms)",
            "thermo_FAIMS Voltage On", "FAIMS Compensation Voltage",
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
            "Scan Start Time (min)", "Base Peak Intensity", "Base Peak m/z",
            "Scan Mode", "thermo_Multi Inject Info", "thermo_Multiple Injection",
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

    def _shutdown_thread(self, wait: bool, force: bool = False, timeout_ms: int = 5000) -> bool:
        t = self._thread
        w = self._worker

        if w is not None:
            try:
                w.stop()
            except Exception:
                pass

        if t is not None:
            try:
                t.requestInterruption()
            except Exception:
                pass
            try:
                t.quit()
            except Exception:
                pass

            if wait and QThread.currentThread() != t:
                if force:
                    t.wait(timeout_ms)
                else:
                    t.wait()

            if force and t.isRunning():
                try:
                    t.terminate()
                    t.wait(1000)
                except Exception:
                    pass

            if force and t.isRunning():
                os._exit(0)

            if t.isRunning():
                return False

            t.deleteLater()

        self._thread = None
        self._worker = None
        return True

    def stop_processing(self):
        if self._worker is not None:
            try:
                self._worker.stop()
            except Exception:
                pass
        self.btn_stop.setEnabled(False)

    def request_shutdown(self, wait: bool = True, force: bool = False) -> bool:
        if self._thread is not None and self._thread.isRunning():
            self.stop_processing()
            return self._shutdown_thread(wait=wait, force=force)
        return True

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
        ms2_technical_details_export = self.cb_ms2_technical_details.isChecked()
        ms1_technical_details_export = self.cb_ms1_technical_details.isChecked()
        sdrf_enabled = self.cb_sdrf.isChecked()
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
                dlg = ComparisonSamplePickerDialog(list(selected_files), self)
                if dlg.exec() != QDialog.Accepted:
                    return
                cmp_files = dlg.selected

        sdrf_payload = None
        if sdrf_enabled:
            processed_files = cmp_files if (multi_cmp and cmp_files) else selected_files
            dlg = SdrfMetadataDialog(list(processed_files), self)
            if dlg.exec() != QDialog.Accepted:
                return
            sdrf_payload = dlg.payload

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
            sdrf_payload=sdrf_payload,
            hdf5_export=hdf5_export, 
            ms2_peaklist_export=ms2_peaklist_export,
            ms1_peaklist_export=ms1_peaklist_export,
            ms2_technical_details_export=ms2_technical_details_export,
            ms1_technical_details_export=ms1_technical_details_export,
        )
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress_bar.setValue, Qt.QueuedConnection)
        self._worker.log.connect(self.log_window.append_log, Qt.QueuedConnection)
        self._worker.finished.connect(self._on_done, Qt.QueuedConnection)
        self._worker.failed.connect(self._on_fail, Qt.QueuedConnection)
        self._thread.finished.connect(self._worker.deleteLater)

        self._thread.start()

    def closeEvent(self, event):
        self.request_shutdown(wait=True, force=True)
        event.accept()


def install_shutdown_handlers(app: QApplication, window: MetaXtract_GUI) -> None:
    timer = QTimer(app)
    timer.start(200)
    timer.timeout.connect(lambda: None)
    app._metaxtract_signal_timer = timer

    shutting_down = False

    def handle_signal(signum, _frame):
        nonlocal shutting_down
        if shutting_down:
            os._exit(128 + int(signum))
        shutting_down = True
        window.request_shutdown(wait=True, force=True)
        app.quit()

    handled_signals = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):
        handled_signals.append(signal.SIGBREAK)

    for sig in handled_signals:
        try:
            signal.signal(sig, handle_signal)
        except (OSError, ValueError):
            pass

    app.aboutToQuit.connect(lambda: window.request_shutdown(wait=True, force=True))


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    w = MetaXtract_GUI()
    install_shutdown_handlers(app, w)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
