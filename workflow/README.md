# MetaXtract Workflow

## Overview

This workflow automates downloading RAW files from the PRIDE
archive and analyzing them with MetaXtract.


## Features

-   Automatically downloads `.raw` files from the PRIDE FTP archive\
-   Selects newest N files per month\
-   Runs MetaXtract on every downloaded file\
-   Stores MetaXtract `_info_*.txt` logs\

## Installation

Create and activate a dedicated environment:

    `python -m venv .snakemake-env`

Activate it:

    `.\.snakemake-env\Scripts\activate`

Install dependencies:

    `pip install "pulp==2.7.0"`

Snakemake will run using this environment.
Or: 
`pip install -U snakemake` 
`pip install -U "pulp>=2.8"`

## Useful Debugging
```bash
snakemake -j 1              # real run
snakemake -n                # dry-run (shows what would run)
snakemake -p -j 1           # prints executed commands and logs
snakemake --forceall -j 1   # re-run everything even if outputs exist
```
## Configuration

All parameters are defined in `config.yaml`.

Example:
```sh
    pride:
        url: "ftp://ftp.pride.ebi.ac.uk/pride/data/archive"
        year: 2025
        month: 1
        max_files: 2
        copy_dir: "results/data"

    output_dir: "results"
```
