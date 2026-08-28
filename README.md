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
  - MS1 and MS2 technical trailer details
  - MS1 and MS2 peak lists with the extended peak list of MS2
- Exports data as:
  - CSV / TSV
  - Parquet (peak lists)
  - SDRF-Proteomics (`metadata.sdrf.tsv`)
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

### Running with Docker or Apptainer/Singularity

MetaXtract can also be run as a CLI-only Linux container. This is the recommended
mode for macOS and HPC infrastructure where a graphical desktop is not available.

On macOS, `brew install docker` installs mostly the Docker CLI, not the Docker
daemon/engine. Mac computers run Linux containers through Docker Desktop or
another VM-based backend because macOS cannot run Linux containers directly.
Install Docker Desktop, open it, and wait until it finishes starting:

```bash
brew install --cask docker
open -a Docker
docker info
```

Build the Docker image:

```bash
docker build -t metaxtract:latest .
```

Run a mounted RAW-file directory and output directory:

```bash
docker run --rm \
  -v /path/to/raw_files:/data:ro \
  -v /path/to/output:/out \
  metaxtract:latest \
  --input /data/sample.raw \
  --output-dir /out \
  --file-based-details \
  --complete-ms1 \
  --complete-ms2 \
  --ms1-peaklist-export \
  --ms2-peaklist-export \
  --graphical-representation
```

Example using the bundled small RAW file:

```bash
mkdir -p output/docker_small
docker run --rm \
  -v "$(pwd)/data:/data:ro" \
  -v "$(pwd)/output/docker_small:/out" \
  metaxtract:latest \
  --input /data/small.RAW \
  --output-dir /out \
  --file-based-details \
  --complete-ms1 \
  --complete-ms2 \
  --ms1-peaklist-export \
  --ms2-peaklist-export \
  --graphical-representation
```

The repository also includes `config_container_small.yml`, a container-ready
configuration for the bundled small RAW file:

```yaml
io:
  input:
    - /data/small.RAW
  output_dir: /out

outputs:
  file_based_details: true
  ms_method: false
  lc_method: false
  ms2_peaklist_export: true
  ms1_peaklist_export: true
  ms2_technical_details_export: false
  ms1_technical_details_export: false
  hdf5_export: false

scan_header:
  MS1:
    select_all: true
    columns:
      Ion Injection Time (ms): true
      Total Number of Peaks: true
      Total Ion Current: true
      Scan Start Time (min): true
      Base Peak Intensity: true
      Base Peak m/z: true
      Scan Mode: true
      thermo_Multi Inject Info: true
      thermo_Multiple Injection: true
  MS2:
    select_all: true
    columns:
      Total Ion Current: true
      Total Number of Peaks: true
      Scan Start Time (min): true
      Base Peak Intensity: true
      Base Peak m/z: true
      Selected Ion Intensity: true
      Filter String: true
      Scan Mode: true

visualisation:
  enabled: true
  format: html

multi_comparison:
  enabled: false
```

Run Docker with the included config file:

```bash
mkdir -p output/docker_small
docker run --rm \
  -v "$(pwd)/data:/data:ro" \
  -v "$(pwd)/output/docker_small:/out" \
  -v "$(pwd)/config_container_small.yml:/config.yml:ro" \
  metaxtract:latest \
  --config /config.yml
```

On Apple Silicon Macs, build and run the image without `--platform` first so
Docker uses the native ARM64 Linux backend:

```bash
docker build -t metaxtract:latest .
mkdir -p output/docker_small
docker run --rm \
  -v "$(pwd)/data:/data:ro" \
  -v "$(pwd)/output/docker_small:/out" \
  metaxtract:latest \
  --input /data/small.RAW \
  --output-dir /out \
  --file-based-details \
  --complete-ms1 \
  --complete-ms2 \
  --ms1-peaklist-export \
  --ms2-peaklist-export \
  --graphical-representation
```

Do not use smart quotes copied from rich-text editors in Docker commands; use
plain shell quotes such as `"$(pwd)/data:/data:ro"`.

Running the container with `--platform linux/amd64` on Apple Silicon uses
emulation. If Mono or `pythonnet` crashes with a message such as
`Assertion: should not be reached at tramp-amd64.c`, rebuild and run without
`--platform`. If native ARM64 execution does not work on the machine, run the
container on an x86_64 Linux workstation or HPC node instead.

For HPC systems, build an Apptainer/Singularity image from Docker or from the
included definition file:

On WSL2 Ubuntu, Apptainer can be installed with:

```bash
sudo apt update
sudo apt install -y software-properties-common
sudo add-apt-repository -y ppa:apptainer/ppa
sudo apt update
sudo apt install -y apptainer
```

Check the installation:

```bash
apptainer --version
```

If the PPA is not available for the Ubuntu version installed in WSL2, check the
Ubuntu version with:

```bash
lsb_release -a
```

Then from the MetaXtract repository, build the Apptainer/Singularity image:

```bash
apptainer build metaxtract.sif apptainer.def
apptainer run --bind /path/to/raw_files:/data,/path/to/output:/out metaxtract.sif --input /data/sample.raw --output-dir /out --file-based-details
```

Run the bundled small RAW file with Apptainer/Singularity on WSL2 or HPC:

```bash
mkdir -p output/hpc_small
apptainer run \
  --bind "$(pwd)/data:/data","$(pwd)/output/hpc_small:/out" \
  metaxtract.sif \
  --input /data/small.RAW \
  --output-dir /out \
  --file-based-details \
  --complete-ms1 \
  --complete-ms2 \
  --ms1-peaklist-export \
  --ms2-peaklist-export \
  --graphical-representation
```

Run Apptainer/Singularity with the included config file:

```bash
mkdir -p output/hpc_small
apptainer run \
  --bind "$(pwd)/data:/data","$(pwd)/output/hpc_small:/out","$(pwd)/config_container_small.yml:/config.yml" \
  metaxtract.sif \
  --config /config.yml
```

The container uses the bundled Thermo RawFileReader DLLs through Mono and
`pythonnet`. The GUI is not included in the container workflow; use command-line
options or a YAML configuration file. MS-method and LC-method export should be
disabled on Linux containers because those Thermo method-reading calls are not
supported on Linux.

#### Configuration File (`config.yml`)

MetaXtract can be fully configured using a YAML configuration file.  
This allows reproducible, automated runs without passing long CLI arguments.

#### Example `config.yml`

```yaml
io:
  input:
    - path/to/sample_1.RAW
    - path/to/sample_2.RAW
    - path/to/sample_3.RAW
  output_dir: output

outputs:
  file_based_details: true
  ms_method: true # this option is not supported on Linux
  lc_method: true # this option is not supported on Linux
  ms2_peaklist_export: true
  ms1_peaklist_export: true
  ms2_technical_details_export: false
  ms1_technical_details_export: false
  hdf5_export: false

scan_header:
  MS1:
    select_all: false
    columns:
      Total Ion Current: true
      Scan Start Time (min): true
      Scan Mode: false
  MS2:
    select_all: true
    columns:
      Scan Mode: false

visualisation:
  enabled: true
  format: html

sdrf:
  # Optional CLI/HPC SDRF support.
  # draft: true writes metadata.sdrf.draft.tsv during the normal run, with
  # only RAW-derived fields filled. Users can complete it after processing.
  draft: false
  draft_output: metadata.sdrf.draft.tsv
  # metadata can point to a completed user-filled SDRF metadata TSV.
  metadata: null
  output: metadata.sdrf.tsv

multi_comparison:
  enabled: true
  # Select any 2 or more inputs using their 1-based positions in io.input.
  samples: [1, 2, 3]
```
---
### GUI Options
#### Input / Output
- **Input RAW files:** One or multiple Thermo .RAW files.
- **Output directory:** Root folder where results are written (one subfolder per RAW).

#### File-based Outputs
**Writes a TSV file containing:** Instrument details, Scan counts, Run statistics, Sample information. 
**MS Method:** Extracts the MS method (`*_MS_method.txt`). # this option is not supported on Linux
**LC Method:** Extracts the LC method (`*_LC_method.txt`). # this option is not supported on Linux

#### Scan Header Extraction
- MS1 scan headers
- MS2 scan headers
Each allows: Selecting individual columns or Select all (complete MS1 / MS2). `Scan Mode` can be selected for both MS1 and MS2.

#### Output Column Naming
MetaXtract uses PSI-MS/mzML-style names where a clear controlled vocabulary term exists. Thermo trailer-extra fields without a direct PSI-MS match are prefixed with `thermo_`. Internally, old Thermo labels such as `Base Peak Mass` and `Retention Time (s)` are still recognized as source aliases, but new CSV exports use the names below.

| Output column | PSI-MS / mzML match | Notes |
|---|---|---|
| `Scan Start Time (min)` | `scan start time`, `MS:1000016` | Thermo returns retention time in minutes. Replaces old ambiguous `Retention Time (s)` / `Retention Time (min)`. |
| `Total Ion Current` | `total ion current`, `MS:1000285` | Direct match. |
| `Base Peak Intensity` | `base peak intensity`, `MS:1000505` | Direct match. |
| `Base Peak m/z` | `base peak m/z`, `MS:1000504` | Replaces old `Base Peak Mass`; the value is m/z, not neutral mass. |
| `Ion Injection Time (ms)` | `ion injection time`, `MS:1000927` | Direct match; unit is milliseconds. |
| `Collision Energy` | `collision energy`, `MS:1000045` | Direct match when the source value is absolute collision energy. |
| `Collision Energy (eV)` | `collision energy`, `MS:1000045` | Same concept with explicit electronvolt unit. |
| `Normalized Collision Energy (%)` | `normalized collision energy`, `MS:1000138` | Replaces old `HCD Energy` when Thermo reports a normalized percent value. |
| `Dissociation Method` | `dissociation method`, `MS:1000044` | Replaces old `Activation Type`. |
| `Mass Analyzer Type` | `mass analyzer type`, `MS:1000443` | Direct match. |
| `Detector Type` | `detector type`, `MS:1000026` | Direct match. |
| `Charge State` | `charge state`, `MS:1000041` | Direct match. |
| `Filter String` | `filter string`, `MS:1000512` | Replaces old `Scan Description`. |
| `Scan Window m/z Range` | `scan window lower limit`, `MS:1000501`; `scan window upper limit`, `MS:1000500` | Exported as a compact `lower-upper` range. |
| `Isolation Window Width (m/z)` | Derived from `isolation window lower offset`, `MS:1000828`, and `isolation window upper offset`, `MS:1000829` | Kept as width because that is what Thermo exposes directly. |
| `Selected Ion Intensity` | `peak intensity`, `MS:1000042`, in precursor selected-ion context | Replaces old `Precursor Intensity`. |
| `Experimental Precursor Monoisotopic m/z` | `experimental precursor monoisotopic m/z`, `MS:1003208` | Replaces old `Monoisotopic M/Z`. |
| `Sampling Frequency` | `sampling frequency`, `MS:1000029` | Only a direct match if the Thermo source value is signal sampling frequency. |
| `FAIMS Compensation Voltage` | `FAIMS compensation voltage`, `MS:1001581` | Replaces old `FAIMS CV`. |

Columns without a direct one-to-one PSI-MS scan-header term but still kept as general, non-vendor labels:

`Total Number of Peaks`, `Scan Mode`.

Columns intentionally marked as Thermo-specific because they are RAW trailer fields or instrument/vendor implementation details:

`thermo_Number of Channels`, `thermo_AGC`, `thermo_Micro Scan Count`, `thermo_Elapsed Scan Time (sec)`, `thermo_Average Scan by Inst`, `thermo_Orbitrap Resolution`, `thermo_API Process Delay`, `thermo_Dependency Type`, `thermo_Multi Inject Info`, `thermo_Master Scan Number`, `thermo_Access ID`, `thermo_Conversion Parameter I`, `thermo_Conversion Parameter A`, `thermo_Conversion Parameter B`, `thermo_Conversion Parameter C`, `thermo_Conversion Parameter D`, `thermo_Conversion Parameter E`, `thermo_Temperature Comp. (ppm)`, `thermo_RF Comp. (ppm)`, `thermo_Space Charge Comp. (ppm)`, `thermo_Resolution Comp. (ppm)`, `thermo_Number of LM Found`, `thermo_LM Correction (ppm)`, `thermo_RawOvFtT`, `thermo_Injection t0`, `thermo_Reagent Ion Injection Time (ms)`, `thermo_FAIMS Voltage On`, `thermo_Multiple Injection`.

#### Output
- CSV tables
- Optional interactive HTML plots (TIC, BPI, TNP, etc.)

#### Peak List Export
- **Export MS2 extended peak list (Parquet):** Per scan; `mz_array`, `intensity_array`, `resolution_array`, `noises_array`, `baselines_array`, `charges_array`.
- **Export MS1 peak list (Parquet):** Per scan; `mz_array`, `intensity_array` with centroid/profile flag.

#### Technical Details Export
- **Export MS2 technical details:** Writes `*_technical_details_ms2_*.csv` using `GetMoreMSInfos` for each MS2 scan.
- **Export MS1 technical details:** Writes `*_technical_details_ms1_*.csv` using `GetMoreMSInfos` for each MS1 scan.

Check the [documentation](Doc/Doc.pdf) for more details. 
#### Visualisation
Interactive Plotly HTML reports, MS1 and MS2 trends, and cross-sample overlays and boxplots.

Visualisation output cases:

- One RAW file with visualisation enabled: MetaXtract writes only the per-file reports, for example `<sample>_MS1.html` and/or `<sample>_MS2.html`.
- Two or more RAW files with visualisation enabled: MetaXtract writes the per-file reports and also writes combined comparison reports, `MS1_compare.html` and/or `MS2_compare.html`, using all processed files.
- GUI with **Multi-sample comparison** enabled: the user selects any 2 or more loaded files, and `MS1_compare.html` / `MS2_compare.html` are generated only for that selected subset.
- YAML/CLI with `multi_comparison.enabled: true`: list the files to compare under `multi_comparison.samples` using 1-based input positions such as `[1, 2, 4]`; the comparison reports are generated for that subset.

If visualisation is disabled, no per-file or comparison HTML reports are written.

#### Runtime and memory logging
For every processed RAW file, both the GUI log and CLI output report memory at the start and a final summary containing runtime, ending memory, sampled peak memory, and memory change. Each run also writes `runtime_summary_YYYYMMDD_HHMMSS.tsv` in the root output directory. The TSV contains one row per processed RAW file with status, runtime in seconds, start/end/peak memory in GB, and memory change in GB. Memory is the resident set size (RSS) of the MetaXtract process, so it includes Python, native libraries, and Thermo/.NET allocations used while that file is processed.

#### SDRF-Proteomics export
Enable **Export SDRF-Proteomics metadata (.sdrf.tsv)** in the GUI to open the metadata editor before processing. MetaXtract fills the RAW filename, instrument model, acquisition date, technology type, SDRF annotation tool, SDRF version, and template. Common Thermo instrument models are written as PSI-MS controlled-vocabulary values, for example `NT=Orbitrap Fusion Lumos;AC=MS:1002732`. If the instrument cannot be mapped automatically, fill `comment[instrument]` manually with the preferred `NT=...;AC=...` value. Initially, the grid shows only required MS-proteomics inputs that cannot be determined reliably from a RAW file.

Use **Add column** to search and multi-select from the complete known column-name catalog in the official SDRF templates registry. This includes sample, clinical, organism, DIA, single-cell, crosslinking, immunopeptidomics, metaproteomics, environmental, affinity-proteomics, and metabolomics fields. A custom `factor value[...]` column can also be added from the same picker. Added columns must be filled for every row and can be removed again with **Remove optional column**.

The editor starts with one sample-to-file row per selected RAW file. Additional rows can be added for multiplexed experiments where multiple samples or labels share a RAW file. The dataset-level file is written as `metadata.sdrf.tsv` in the root output directory using the `ms-proteomics v1.1.0` template.

CLI users can generate an SDRF draft during the normal extraction run:

```bash
python main.py \
  --input path/to/sample_1.RAW path/to/sample_2.RAW \
  --output-dir output/cli_run \
  --file-based-details \
  --sdrf-draft
```

This writes `output/cli_run/metadata.sdrf.draft.tsv`. MetaXtract fills only the fields that can be read or derived safely from the RAW file, including the RAW filename, acquisition date, technology type, recognized instrument model, SDRF annotation tool, SDRF version, and SDRF template. Biological and experimental design fields that cannot be inferred from RAW files are left for the user to complete manually.

For the bundled small example, the draft command is:

```bash
python main.py \
  --input data/small.RAW \
  --output-dir output/cli_small \
  --file-based-details \
  --sdrf-draft
```

The same draft mode can be enabled from YAML:

```yaml
sdrf:
  draft: true
  draft_output: metadata.sdrf.draft.tsv
```

Users who already have a completed metadata TSV can ask MetaXtract to validate/enrich it and write a final SDRF file:

```bash
python main.py \
  --input data/small.RAW \
  --output-dir output/cli_small \
  --file-based-details \
  --sdrf-metadata sdrf_input.tsv
```

The completed metadata file can also be passed from YAML:

```yaml
sdrf:
  metadata: sdrf_input.tsv
  output: metadata.sdrf.tsv
```

If a user wants a blank starter TSV without processing RAW files, they can still create one with `--sdrf-template-out`; this command only writes the TSV template and exits.

Optional SDRF fields such as `comment[precursor mass tolerance]` and `comment[fragment mass tolerance]` can be added in the GUI, or as extra columns in the CLI metadata TSV. These fields describe the mass-error tolerance intended for downstream identification/search workflows: precursor tolerance applies to intact precursor ions, while fragment tolerance applies to MS/MS fragment ions.

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
