from pathlib import Path
import csv
import json
import statistics
import time


def read_wall(tsv):
    try:
        with open(tsv, newline="") as handle:
            row = next(csv.DictReader(handle, delimiter="\t"))
            return float(row.get("wallclock") or row.get("s") or 0.0)
    except Exception:
        return 0.0


runtime_dir = Path(snakemake.params.runtime_dir)
start_path = Path(snakemake.input.start)
start_ts = int(start_path.read_text().strip()) if start_path.exists() else int(time.time())
overall = int(time.time()) - start_ts

prepare_wall = read_wall(runtime_dir / "benchmark_prepare_inputs.tsv")
analysis_benches = sorted(runtime_dir.glob("benchmark_analyze_*.tsv"))
analysis_walls = [read_wall(path) for path in analysis_benches]
total = sum(analysis_walls)
mean = statistics.mean(analysis_walls) if analysis_walls else 0.0

manifest = json.loads(Path(snakemake.input.manifest).read_text(encoding="utf-8"))
outp = Path(snakemake.output[0])
outp.parent.mkdir(parents=True, exist_ok=True)
with open(outp, "w", encoding="utf-8") as handle:
    handle.write("=== Runtime Summary ===\n")
    handle.write(f"input_mode: {manifest.get('input_mode')}\n")
    handle.write(f"execution_mode: {manifest.get('execution_mode')}\n")
    handle.write(f"files_count: {manifest.get('file_count', 0)}\n")
    handle.write(f"overall_pipeline_seconds: {overall}\n")
    handle.write(f"prepare_inputs_seconds: {prepare_wall:.3f}\n")
    handle.write(f"analysis_total_seconds: {total:.3f}\n")
    handle.write(f"analysis_per_file_mean_seconds: {mean:.3f}\n")
