
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import numpy as np

try:
    import anndata as ad
except Exception:
    ad = None

import h5py


def _read_info_tsv(info_tsv_path: str | Path | None) -> dict[str, Any]:
    if not info_tsv_path:
        return {}
    p = Path(info_tsv_path)
    if not p.exists():
        return {}
    meta: dict[str, Any] = {}
    with p.open("r", encoding="utf-8", errors="replace", newline="") as f:
        r = csv.DictReader(f, delimiter="\t")
        for row in r:
            sec = (row.get("Section") or "").strip()
            key = (row.get("Key") or "").strip()
            val = (row.get("Value") or "").strip()
            if not key:
                continue
            k = f"{sec}.{key}" if sec else key
            meta[k] = val
    return meta


def _get_mz_intensity_arrays(raw_parser, scan_number: int) -> tuple[np.ndarray, np.ndarray]:
    scan_stats = raw_parser.source.GetScanStatsForScanNumber(scan_number)
    if scan_stats is None:
        return np.array([], dtype=np.float64), np.array([], dtype=np.float64)

    if getattr(scan_stats, "IsCentroidScan", False):
        stream = raw_parser.source.GetCentroidStream(scan_number, False)
        if stream is None or not hasattr(stream, "Masses") or not hasattr(stream, "Intensities"):
            return np.array([], dtype=np.float64), np.array([], dtype=np.float64)
        return np.asarray(stream.Masses, dtype=np.float64), np.asarray(stream.Intensities, dtype=np.float64)

    seg = raw_parser.source.GetSegmentedScanFromScanNumber(scan_number, scan_stats)
    if seg is None or not hasattr(seg, "Positions") or not hasattr(seg, "Intensities"):
        return np.array([], dtype=np.float64), np.array([], dtype=np.float64)
    return np.asarray(seg.Positions, dtype=np.float64), np.asarray(seg.Intensities, dtype=np.float64)


def _write_vlen_float(group: h5py.Group, name: str, arrays: list[np.ndarray]) -> None:
    dt = h5py.vlen_dtype(np.dtype("float64"))
    data = np.empty((len(arrays),), dtype=object)
    for i, a in enumerate(arrays):
        data[i] = np.asarray(a, dtype=np.float64)
    if name in group:
        del group[name]
    group.create_dataset(name, data=data, dtype=dt)


def export_ms2_to_h5ad(raw_parser, out_h5ad_path: str | Path, *, info_tsv_path: str | Path | None = None) -> Path:
    """
    MS2-only AnnData export (H5AD):
      - obs: scan-level metadata
      - uns["meta"]: file-level metadata from TSV
      - HDF5 groups:
          /uns/spectra/mz        (vlen float64, one spectrum per scan)
          /uns/spectra/intensity (vlen float64, one spectrum per scan)
    """
    if ad is None:
        raise RuntimeError("anndata is not installed. `pip install anndata h5py`")

    out_h5ad_path = Path(out_h5ad_path)
    out_h5ad_path.parent.mkdir(parents=True, exist_ok=True)

    num_scans = int(getattr(raw_parser, "NumSpectra", 0) or 0)

    obs_rows = []
    mz_list: list[np.ndarray] = []
    it_list: list[np.ndarray] = []

    for scan_number in range(1, num_scans + 1):
        ms_order = int(raw_parser.GetMSOrder(scan_number))
        if ms_order != 2:
            continue
        if not raw_parser.CheckMS2Centroid(scan_number):
            continue

        mz, it = _get_mz_intensity_arrays(raw_parser, scan_number)

        rt = raw_parser.GetRetentionTimeFromScanNumber(scan_number)
        tic = raw_parser.GetTICForScanNumber(scan_number)
        tnp = raw_parser.GetNumPeaksForScanNumber(scan_number)
        prec_i = raw_parser.GetPrecursorIntensityFromScanNumber(scan_number)
        cs = raw_parser.GetMS2ChargeFromScanNumber(scan_number)
        iit = raw_parser.GetIonInjectionTimeFromScanNumber(scan_number)

        bp = raw_parser.GetBasePeakForScanNumber(scan_number)
        bpi = float(bp[1]) if isinstance(bp, (list, tuple)) and len(bp) >= 2 and bp[1] is not None else 0.0
        bpm = float(bp[0]) if isinstance(bp, (list, tuple)) and len(bp) >= 2 and bp[0] is not None else 0.0

        obs_rows.append(
            {
                "scan_number": scan_number,
                "rt_s": float(rt) if rt is not None else 0.0,
                "tic": float(tic) if tic is not None else 0.0,
                "tnp": int(tnp) if tnp is not None else 0,
                "precursor_intensity": float(prec_i) if prec_i is not None else 0.0,
                "charge_state": int(cs) if cs is not None else 0,
                "ion_injection_time_ms": float(iit) if iit is not None else 0.0,
                "base_peak_intensity": float(bpi),
                "base_peak_mz": float(bpm),
                "n_points": int(mz.size),
            }
        )

        mz_list.append(mz)
        it_list.append(it)

    import pandas as pd
    obs = pd.DataFrame(obs_rows)

    adata = ad.AnnData(X=np.empty((len(obs), 0), dtype=np.float32), obs=obs)

    adata.uns["meta"] = _read_info_tsv(info_tsv_path)

    adata.write_h5ad(str(out_h5ad_path))

    with h5py.File(str(out_h5ad_path), "a") as h:
        uns = h.require_group("uns")
        spectra = uns.require_group("spectra")
        _write_vlen_float(spectra, "mz", mz_list)
        _write_vlen_float(spectra, "intensity", it_list)

    return out_h5ad_path
