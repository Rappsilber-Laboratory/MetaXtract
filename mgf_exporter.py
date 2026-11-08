from __future__ import annotations

import csv
import hashlib
import math
import os
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


ACQUISITION_MODES = ("recorded", "dda", "dia")
PEAK_MODES = ("centroid", "recorded")
METADATA_COLUMNS = (
    "source_file", "scan", "title", "acquisition", "status", "reason",
    "pepmass_mz", "pepmass_source", "charge", "retention_time_seconds",
    "monoisotopic_mz", "isolation_target_mz", "isolation_width_mz",
    "isolation_offset_mz", "polarity", "centroid_source", "peaks_written",
    "invalid_peaks_removed",
    "peak_mode", "peak_source",
    "precursor_intensity_source", "precursor_ms1_scan",
)


def finite_number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _positive(value):
    value = finite_number(value)
    return value if value is not None and value > 0 else None


def _text(value):
    return str(value).replace("\r", " ").replace("\n", " ").replace("\t", " ")


def plan_mgf_outputs(inputs, output_dir):
    """Keep the usual sample folders, disambiguating equal basenames."""
    paths = list(dict.fromkeys(str(Path(p).resolve()) for p in inputs))
    counts = Counter(Path(p).stem.casefold() for p in paths)
    result = {}
    for path in paths:
        stem = Path(path).stem
        if counts[stem.casefold()] > 1:
            stem += "_" + hashlib.sha256(path.encode("utf-8")).hexdigest()[:12]
        result[path] = Path(output_dir) / stem / f"{stem}.mgf"
    return result


@dataclass
class MGFExportSummary:
    output: Path
    metadata: Path
    scans_examined: int = 0
    spectra_written: int = 0
    skipped: Counter = field(default_factory=Counter)
    invalid_peaks_removed: int = 0
    isolation_target_spectra: int = 0

    def describe(self):
        reasons = ", ".join(f"{key}: {value}" for key, value in self.skipped.items()) or "none"
        return (
            f"MGF: {self.spectra_written} spectra written; "
            f"{sum(self.skipped.values())} skipped ({reasons}); "
            f"{self.invalid_peaks_removed} invalid peaks removed; "
            f"{self.isolation_target_spectra} spectra use isolation-target m/z. "
            f"Output: {self.output}; metadata: {self.metadata}"
        )


class MGFExporter:
    """Export an open MetaXtract reader without owning or closing it.

    ``recorded`` preserves usable recorded precursor information without guessing
    acquisition type. ``dia`` exports window spectra using isolation-target m/z,
    omitting precursor charge/intensity. This performs no DIA deconvolution.
    ``on_progress(examined, total, written)`` runs on the calling thread.
    """

    def __init__(self, acquisition="recorded", overwrite=False, peak_mode="centroid"):
        if acquisition not in ACQUISITION_MODES:
            raise ValueError(f"MGF acquisition must be one of {ACQUISITION_MODES}")
        if peak_mode not in PEAK_MODES:
            raise ValueError(f"MGF peak mode must be one of {PEAK_MODES}")
        self.acquisition = acquisition
        self.overwrite = bool(overwrite)
        self.peak_mode = peak_mode

    def export(self, raw_parser, output_path, *, on_progress=None, should_stop=None):
        output = Path(output_path)
        metadata = output.with_suffix(".mgf.metadata.tsv")
        summary = MGFExportSummary(output, metadata)
        output.parent.mkdir(parents=True, exist_ok=True)
        for target in (output, metadata):
            if target.exists() and (not self.overwrite or not target.is_file()):
                raise FileExistsError(f"MGF output already exists: {target}")

        first = int(raw_parser.FirstSpectrumNumber)
        last = int(raw_parser.LastSpectrumNumber)
        total = max(0, last - first + 1)
        source = str(Path(raw_parser.filename).resolve())
        last_update = 0.0

        def check_stop():
            if should_stop is not None and should_stop():
                raise InterruptedError("MGF conversion cancelled")

        with tempfile.TemporaryDirectory(prefix=".mgf-", dir=output.parent) as temporary:
            staged = [Path(temporary) / "spectra.mgf", Path(temporary) / "metadata.tsv"]
            with staged[0].open("w", encoding="ascii", errors="backslashreplace", newline="\n") as mgf, staged[1].open("w", encoding="utf-8", newline="") as table:
                mgf.write("# MetaXtract MS2 export; see companion .mgf.metadata.tsv\n")
                mgf.write("# Isolation-target PEPMASS values do not identify individual precursors.\n")
                writer = csv.DictWriter(table, METADATA_COLUMNS, delimiter="\t")
                writer.writeheader()
                if on_progress:
                    on_progress(0, total, 0)
                for scan in range(first, last + 1):
                    check_stop()
                    row = None
                    try:
                        row = self._spectrum(raw_parser, scan, source, summary, mgf)
                    except Exception as exc:
                        # Disk/write failures must fail the file, not silently skip scans.
                        if isinstance(exc, (OSError, InterruptedError)):
                            raise
                        summary.skipped["read_error"] += 1
                        row = {"source_file": source, "scan": scan, "status": "skipped",
                               "reason": f"read_error: {_text(exc)}", "acquisition": self.acquisition}
                    if row is not None:
                        writer.writerow(row)
                    summary.scans_examined += 1
                    now = time.monotonic()
                    if on_progress and now - last_update >= 0.1:
                        on_progress(summary.scans_examined, total, summary.spectra_written)
                        last_update = now
                check_stop()
            if not summary.spectra_written:
                raise ValueError(f"No exportable MS2 spectra. {summary.describe()}")
            check_stop()
            self._publish(staged, [output, metadata], Path(temporary))
        if on_progress:
            on_progress(total, total, summary.spectra_written)
        return summary

    def _spectrum(self, reader, scan, source, summary, mgf):
        read_scan = getattr(reader, "GetMGFScanData", None)
        if not callable(read_scan):
            order = reader.GetMSOrder(scan)
            if order is None or int(order) < 1:
                raise ValueError("Missing MS order")
            if int(order) != 2:
                return None
            read_scan = reader.GetMGFSpectrumFromScanNumber
        if self.peak_mode == "centroid":
            spectrum = read_scan(scan)
        else:
            spectrum = read_scan(scan, peak_mode=self.peak_mode)
        if spectrum is None:  # MS1/MS3: the reader checks MS order once.
            return None
        mono = _positive(spectrum.get("monoisotopic_mz"))
        target = _positive(spectrum.get("isolation_target_mz"))
        pepmass = target if self.acquisition == "dia" else (mono or target)
        pepmass_source = "isolation_target" if self.acquisition == "dia" or not mono else "monoisotopic"
        rt = finite_number(spectrum.get("retention_time_minutes"))
        rt = finite_number(rt * 60) if rt is not None and rt >= 0 else None
        charge = finite_number(spectrum.get("charge"))
        # The adapter returns None for missing trailer charge. Signed values
        # here include valid -1 for a negative, singly charged ion.
        charge = int(charge) if charge is not None and charge != 0 and charge.is_integer() else None
        if self.acquisition == "dia":
            charge = None
        title = f"File: {_text(Path(source).name)}; scan={scan}"
        title = title.encode("ascii", errors="backslashreplace").decode("ascii")
        if pepmass_source == "isolation_target":
            title += "; precursor=isolation_target"
        row = dict(source_file=source, scan=scan, title=title, acquisition=self.acquisition,
                   status="exported", reason="", pepmass_mz=pepmass,
                   pepmass_source=pepmass_source, charge=charge,
                   retention_time_seconds=rt, monoisotopic_mz=mono,
                   isolation_target_mz=target,
                   isolation_width_mz=finite_number(spectrum.get("isolation_width_mz")),
                   isolation_offset_mz=finite_number(spectrum.get("isolation_offset_mz")),
                   polarity=spectrum.get("polarity", ""),
                   centroid_source=spectrum.get("centroid_source", ""),
                   peak_mode=self.peak_mode,
                   peak_source=spectrum.get("peak_source", spectrum.get("centroid_source", "")))
        if pepmass is None:
            row.update(status="skipped", reason="missing_precursor")
            summary.skipped[row["reason"]] += 1
            return row
        masses, intensities = spectrum["masses"], spectrum["intensities"]
        if len(masses) != len(intensities):
            raise ValueError("Fragment m/z and intensity arrays differ in length")
        original_count = len(masses)
        masses, intensities = self._prepare_peaks(masses, intensities)
        removed = original_count - len(masses)
        row.update(peaks_written=len(masses), invalid_peaks_removed=removed)
        summary.invalid_peaks_removed += removed
        if not len(masses):
            row.update(status="skipped", reason="empty_spectrum")
            summary.skipped[row["reason"]] += 1
            return row
        # Construct a complete block before writing anything to the output.
        lines = ["BEGIN IONS", f"TITLE={title}", f"SCANS={scan}", f"PEPMASS={pepmass:.10f}"]
        intensity = _positive(spectrum.get("precursor_intensity"))
        intensity_source = "recorded" if intensity is not None else "missing"
        parent_scan = None
        derive_intensity = getattr(reader, "GetMGFPrecursorIntensityFromScanNumber", None)
        if self.acquisition == "dda" and intensity is None and target is not None and callable(derive_intensity):
            try:
                value, parent_scan, intensity_source = derive_intensity(
                    scan, target, spectrum.get("isolation_width_mz"), spectrum.get("master_scan"))
                intensity = _positive(value)
            except Exception:
                # Optional precursor information must not discard valid MS2 peaks.
                intensity_source = "unavailable"
        row["precursor_intensity_source"] = "omitted_dia" if self.acquisition == "dia" else intensity_source
        row["precursor_ms1_scan"] = parent_scan
        if intensity is not None and self.acquisition != "dia":
            lines[-1] += f" {intensity:.10g}"
        if charge is not None:
            lines.append(f"CHARGE={abs(charge)}{'+' if charge > 0 else '-'}")
        if rt is not None:
            lines.append(f"RTINSECONDS={rt:.8f}")
        lines.extend(f"{mass:.12g} {intensity:.10g}" for mass, intensity in zip(masses, intensities))
        lines.extend(["END IONS", "", ""])
        mgf.write("\n".join(lines))
        summary.spectra_written += 1
        summary.isolation_target_spectra += pepmass_source == "isolation_target"
        return row

    def _prepare_peaks(self, masses, intensities):
        def numeric(values):
            try:
                return np.asarray(values, dtype=np.float64)
            except (TypeError, ValueError):
                return np.asarray([finite_number(v) for v in values], dtype=np.float64)

        masses, intensities = numeric(masses), numeric(intensities)
        if masses.ndim != 1 or intensities.ndim != 1:
            raise ValueError("Fragment arrays must be one-dimensional")
        valid = np.isfinite(masses) & np.isfinite(intensities) & (masses > 0)
        valid &= intensities >= 0 if self.peak_mode == "recorded" else intensities > 0
        if not np.all(valid):
            masses, intensities = masses[valid], intensities[valid]
        # Vendor arrays are normally sorted; avoid Python tuple allocation and
        # sorting every spectrum when no ordering change is needed.
        if np.any(masses[1:] < masses[:-1]):
            order = np.argsort(masses, kind="stable")
            masses, intensities = masses[order], intensities[order]
        return masses.tolist(), intensities.tolist()

    def _publish(self, staged, targets, temporary):
        """Publish each complete file, restoring old outputs on ordinary errors."""
        installed, backups = [], {}
        try:
            for index, (stage, target) in enumerate(zip(staged, targets)):
                if self.overwrite:
                    if target.exists():
                        backup = temporary / f"backup-{index}"
                        os.replace(target, backup)
                        backups[target] = backup
                    os.replace(stage, target)
                else:
                    # A hard link publishes a complete file and cannot overwrite
                    # an output created by another converter in the meantime.
                    os.link(stage, target)
                installed.append(target)
        except BaseException:
            for target in installed:
                target.unlink(missing_ok=True)
            for target, backup in backups.items():
                os.replace(backup, target)
            raise
