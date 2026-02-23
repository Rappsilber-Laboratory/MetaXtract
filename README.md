# MetaXtract

MetaXtract is a hybrid tool for extracting, analysing, and visualising data from **Thermo Fisher RAW** mass spectrometry files. It can be used via a **Graphical User Interface (GUI)**, a **Command Line Interface (CLI)**, or directly as a **Python library** for programmatic workflows.

<div align="center">
<img src="img/abstract.svg" alt="MetaXtract abstract" width="350">
</div>
<div align="center">

[![bioRxiv](https://img.shields.io/badge/biorxiv-2025.11.12.687968v1-b31b1b)](https://www.biorxiv.org/content/10.1101/2025.11.12.687968v1)&nbsp;

</div>

---

## Features

- Reads native **Thermo RAW** files (Windows + Linux)
- GUI and CLI workflows
- Extracts:
  - File and instrument metadata
  - MS1 and MS2 scan headers
  - MS1 and MS2 peak lists with the extended peak list of MS2
- Exports data as:
  - CSV / TSV
  - Parquet (peak lists)
  - Interactive Plotly HTML reports
- Cross-sample visual comparisons
- Designed for downstream computational analysis

---

## Installation

### Requirements
- Python ≥ 3.9
- Thermo Fisher RAW access (DLLs included in the repository)

### Install dependencies

```bash
pip install numpy pandas pyarrow pyyaml tqdm plotly anndata h5py pythonnet PySide6
```

## Build Windows tool

```bash
pip install pyinstaller
```
If `PyQt6` is installed, it should be excluded from the installer. 

```bash
pyinstaller --noconfirm --onedir --console --name MetaXtract   --icon assets/icon.ico   --add-data "os_data;os_data"   --add-data "assets;assets"   --hidden-import=clr --hidden-import=System --hidden-import=pythonnet   --hidden-import=matplotlib.backends.backend_pdf --hidden-import=matplotlib.backends   --collect-all PySide6   --collect-all h5py   --collect-submodules h5py   --exclude-module PyQt6 --exclude-module PyQt6.sip --exclude-module PyQt6.QtCore --exclude-module PyQt6.QtGui --exclude-module PyQt6.QtWidgets   main.py
```
---
## Usage
### Running the GUI
```bash
python main.py
```
### Running the CLI
```bash
python main.py --config /path/to/config.yml
```
#### Configuration File (`config.yml`)

MetaXtract can be fully configured using a YAML configuration file.  
This allows reproducible, automated runs without passing long CLI arguments.

#### Example `config.yml`

```yaml
io:
  input:
    - path/to/sample.RAW
  output_dir: output

outputs:
  file_based_details: true
  ms_method: true
  lc_method: true
  ms2_peaklist_export: true
  ms1_peaklist_export: true
  hdf5_export: false

scan_header:
  MS1:
    select_all: false
    columns:
      Total Ion Current: true
      Retention Time (s): true
  MS2:
    select_all: true
    columns: {}

visualisation:
  enabled: true
  format: html
```
---
### GUI Options
#### Input / Output
- **Input RAW files:** One or multiple Thermo .RAW files.
- **Output directory:** Root folder where results are written (one subfolder per RAW).

#### File-based Outputs
**Writes a TSV file containing:** Instrument details, Scan counts, Run statistics, Sample information. 
**MS Method:** Extracts the MS method (`*_MS_method.txt`).
**LC Method:** Extracts the LC method (`*_LC_method.txt`).

#### Scan Header Extraction
- MS1 scan headers
- MS2 scan headers
Each allows: Selecting individual columns or Select all (complete MS1 / MS2).

#### Output
- CSV tables
- Optional interactive HTML plots (TIC, BPI, TNP, etc.)

#### Peak List Export
- **Export MS2 extended peak list (Parquet):** Per scan; `mz_array`, `intensity_array`, `resolution_array`, `noises_array`, `baselines_array`, `charges_array`.
- **Export MS1 peak list (Parquet):** Per scan; `mz_array`, `intensity_array` with centroid/profile flag.

#### Visualisation
Interactive Plotly HTML reports, MS1 and MS2 trends, and Cross-sample overlays and boxplots.

---
## Using MetaXtract as a Python Library
You can import `MetaXtract` directly and use it in your own Python scripts (e.g. notebooks, pipelines, custom QC tooling).

### Example

```python
from raw_parser import MetaXtract

raw = MetaXtract("path/to/file.RAW")

raw.CountMS2()

tic = raw.GetTICForScanNumber(100)
rt = raw.GetRetentionTimeFromScanNumber(100)

raw.ExportPeakList("ms2_peaklist.parquet")
raw.ExportMS1PeakList("ms1_peaklist.parquet")

raw.CloseRAWFile()
```


### Loading Peak Lists into Python (scan → NumPy arrays)

MetaXtract exports MS1/MS2 peak lists as **Parquet** (or CSV) where each row represents one scan and stores arrays (m/z, intensities, etc.).  
The helper function below reads such a file and returns a **dictionary**:

- **key** = scan number  
- **value** = tuple of NumPy arrays  
  - MS1: `(mz, intensity)`
  - MS2: `(mz, intensity, resolution, noise, baseline, charge)` if those columns exist


### Helper function

```python
from pathlib import Path
import numpy as np
import pandas as pd

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
        raise ValueError("Unsupported file type")

    scan_col = None
    for cand in ("scan_number", "ScanNumber", "scan", "Scan", "scanNumber", "Scan_Number"):
        if cand in df.columns:
            scan_col = cand
            break
    if scan_col is None:
        raise ValueError("No scan number column found")

    if "mz_array" not in df.columns or "intensity_array" not in df.columns:
        raise ValueError("Missing mz_array or intensity_array")

    extended = ms_type == "ms2" and all(
        c in df.columns for c in (
            "resolution_array",
            "noises_array",
            "baselines_array",
            "charges_array"
        )
    )

    out = {}
    for row in df.itertuples(index=False):
        r = row._asdict()
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
```
## **License**

This project is licensed under the Apache-2.0 license.
### Third-party licenses and copyright

**RawFileReader** reading tool. Copyright © 2016 by Thermo Fisher Scientific, Inc. All rights reserved. See [THERMO_LICENSE.txt](https://github.com/lutfia95/MetaXtract/blob/main/os_data/THERMO_LICENSE.txt) for licensing information. 
Note: anyone recieving RawFileReader as part of a larger software distribution (in the current context, as part of MetaXtract) is considered an "end user" under 
section 3.3 of the RawFileReader License, and is not granted rights to redistribute RawFileReader.








