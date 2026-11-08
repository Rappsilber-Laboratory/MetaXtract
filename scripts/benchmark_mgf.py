from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True, help="JSON measurements")
    parser.add_argument("--first-scan", type=int, default=1)
    parser.add_argument("--scan-count", type=int, default=5000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--peak-mode", choices=("centroid", "recorded"), default="centroid")
    parser.add_argument("--acquisition", choices=("recorded", "dda", "dia"), default="recorded")
    parser.add_argument("--module-dir", type=Path, help="Optional alternate exporter/reader directory for before/after comparisons")
    args = parser.parse_args()
    if min(args.first_scan, args.scan_count, args.repeats) < 1:
        parser.error("Scan numbers, scan count and repeats must be positive")
    repository = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repository))
    if args.module_dir:
        sys.path.insert(0, str(args.module_dir.resolve()))
    import mgf_exporter
    import raw_parser
    from runtime_metrics import FileUsageMonitor

    measurements = []
    with tempfile.TemporaryDirectory(prefix="mgf-benchmark-") as temporary:
        for repeat in range(args.repeats):
            reader = raw_parser.MetaXtract(args.input)
            first = max(reader.FirstSpectrumNumber, args.first_scan)
            last = min(reader.LastSpectrumNumber, first + args.scan_count - 1)
            if first > last:
                reader.CloseRAWFile()
                parser.error("Scan interval is outside this RAW file")
            reader.FirstSpectrumNumber, reader.LastSpectrumNumber = first, last
            options = dict(acquisition=args.acquisition, overwrite=True)
            if args.peak_mode != "centroid":
                options["peak_mode"] = args.peak_mode
            monitor = FileUsageMonitor().start()
            try:
                summary = mgf_exporter.MGFExporter(**options).export(reader, Path(temporary) / "benchmark.mgf")
            finally:
                usage = monitor.stop()
                reader.CloseRAWFile()
            measurement = dict(repeat=repeat + 1, first_scan=first, last_scan=last,
                               spectra_written=summary.spectra_written,
                               output_bytes=summary.output.stat().st_size, **asdict(usage))
            measurements.append(measurement)
            print(json.dumps(measurement), flush=True)
    report = dict(
        input=str(Path(args.input).resolve()), acquisition=args.acquisition, peak_mode=args.peak_mode,
        median_export_seconds=statistics.median(m["elapsed_seconds"] for m in measurements),
        max_process_rss_bytes=max(m["peak_rss_bytes"] or 0 for m in measurements),
        exporter_sha256=hashlib.sha256(Path(mgf_exporter.__file__).read_bytes()).hexdigest(),
        reader_sha256=hashlib.sha256(Path(raw_parser.__file__).read_bytes()).hexdigest(),
        measurements=measurements,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
