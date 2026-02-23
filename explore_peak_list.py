import sys
from pathlib import Path
import pandas as pd
import numpy as np

def load_peaklist_as_dict(path: str | Path, ms_type: str):
    path = Path(path)
    ms_type = ms_type.lower()
    if ms_type not in {"ms1", "ms2"}:
        raise ValueError("ms_type must be 'ms1' or 'ms2'")

    suffix = path.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        df = pd.read_parquet(path)
    elif suffix == ".csv":
        df = pd.read_csv(path)
    else:
        raise ValueError("Unsupported file type. Use .parquet/.pq or .csv")

    scan_col = None
    for cand in ("scan_number", "ScanNumber", "scan", "Scan", "scanNumber", "Scan_Number"):
        if cand in df.columns:
            scan_col = cand
            break
    if scan_col is None:
        raise ValueError("No scan number column found")

    if "mz_array" not in df.columns or "intensity_array" not in df.columns:
        raise ValueError("Missing required columns: mz_array and/or intensity_array")

    extended = ms_type == "ms2" and all(c in df.columns for c in ("resolution_array", "noises_array", "baselines_array", "charges_array"))

    out = {}
    for row in df.itertuples(index=False):
        r = row._asdict() if hasattr(row, "_asdict") else dict(zip(df.columns, row))
        sn = int(r[scan_col])
        mz = np.asarray(r["mz_array"], dtype=float)
        inten = np.asarray(r["intensity_array"], dtype=float)

        if extended:
            res = np.asarray(r["resolution_array"], dtype=float)
            noi = np.asarray(r["noises_array"], dtype=float)
            base = np.asarray(r["baselines_array"], dtype=float)
            chg = np.asarray(r["charges_array"], dtype=float)
            out[sn] = (mz, inten, res, noi, base, chg)
        else:
            out[sn] = (mz, inten)

    return out


def main():
    if len(sys.argv) != 3:
        print("Usage: python explore_peak_list.py <peaklist_path> <ms1|ms2>")
        sys.exit(1)

    path = Path(sys.argv[1])
    ms_type = sys.argv[2].strip().lower()

    if ms_type not in {"ms1", "ms2"}:
        print("Second argument must be ms1 or ms2")
        sys.exit(1)

    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    suffix = path.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        df = pd.read_parquet(path)
    elif suffix == ".csv":
        df = pd.read_csv(path)
    else:
        print("Unsupported file type. Use .parquet/.pq or .csv")
        sys.exit(1)

    print("Columns:")
    for c in df.columns.tolist():
        print(f"- {c}")

    scan_col = None
    for cand in ("scan_number", "ScanNumber", "scan", "Scan", "scanNumber", "Scan_Number"):
        if cand in df.columns:
            scan_col = cand
            break

    if scan_col is None:
        print("\nNumber of scans: N/A (no scan column found)")
    else:
        print(f"\nNumber of scans: {int(df[scan_col].nunique(dropna=True))}")

    print("\nFirst 2 rows:")
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(df.head(2).to_string(index=False))

if __name__ == "__main__":
    main()
