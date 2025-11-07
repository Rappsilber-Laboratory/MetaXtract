# MetaXtract
The **MetaXtract** is a hybrid tool that can be used through a **Graphical User Interface (GUI)** or as a **Command Line Interface (CLI)** to extract and visualize data from Thermo RAW files.

## **Features**

- Extracts metadata from Thermo Fisher RAW files
- Supports both **GUI** and **CLI** usage
- Generates **MS1** and **MS2** plots
- Outputs results in structured tabular formats (**TXT, CSV, PDF**)
- Aligns with **FAIR data principles**

## **Installation**

Download the latest version from the [Releases](https://github.com/Rappsilber-Laboratory/MetaXtract/releases) page.

## **Usage**

### **1. GUI Mode**

Double-click the `MetaXtract_vX.X.X.exe` to launch the graphical interface.

### **2. Command Line Mode**

The tool can be executed directly via the command line for automated processing using Windows PowerShell.

```sh
MetaXtract.v0.3.0.exe --input <RAW_FILES> --output-dir <OUTPUT_DIRECTORY> [OPTIONS]
```

### **Command Line Arguments**

| **Argument** | **Description** | **Type** |
|-------------|----------------|----------|
| `--input`  | Path to one or more RAW files. | **Required** |
| `--output_dir`  | Directory to save extracted data. | **Required** |
| `--file-based-details` | Extract basic file information (e.g., instrument details, file creation date, sample information). | **Optional** |
| `--ms-method` | Extract the MS method details and save to a file. | **Optional** |
| `--lc-method` | Extract the LC method details and save to a file. | **Optional** |
| `--graphical-representation` | Generate and save plots for MS1 and MS2 data. | **Optional** |
| `--complete-ms2` | Select all MS2 scan information (overrides the YAML config if used). | **Optional** |
| `--complete-ms1` | Select all MS1 scan information (overrides the YAML config if used). | **Optional** |
| `--config <path_to_config>` | Path to a YAML configuration file that specifies which MS1 and MS2 options to extract. The file is needed also if `--complete-ms1/ms2` are applied. | **Required** |

### **Example Command:**

```sh
MetaXtract.vx.x.x.exe --input C:\data\file1.raw C:\data\file2.raw --output-dir C:\output --file-based-details --graphical-representation --config config.yml --ms-method --lc-method --complete-ms2 --complete-ms1
```

## **Output Formats**

- **TXT**: Tabular metadata for manual inspection
- **CSV**: Processed data for further analysis
- **PDF**: Graphical representations of MS1 and MS2 spectra

## **License**

This project is licensed under the Apache-2.0 license.
### Third-party licenses and copyright

**RawFileReader** reading tool. Copyright © 2016 by Thermo Fisher Scientific, Inc. All rights reserved. See [THERMO_LICENSE.txt](https://github.com/lutfia95/MetaXtract/blob/main/os_data/THERMO_LICENSE.txt) for licensing information. 
Note: anyone recieving RawFileReader as part of a larger software distribution (in the current context, as part of MetaXtract) is considered an "end user" under 
section 3.3 of the RawFileReader License, and is not granted rights to redistribute RawFileReader.
