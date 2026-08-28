from __future__ import annotations

import os
import signal
import sys
import threading
import yaml
from datetime import datetime
import csv, json
from pathlib import Path

from raw_parser import MetaXtract
from anndata_export import export_ms2_to_h5ad
from plotly_visualizer import (
    PlotlyMS1Visualizer,
    PlotlyMS2Visualizer,
    write_comparison_html_multi,
    write_comparison_html_with_boxplots,
)
from runtime_metrics import FileUsageMonitor, format_bytes, format_file_usage


def _cancel_requested(should_stop=None) -> bool:
    if should_stop is None:
        return False
    try:
        return bool(should_stop())
    except Exception:
        return False


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

DEFAULT_MS1_COLUMNS = [
    "Ion Injection Time (ms)",
    "Total Number of Peaks",
    "Total Ion Current",
    "Scan Start Time (min)",
    "Base Peak Intensity",
    "Base Peak m/z",
    "Scan Mode",
    "thermo_Multi Inject Info",
    "thermo_Multiple Injection",
]

DEFAULT_MS2_COLUMNS = [
    "Total Ion Current",
    "Total Number of Peaks",
    "thermo_Number of Channels",
    "Sampling Frequency",
    "Collision Energy",
    "Scan Start Time (min)",
    "Scan Window m/z Range",
    "Selected Ion Intensity",
    "Filter String",
    "Scan Mode",
    "thermo_AGC",
    "thermo_Micro Scan Count",
    "Ion Injection Time (ms)",
    "thermo_Elapsed Scan Time (sec)",
    "Dissociation Method",
    "Mass Analyzer Type",
    "Detector Type",
    "Base Peak m/z",
    "thermo_Average Scan by Inst",
    "thermo_Orbitrap Resolution",
    "thermo_API Process Delay",
    "thermo_Dependency Type",
    "thermo_Multi Inject Info",
    "Base Peak Intensity",
    "thermo_Master Scan Number",
    "Experimental Precursor Monoisotopic m/z",
    "Charge State",
    "Normalized Collision Energy (%)",
    "Collision Energy (eV)",
    "Isolation Window Width (m/z)",
    "thermo_Access ID",
    "thermo_Conversion Parameter I",
    "thermo_Conversion Parameter A",
    "thermo_Conversion Parameter B",
    "thermo_Conversion Parameter C",
    "thermo_Conversion Parameter D",
    "thermo_Conversion Parameter E",
    "thermo_Temperature Comp. (ppm)",
    "thermo_RF Comp. (ppm)",
    "thermo_Space Charge Comp. (ppm)",
    "thermo_Resolution Comp. (ppm)",
    "thermo_Number of LM Found",
    "thermo_LM Correction (ppm)",
    "thermo_RawOvFtT",
    "thermo_Injection t0",
    "thermo_Reagent Ion Injection Time (ms)",
    "thermo_FAIMS Voltage On",
    "FAIMS Compensation Voltage",
]


def trailer_value(trailer_data, output_label: str):
    if not trailer_data:
        return None
    for key in (output_label, *COLUMN_SOURCE_ALIASES.get(output_label, ())):
        value = trailer_data.get(key, None)
        if value not in (None, ""):
            return value
    return None


def format_scan_window_mz_range(raw_parser, scan_number: int):
    n = raw_parser.GetNumberOfMassRangesFromScanNumber(scan_number) or 0
    ranges = []
    for i in range(n):
        lo, hi = raw_parser.GetMassRangeFromScanNumber(scan_number, i)
        if lo is not None and hi is not None:
            ranges.append(f"{lo}-{hi}")
    return "; ".join(ranges) if ranges else "N/A"

def remove_empty_lines(input_file):
    with open(input_file, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    non_empty_lines = [line for line in lines if line.strip()]
    with open(input_file, "w", encoding="utf-8", errors="replace") as f:
        f.writelines(non_empty_lines)


def load_yml_config(config_path):
    if not config_path:
        return {}
    if not os.path.exists(config_path):
        print(f"[ERROR] Config file '{config_path}' not found.")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8", errors="replace") as f:
        cfg = yaml.safe_load(f)
    return cfg or {}


def _cfg_get(d, path, default=None):
    cur = d
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _selected_columns(block: dict) -> list[str]:

    if not isinstance(block, dict):
        return []
    cols = block.get("columns", {}) or {}
    if not isinstance(cols, dict):
        cols = {}
    if bool(block.get("select_all", False)):
        return list(cols.keys())
    return [k for k, v in cols.items() if bool(v)]


def _pick_cmp_inputs(all_inputs: list[str], samples_1based: list[int]) -> list[str]:
    if not isinstance(samples_1based, list) or len(samples_1based) < 2:
        raise ValueError(
            "multi_comparison.samples must have at least 2 indices (1-based), e.g. [1, 3, 4]."
        )
    out = []
    for idx in samples_1based:
        if not isinstance(idx, int) or isinstance(idx, bool):
            raise ValueError("multi_comparison.samples must be integers.")
        if idx < 1 or idx > len(all_inputs):
            raise ValueError(f"multi_comparison index {idx} out of range for {len(all_inputs)} inputs.")
        out.append(all_inputs[idx - 1])
    if len(set(samples_1based)) != len(samples_1based) or len(set(out)) != len(out):
        raise ValueError("multi_comparison.samples must point to different files.")
    return out


def extract_scan_header_to_csv(
    raw_parser,
    output_dir,
    selected_options,
    single_file_name,
    graphical_representation=False,
    should_stop=None,
):
    # MS2
    try:
        csv_file_path = f"{output_dir}/{single_file_name}_scan_header_ms2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        plotly_vis = PlotlyMS2Visualizer(single_file_name, output_dir) if graphical_representation else None

        option_functions = {
            "Total Ion Current": lambda sn: raw_parser.GetTICForScanNumber(sn),
            "Total Number of Peaks": lambda sn: raw_parser.GetNumPeaksForScanNumber(sn),
            "thermo_Number of Channels": lambda sn: raw_parser.GetNumChannelsForScanNumber(sn),
            "Number of Channels": lambda sn: raw_parser.GetNumChannelsForScanNumber(sn),
            "Sampling Frequency": lambda sn: raw_parser.GetFrequencyForScanNumber(sn),
            "Frequency": lambda sn: raw_parser.GetFrequencyForScanNumber(sn),
            "Collision Energy": lambda sn: raw_parser.GetCollisionEnergyForScanNumber(sn),
            "Scan Start Time (min)": lambda sn: raw_parser.GetRetentionTimeFromScanNumber(sn),
            "Retention Time (min)": lambda sn: raw_parser.GetRetentionTimeFromScanNumber(sn),
            "Retention Time (s)": lambda sn: raw_parser.GetRetentionTimeFromScanNumber(sn),
            "Scan Window m/z Range": lambda sn: format_scan_window_mz_range(raw_parser, sn),
            "Mass Ranges": lambda sn: format_scan_window_mz_range(raw_parser, sn),
            "Scan Mode": lambda sn: raw_parser.GetScanModeFromScanNumber(sn),
            "Filter String": lambda sn: raw_parser.GetScanEventStringForScanNumber(sn),
            "Scan Description": lambda sn: raw_parser.GetScanEventStringForScanNumber(sn),
            "Selected Ion Intensity": lambda sn: raw_parser.GetPrecursorIntensityFromScanNumber(sn),
            "Precursor Intensity": lambda sn: raw_parser.GetPrecursorIntensityFromScanNumber(sn),
            "Base Peak m/z": lambda sn: raw_parser.GetBasePeakForScanNumber(sn)[0],
            "Base Peak Mass": lambda sn: raw_parser.GetBasePeakForScanNumber(sn)[0],
            "Base Peak Intensity": lambda sn: raw_parser.GetBasePeakForScanNumber(sn)[1],
            "Dissociation Method": lambda sn: raw_parser.GetActivationTypeForScanNumber(sn),
            "Activation Type": lambda sn: raw_parser.GetActivationTypeForScanNumber(sn),
            "Mass Analyzer Type": lambda sn: raw_parser.GetMassAnalyzerTypeFromScanNumber(sn),
            "Detector Type": lambda sn: raw_parser.GetDetectorTypeFromScanNumber(sn),
        }

        with open(csv_file_path, mode="w", newline="", encoding="utf-8", errors="replace") as csv_file:
            csv_writer = csv.writer(csv_file)
            csv_writer.writerow(["Scan Number", "RAW File"] + selected_options)

            num_scans = raw_parser.NumSpectra
            for scan_number in range(1, num_scans + 1):
                if _cancel_requested(should_stop):
                    print("[INFO] MS2 scan header extraction cancelled.")
                    break
                scan_ms_order = int(raw_parser.GetMSOrder(scan_number))
                if scan_ms_order != 2:
                    continue
                if not raw_parser.CheckMS2Centroid(scan_number):
                    continue

                row = [scan_number, single_file_name]
                trailer_data = raw_parser.GetTrailerExtraInformaionEdited(scan_number) or {}

                for option in selected_options:
                    value = trailer_value(trailer_data, option)
                    if value is None:
                        value = option_functions.get(option, lambda sn: "N/A")(scan_number)
                    row.append(value)

                csv_writer.writerow(row)

                if graphical_representation and plotly_vis is not None:
                    plotly_vis.ms2_scans.append(scan_number)
                    plotly_vis.ms2_data["Scan Start Time (min)"].append(raw_parser.GetRetentionTimeFromScanNumber(scan_number))
                    plotly_vis.ms2_data["Elapsed Scan Time (sec)"].append(raw_parser.GetElaspedScanTimeFromScanNumber(scan_number))
                    plotly_vis.ms2_data["Total Ion Current"].append(raw_parser.GetTICForScanNumber(scan_number))
                    plotly_vis.ms2_data["Total Number of Peaks"].append(raw_parser.GetNumPeaksForScanNumber(scan_number))
                    plotly_vis.ms2_data["Selected Ion Intensity"].append(raw_parser.GetPrecursorIntensityFromScanNumber(scan_number))
                    plotly_vis.ms2_data["Charge State"].append(raw_parser.GetMS2ChargeFromScanNumber(scan_number))
                    plotly_vis.ms2_data["Ion Injection Time (ms)"].append(raw_parser.GetIonInjectionTimeFromScanNumber(scan_number))
                    plotly_vis.ms2_data.setdefault("Base Peak Intensity", []).append(raw_parser.GetBasePeakForScanNumber(scan_number)[1])

        if graphical_representation and plotly_vis is not None:
            plotly_vis.write_html_report()

        print(f"[INFO] Scan header information (MS2) saved to {csv_file_path}")
        return plotly_vis
    except Exception as e:
        print(f"[ERROR] Failed to generate MS2 CSV: {e}")
        return None


def extract_scan_header_to_csv_ms1(
    raw_parser,
    output_dir,
    selected_options,
    single_file_name,
    graphical_representation=False,
    should_stop=None,
):
    # MS1
    try:
        csv_file_path = f"{output_dir}/{single_file_name}_scan_header_ms1_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        plotly_vis = PlotlyMS1Visualizer(single_file_name, output_dir) if graphical_representation else None

        option_functions = {
            "Total Ion Current": lambda sn: raw_parser.GetTICForScanNumber(sn),
            "Total Number of Peaks": lambda sn: raw_parser.GetNumPeaksForScanNumber(sn),
            "Scan Start Time (min)": lambda sn: raw_parser.GetRetentionTimeFromScanNumber(sn),
            "Retention Time (min)": lambda sn: raw_parser.GetRetentionTimeFromScanNumber(sn),
            "Retention Time (s)": lambda sn: raw_parser.GetRetentionTimeFromScanNumber(sn),
            "Base Peak m/z": lambda sn: raw_parser.GetBasePeakForScanNumber(sn)[0],
            "Base Peak Mass": lambda sn: raw_parser.GetBasePeakForScanNumber(sn)[0],
            "Base Peak Intensity": lambda sn: raw_parser.GetBasePeakForScanNumber(sn)[1],
            "Ion Injection Time (ms)": lambda sn: raw_parser.GetIonInjectionTimeFromScanNumber(sn),
            "Scan Mode": lambda sn: raw_parser.GetScanModeFromScanNumber(sn),
        }

        with open(csv_file_path, mode="w", newline="", encoding="utf-8", errors="replace") as csv_file:
            csv_writer = csv.writer(csv_file)
            csv_writer.writerow(["Scan Number", "RAW File"] + selected_options)

            num_scans = raw_parser.NumSpectra
            for scan_number in range(1, num_scans + 1):
                if _cancel_requested(should_stop):
                    print("[INFO] MS1 scan header extraction cancelled.")
                    break
                scan_ms_order = int(raw_parser.GetMSOrder(scan_number))
                if raw_parser.CheckMS2Centroid(scan_number) or scan_ms_order == 2:
                    continue

                row = [scan_number, single_file_name]
                trailer_data = raw_parser.GetTrailerExtraInformaionEdited(scan_number) or {}

                for option in selected_options:
                    value = trailer_value(trailer_data, option)
                    if value is None:
                        value = option_functions.get(option, lambda sn: "N/A")(scan_number)
                    row.append(value)

                csv_writer.writerow(row)

                if graphical_representation and plotly_vis is not None:
                    plotly_vis.ms1_scans.append(scan_number)
                    plotly_vis.ms1_data["Scan Start Time (min)"].append(raw_parser.GetRetentionTimeFromScanNumber(scan_number))
                    plotly_vis.ms1_data["Elapsed Scan Time (sec)"].append(raw_parser.GetElaspedScanTimeFromScanNumber(scan_number))
                    plotly_vis.ms1_data["Total Ion Current"].append(raw_parser.GetTICForScanNumber(scan_number))
                    plotly_vis.ms1_data["Total Number of Peaks"].append(raw_parser.GetNumPeaksForScanNumber(scan_number))
                    plotly_vis.ms1_data["Base Peak Intensity"].append(raw_parser.GetBasePeakForScanNumber(scan_number)[1])
                    plotly_vis.ms1_data["Base Peak m/z"].append(raw_parser.GetBasePeakForScanNumber(scan_number)[0])
                    plotly_vis.ms1_data["Ion Injection Time (ms)"].append(raw_parser.GetIonInjectionTimeFromScanNumber(scan_number))

        if graphical_representation and plotly_vis is not None:
            plotly_vis.write_html_report()

        print(f"[INFO] Scan header information (MS1) saved to {csv_file_path}")
        return plotly_vis
    except Exception as e:
        print(f"[ERROR] Failed to generate MS1 CSV: {e}")
        return None

def extract_technical_details_to_csv(raw_parser, output_dir, single_file_name, ms_order: int, should_stop=None):
    try:
        csv_file_path = (
            f"{output_dir}/{single_file_name}_technical_details_ms{ms_order}_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )
        rows = []
        columns = ["Scan Number", "RAW File"]
        seen_columns = set(columns)

        num_scans = raw_parser.NumSpectra
        for scan_number in range(1, num_scans + 1):
            if _cancel_requested(should_stop):
                print(f"[INFO] MS{ms_order} technical details extraction cancelled.")
                break
            scan_ms_order = int(raw_parser.GetMSOrder(scan_number))
            if scan_ms_order != ms_order:
                continue

            info = raw_parser.GetMoreMSInfos(scan_number) or {}
            if not isinstance(info, dict):
                info = {}

            row = {"Scan Number": scan_number, "RAW File": single_file_name}
            for key, value in info.items():
                if key in ("Scan Number", "RAW File"):
                    continue
                if key not in seen_columns:
                    seen_columns.add(key)
                    columns.append(key)
                row[key] = value
            rows.append(row)

        with open(csv_file_path, mode="w", newline="", encoding="utf-8", errors="replace") as csv_file:
            csv_writer = csv.writer(csv_file)
            csv_writer.writerow(columns)
            for row in rows:
                csv_writer.writerow([_tsv_safe(row.get(col, "N/A")) for col in columns])

        print(f"[INFO] Technical details (MS{ms_order}) saved to {csv_file_path}")
    except Exception as e:
        print(f"[ERROR] Failed to generate MS{ms_order} technical details CSV: {e}")

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

def run_cli(args):
    stop_event = threading.Event()
    file_usage_monitor = None
    file_usage_path = None

    def start_file_usage(input_file):
        nonlocal file_usage_monitor, file_usage_path
        file_usage_path = input_file
        file_usage_monitor = FileUsageMonitor().start()
        print(
            f"[METRICS] Started: {input_file} | "
            f"Memory RSS: {format_bytes(file_usage_monitor.start_rss_bytes)}"
        )

    def finish_file_usage(status):
        nonlocal file_usage_monitor, file_usage_path
        monitor = file_usage_monitor
        input_file = file_usage_path
        file_usage_monitor = None
        file_usage_path = None
        if monitor is None or input_file is None:
            return
        print(f"[METRICS] {status}: {input_file} | {format_file_usage(monitor.stop())}")

    def request_stop(signum, _frame):
        if stop_event.is_set():
            raise KeyboardInterrupt
        stop_event.set()
        print(f"\n[INFO] Received signal {signum}; stopping after the current operation...")

    handled_signals = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):
        handled_signals.append(signal.SIGBREAK)

    for sig in handled_signals:
        try:
            signal.signal(sig, request_stop)
        except (OSError, ValueError):
            pass

    cfg = load_yml_config(args.config) if getattr(args, "config", None) else {}

    cfg_inputs = _cfg_get(cfg, ["io", "input"], []) or []
    cfg_outdir = _cfg_get(cfg, ["io", "output_dir"], None)

    inputs = list(getattr(args, "input", None) or cfg_inputs)
    outdir = getattr(args, "output_dir", None) or cfg_outdir

    if not inputs:
        print("[ERROR] No input files. Set io.input in config.yml or pass --input ...")
        sys.exit(1)
    if not outdir:
        print("[ERROR] No output directory. Set io.output_dir in config.yml or pass --output-dir ...")
        sys.exit(1)

    os.makedirs(outdir, exist_ok=True)

    cfg_outputs = _cfg_get(cfg, ["outputs"], {}) or {}
    hdf5_export = bool(getattr(args, "hdf5_export", False) or cfg_outputs.get("hdf5_export", False))
    file_based_details = bool(getattr(args, "file_based_details", False) or cfg_outputs.get("file_based_details", False))
    ms_method = bool(getattr(args, "ms_method", False) or cfg_outputs.get("ms_method", False))
    lc_method = bool(getattr(args, "lc_method", False) or cfg_outputs.get("lc_method", False))
    ms2_peaklist_export = bool(getattr(args, "ms2_peaklist_export", False) or cfg_outputs.get("ms2_peaklist_export", False))
    ms1_peaklist_export = bool(getattr(args, "ms1_peaklist_export", False) or cfg_outputs.get("ms1_peaklist_export", False))
    ms2_technical_details_export = bool(
        getattr(args, "ms2_technical_details_export", False) or cfg_outputs.get("ms2_technical_details_export", False)
    )
    ms1_technical_details_export = bool(
        getattr(args, "ms1_technical_details_export", False) or cfg_outputs.get("ms1_technical_details_export", False)
    )

    cfg_vis = _cfg_get(cfg, ["visualisation"], {}) or {}
    graphical_representation = bool(getattr(args, "graphical_representation", False) or cfg_vis.get("enabled", False))
    fmt = (cfg_vis.get("format", "html") or "html").lower().strip()
    if fmt != "html":
        print("[ERROR] visualisation.format must be 'html' (only supported format).")
        sys.exit(1)

    ms1_block = _cfg_get(cfg, ["scan_header", "MS1"], {}) or {}
    ms2_block = _cfg_get(cfg, ["scan_header", "MS2"], {}) or {}

    if getattr(args, "complete_ms1", False):
        columns = ms1_block.get("columns", {}) if isinstance(ms1_block, dict) else {}
        if not columns:
            columns = {column: True for column in DEFAULT_MS1_COLUMNS}
        ms1_block = {"select_all": True, "columns": columns}
    if getattr(args, "complete_ms2", False):
        columns = ms2_block.get("columns", {}) if isinstance(ms2_block, dict) else {}
        if not columns:
            columns = {column: True for column in DEFAULT_MS2_COLUMNS}
        ms2_block = {"select_all": True, "columns": columns}

    selected_ms1_options = _selected_columns(ms1_block)
    selected_ms2_options = _selected_columns(ms2_block)

    cfg_mc = _cfg_get(cfg, ["multi_comparison"], {}) or {}
    multi_cmp = bool(cfg_mc.get("enabled", False))
    cmp_inputs = None
    if multi_cmp:
        try:
            cmp_inputs = _pick_cmp_inputs(inputs, cfg_mc.get("samples", []))
        except Exception as e:
            print(f"[ERROR] {e}")
            sys.exit(1)

    proc_inputs = cmp_inputs if (multi_cmp and cmp_inputs) else inputs

    all_ms1_tic, all_ms1_bpi, all_ms1_tnp = [], [], []
    all_ms2_tic, all_ms2_tnp, all_ms2_prec = [], [], []
    ms1_box_tic, ms1_box_bpi, ms1_box_tnp = {}, {}, {}
    ms2_box_tic, ms2_box_bpi, ms2_box_tnp = {}, {}, {}


    for input_file in proc_inputs:
        if stop_event.is_set():
            break
        if not os.path.exists(input_file):
            print(f"[ERROR] Input file '{input_file}' does not exist.")
            continue

        print(f"[INFO] Processing: {input_file}")
        start_file_usage(input_file)
        try:
            raw_parser = MetaXtract(input_file)
        except Exception:
            finish_file_usage("Failed")
            raise

        base = os.path.splitext(os.path.basename(input_file))[0]
        sample_out = os.path.join(outdir, base)
        os.makedirs(sample_out, exist_ok=True)
        
        info_tsv_path = None
        if file_based_details:
            file_details_path = os.path.join(sample_out, f"{base}_info.tsv")
            write_info_tsv(raw_parser, file_details_path, should_stop=stop_event.is_set)
            info_tsv_path = file_details_path
            print(f"[INFO] Wrote: {file_details_path}")

        if stop_event.is_set():
            raw_parser.CloseRAWFile()
            break

        if ms_method:
            ms_method_path = os.path.join(sample_out, f"{base}_MS_method.txt")
            with open(ms_method_path, "w", encoding="utf-8", errors="replace") as f:
                f.write(raw_parser.GetMSMethod() or "")
            remove_empty_lines(ms_method_path)

        if stop_event.is_set():
            raw_parser.CloseRAWFile()
            break

        if lc_method:
            lc_method_path = os.path.join(sample_out, f"{base}_LC_method.txt")
            with open(lc_method_path, "w", encoding="utf-8", errors="replace") as f:
                f.write(raw_parser.GetLCMethod() or "")
            remove_empty_lines(lc_method_path)

        if stop_event.is_set():
            raw_parser.CloseRAWFile()
            break

        ms1_vis = None
        ms2_vis = None

        if selected_ms1_options:
            ms1_vis = extract_scan_header_to_csv_ms1(
                raw_parser,
                sample_out,
                selected_ms1_options,
                base,
                graphical_representation,
                should_stop=stop_event.is_set,
            )

        if stop_event.is_set():
            raw_parser.CloseRAWFile()
            break

        if selected_ms2_options:
            ms2_vis = extract_scan_header_to_csv(
                raw_parser,
                sample_out,
                selected_ms2_options,
                base,
                graphical_representation,
                should_stop=stop_event.is_set,
            )

        if stop_event.is_set():
            raw_parser.CloseRAWFile()
            break

        if ms2_technical_details_export:
            extract_technical_details_to_csv(raw_parser, sample_out, base, 2, should_stop=stop_event.is_set)

        if stop_event.is_set():
            raw_parser.CloseRAWFile()
            break

        if ms1_technical_details_export:
            extract_technical_details_to_csv(raw_parser, sample_out, base, 1, should_stop=stop_event.is_set)
            
        if stop_event.is_set():
            raw_parser.CloseRAWFile()
            break

        if hdf5_export:
            out_h5ad = Path(sample_out) / f"{base}_MS2.h5ad"
            try:
                export_ms2_to_h5ad(raw_parser, out_h5ad, info_tsv_path=info_tsv_path, should_stop=stop_event.is_set)
                print(f"[INFO] Wrote: {out_h5ad}")
            except InterruptedError:
                stop_event.set()
        if stop_event.is_set():
            raw_parser.CloseRAWFile()
            break
        if ms2_peaklist_export:
            out_pq = Path(sample_out) / f"{base}_ms2_peaklist.parquet"
            raw_parser.ExportPeakList(str(out_pq), should_stop=stop_event.is_set)
            print(f"[INFO] Wrote: {out_pq}")
        if stop_event.is_set():
            raw_parser.CloseRAWFile()
            break
        if ms1_peaklist_export:
            out_pq = Path(sample_out) / f"{base}_ms1_peaklist.parquet"
            raw_parser.ExportMS1PeakList(str(out_pq), should_stop=stop_event.is_set)
            print(f"[INFO] Wrote: {out_pq}")
        if stop_event.is_set():
            raw_parser.CloseRAWFile()
            break
        if graphical_representation and ms1_vis is not None:
            ms1_box_tic[base] = list(ms1_vis.ms1_data.get("Total Ion Current", []))
            ms1_box_bpi[base] = list(ms1_vis.ms1_data.get("Base Peak Intensity", []))
            ms1_box_tnp[base] = list(ms1_vis.ms1_data.get("Total Number of Peaks", []))

        if graphical_representation and ms2_vis is not None:
            ms2_box_tic[base] = list(ms2_vis.ms2_data.get("Total Ion Current", []))
            ms2_box_tnp[base] = list(ms2_vis.ms2_data.get("Total Number of Peaks", []))
            ms2_box_bpi[base] = list(ms2_vis.ms2_data.get("Base Peak Intensity", []))


        if graphical_representation and ms1_vis is not None:
            x, y = ms1_vis.tic_trace()
            all_ms1_tic.append((base, x, y))
            if hasattr(ms1_vis, "bpi_trace"):
                x, y = ms1_vis.bpi_trace()
                all_ms1_bpi.append((base, x, y))
            if hasattr(ms1_vis, "tnp_trace"):
                x, y = ms1_vis.tnp_trace()
                all_ms1_tnp.append((base, x, y))

        if graphical_representation and ms2_vis is not None:
            x, y = ms2_vis.tic_trace()
            all_ms2_tic.append((base, x, y))
            if hasattr(ms2_vis, "tnp_trace"):
                x, y = ms2_vis.tnp_trace()
                all_ms2_tnp.append((base, x, y))
            if hasattr(ms2_vis, "prec_trace"):
                x, y = ms2_vis.prec_trace()
                all_ms2_prec.append((base, x, y))

        raw_parser.CloseRAWFile()
        print(f"[INFO] Done: {input_file}")
        finish_file_usage("Finished")
        print()

    if stop_event.is_set():
        finish_file_usage("Stopped")
        print("[INFO] Processing stopped.")

    if not stop_event.is_set() and graphical_representation and len(all_ms1_tic) >= 2:
        out = Path(outdir) / "MS1_compare.html"
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
        print(f"[VIS] MS1 comparison: {out}")


    if not stop_event.is_set() and graphical_representation and len(all_ms2_tic) >= 2:
        out = Path(outdir) / "MS2_compare.html"
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
        print(f"[VIS] MS2 comparison: {out}")
