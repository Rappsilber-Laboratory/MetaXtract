# MetaXtract Snakemake Workflow

## Overview

This workflow provides a portable batch-processing layer for MetaXtract. It can
run local RAW files, including the bundled `../data/small.RAW` example, or
optionally download RAW files from the PRIDE FTP archive before analysis.

The workflow calls the same MetaXtract command-line interface used by Docker and
Apptainer/Singularity.

## Execution Modes

The workflow is controlled by `workflow/config.yaml`.

```yaml
execution:
  mode: "local"        # local, docker, apptainer, or singularity
  metaxtract_root: ".."
  docker_image: "metaxtract:latest"
  apptainer_image: "../metaxtract.sif"
```

Available modes:

- `local`: run `../main.py --config ...` directly.
- `docker`: run the `metaxtract:latest` Docker image.
- `apptainer` or `singularity`: run the `metaxtract.sif` container image.

For Linux container execution, keep `ms_method` and `lc_method` disabled because
Thermo method extraction is not supported by the Linux RawFileReader runtime.

## Install Snakemake

Create a workflow environment:

```bash
cd workflow
python -m venv .snakemake-env
source .snakemake-env/bin/activate
pip install -r requirements.txt
```

On WSL2 Ubuntu, the same commands can be used from the WSL2 terminal. For best
Snakemake filesystem behavior, keep the repository under the WSL2 Linux
filesystem, for example under `~/`, rather than under a Windows-mounted path
such as `/mnt/c` or `/mnt/d`.

## Run the Bundled Small Example

The default `config.yaml` runs the bundled RAW file:

```yaml
inputs:
  mode: "local"
  local_files:
    - "../data/small.RAW"
```

Run a dry run first:

```bash
snakemake -n -p --cores 1
```

Run the workflow:

```bash
snakemake -p --cores 1
```

Outputs are written under:

```text
workflow/results/metaxtract/
workflow/results/runtime/
```

## Run with Docker

Build the Docker image from the repository root:

```bash
cd ..
docker build -t metaxtract:latest .
cd workflow
```

Set `execution.mode` in `config.yaml`:

```yaml
execution:
  mode: "docker"
```

Run:

```bash
snakemake -p --cores 1
```

## Run with Apptainer/Singularity

Build the image from the repository root:

```bash
cd ..
apptainer build metaxtract.sif apptainer.def
cd workflow
```

Set `execution.mode` in `config.yaml`:

```yaml
execution:
  mode: "apptainer"
  apptainer_image: "../metaxtract.sif"
```

Run:

```bash
snakemake -p --cores 1
```

On HPC systems, submit the Snakemake command through the scheduler according to
the cluster policy, for example inside a SLURM job script.

## Optional PRIDE Download Mode

To download RAW files from PRIDE before analysis, switch the input mode:

```yaml
inputs:
  mode: "pride"

pride:
  url: "ftp://ftp.pride.ebi.ac.uk/pride/data/archive"
  year: 2025
  month: 1
  max_files: 2
  copy_dir: "results/data"
```

Then run:

```bash
snakemake -p --cores 1
```

Many HPC systems restrict compute-node internet access. In that case, use
`inputs.mode: "local"` and point `inputs.local_files` to RAW files that have
already been copied to the cluster.

## Useful Commands

```bash
snakemake -n -p --cores 1        # dry run
snakemake -p --cores 1           # run workflow
snakemake --forceall -p --cores 1 # rerun all steps
```
