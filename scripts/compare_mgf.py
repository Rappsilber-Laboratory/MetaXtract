"""Compare MGF spectra by original scan number using bounded memory.

Example: python scripts/compare_mgf.py --reference reference.mgf \
    --candidate exported.mgf --output comparison.json
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np


PEAK_START = re.compile(rb"(?m)^[ \t]*[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?[ \t]+")


def iter_spectra(path):
    """Read complete spectrum blocks without loading an entire MGF into RAM."""
    with Path(path).open("rb") as stream:
        pending = b""
        while chunk := stream.read(4 * 1024 * 1024):
            pending += chunk
            position = 0
            while (end := pending.find(b"END IONS", position)) >= 0:
                block = pending[position:end]
                position = end + len(b"END IONS")
                begin = block.find(b"BEGIN IONS")
                if begin < 0:
                    raise ValueError("END IONS without BEGIN IONS")
                block = block[begin + len(b"BEGIN IONS"):]
                peak_start = PEAK_START.search(block)
                header = block[:peak_start.start()] if peak_start else block
                params = {}
                for line in header.splitlines():
                    if b"=" in line:
                        key, value = line.split(b"=", 1)
                        params[key.strip().decode("ascii").upper()] = value.strip().decode("utf-8", errors="replace")
                native_scan = re.search(r"\bscan=(\d+)", params.get("TITLE", ""))
                scan = params.get("SCANS") or (native_scan.group(1) if native_scan else None)
                if scan is None or not scan.isdigit():
                    raise ValueError("Spectrum needs a single SCANS value or scan= in TITLE")
                peaks = np.fromstring(block[peak_start.start():], sep=" ") if peak_start else np.empty(0)
                if peaks.size % 2:
                    raise ValueError(f"Odd number of fragment values in scan {scan}")
                yield int(scan), params, peaks.reshape(-1, 2)
            pending = pending[position:]
        if b"BEGIN IONS" in pending:
            raise ValueError("Truncated MGF ends inside a spectrum")


def _charge(params):
    value = params.get("CHARGE", "")
    match = re.fullmatch(r"(\d+)([+-])", value)
    return int(match[1]) * (-1 if match[2] == "-" else 1) if match else value or None


def compare(reference, candidate):
    paths = [Path(reference), Path(candidate)]
    before = [p.stat() for p in paths]
    streams = [iter(iter_spectra(p)) for p in paths]
    entries = [next(s, None) for s in streams]
    counts = [0, 0]
    total_peaks = [0, 0]
    zero_peaks = [0, 0]
    missing, extra = [], []
    shared = 0
    equal_counts = equal_axes = equal_intensities = 0
    max_mz_error = max_intensity_relative_error = 0.0
    precursor_errors, rt_errors = [], []
    charge_mismatches = 0
    precursor_intensity_present = [0, 0]
    precursor_intensity_errors = []
    last_scan = [-1, -1]

    def advance(index):
        scan, params, peaks = entries[index]
        if scan <= last_scan[index]:
            raise ValueError(f"Duplicate or out-of-order scan {scan} in {paths[index]}")
        last_scan[index] = scan
        counts[index] += 1
        total_peaks[index] += len(peaks)
        zero_peaks[index] += int(np.count_nonzero(peaks[:, 1] == 0))
        precursor_intensity_present[index] += len(params.get("PEPMASS", "").split()) > 1
        entries[index] = next(streams[index], None)

    while any(entry is not None for entry in entries):
        left, right = entries
        if right is None or (left is not None and left[0] < right[0]):
            missing.append(left[0])
            advance(0)
            continue
        if left is None or right[0] < left[0]:
            extra.append(right[0])
            advance(1)
            continue
        shared += 1
        _, a, x = left
        _, b, y = right
        precursor_a = [float(v) for v in a["PEPMASS"].split()]
        precursor_b = [float(v) for v in b["PEPMASS"].split()]
        precursor_errors.append(abs(precursor_a[0] - precursor_b[0]) / precursor_a[0] * 1e6)
        if len(precursor_a) > 1 and len(precursor_b) > 1 and precursor_a[1] > 0:
            precursor_intensity_errors.append(abs(precursor_a[1] - precursor_b[1]) / precursor_a[1])
        if "RTINSECONDS" in a and "RTINSECONDS" in b:
            rt_errors.append(abs(float(a["RTINSECONDS"]) - float(b["RTINSECONDS"])))
        charge_mismatches += _charge(a) != _charge(b)
        if len(x) == len(y):
            equal_counts += 1
            if len(x):
                error = float(np.max(np.abs(x[:, 0] - y[:, 0])))
                max_mz_error = max(max_mz_error, error)
                if error <= 1e-6:
                    equal_axes += 1
                    positive = x[:, 1] > 0
                    if np.any(positive):
                        max_intensity_relative_error = max(max_intensity_relative_error, float(
                            np.max(np.abs(x[positive, 1] - y[positive, 1]) / x[positive, 1])))
                    equal_intensities += bool(np.allclose(x[:, 1], y[:, 1], rtol=1e-8, atol=1e-6))
            else:
                equal_axes += 1
                equal_intensities += 1
        advance(0)
        advance(1)
    after = [p.stat() for p in paths]
    if any(a.st_size != b.st_size or a.st_mtime_ns != b.st_mtime_ns for a, b in zip(before, after)):
        raise ValueError("An input changed during comparison; wait for conversion/copying to finish")
    return dict(
        reference=str(paths[0]), candidate=str(paths[1]), reference_spectra=counts[0],
        candidate_spectra=counts[1], shared_spectra=shared, missing_scan_count=len(missing),
        extra_scan_count=len(extra), missing_scan_examples=missing[:10], extra_scan_examples=extra[:10],
        reference_peak_count=total_peaks[0], candidate_peak_count=total_peaks[1],
        reference_zero_intensity_peaks=zero_peaks[0], candidate_zero_intensity_peaks=zero_peaks[1],
        spectra_with_equal_peak_counts=equal_counts, spectra_with_matching_peak_mz=equal_axes,
        spectra_with_matching_peak_intensities=equal_intensities,
        max_peak_mz_error_same_count_da=max_mz_error,
        max_intensity_relative_error_matching_axes=max_intensity_relative_error,
        max_precursor_error_ppm=max(precursor_errors, default=0),
        p95_precursor_error_ppm=float(np.percentile(precursor_errors, 95)) if precursor_errors else 0,
        max_rt_error_seconds=max(rt_errors, default=0), charge_mismatches=charge_mismatches,
        reference_precursor_intensities=precursor_intensity_present[0],
        candidate_precursor_intensities=precursor_intensity_present[1],
        max_precursor_intensity_relative_error=max(precursor_intensity_errors, default=None),
        reference_bytes=before[0].st_size, candidate_bytes=before[1].st_size,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = compare(args.reference, args.candidate)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
