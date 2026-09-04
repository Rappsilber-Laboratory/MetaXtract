from pathlib import Path
import json
import subprocess
import sys


def resolve_path(value, workflow_dir):
    path = Path(str(value)).expanduser()
    if path.is_absolute():
        return path
    cwd_path = (Path.cwd() / path).resolve()
    if cwd_path.exists():
        return cwd_path
    return (Path(workflow_dir) / path).resolve()


def unix(path):
    return str(path).replace("\\", "/")


def metaxtract_config(raw_path, output_root, meta_cfg, container=False):
    raw_path = Path(raw_path)
    if container:
        raw_input = f"/data/{raw_path.name}"
        output_dir = "/out"
    else:
        raw_input = unix(raw_path.resolve())
        output_dir = unix(Path(output_root).resolve())

    return {
        "io": {
            "input": [raw_input],
            "output_dir": output_dir,
        },
        "outputs": meta_cfg.get("outputs", {}),
        "scan_header": meta_cfg.get("scan_header", {}),
        "visualisation": meta_cfg.get("visualisation", {"enabled": False, "format": "html"}),
        "multi_comparison": {"enabled": False},
    }


cfg = snakemake.config
workflow_dir = Path(snakemake.params.workflow_dir)
exec_cfg = cfg.get("execution", {}) or {}
exec_mode = str(exec_cfg.get("mode", "local")).lower()
meta_cfg = cfg.get("metaxtract", {}) or {}

raw_path = Path(snakemake.input.raw).resolve()
output_root = Path(snakemake.params.output_root).resolve()
config_path = Path(snakemake.output.config).resolve()
output_root.mkdir(parents=True, exist_ok=True)
config_path.parent.mkdir(parents=True, exist_ok=True)

if exec_mode == "local":
    run_cfg = metaxtract_config(raw_path, output_root, meta_cfg, container=False)
    config_path.write_text(json.dumps(run_cfg, indent=2), encoding="utf-8")
    metaxtract_root = resolve_path(exec_cfg.get("metaxtract_root", ".."), workflow_dir)
    cmd = [sys.executable, str(metaxtract_root / "main.py"), "--config", str(config_path)]

elif exec_mode == "docker":
    run_cfg = metaxtract_config(raw_path, output_root, meta_cfg, container=True)
    config_path.write_text(json.dumps(run_cfg, indent=2), encoding="utf-8")
    docker_image = str(exec_cfg.get("docker_image", "metaxtract:latest"))
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{raw_path.parent}:/data:ro",
        "-v",
        f"{output_root}:/out",
        "-v",
        f"{config_path}:/config.yml:ro",
        docker_image,
        "--config",
        "/config.yml",
    ]

elif exec_mode in {"apptainer", "singularity"}:
    run_cfg = metaxtract_config(raw_path, output_root, meta_cfg, container=True)
    config_path.write_text(json.dumps(run_cfg, indent=2), encoding="utf-8")
    runner = "apptainer" if exec_mode == "apptainer" else "singularity"
    apptainer_image = resolve_path(exec_cfg.get("apptainer_image", "../metaxtract.sif"), workflow_dir)
    cmd = [
        runner,
        "run",
        "--bind",
        f"{raw_path.parent}:/data:ro,{output_root}:/out,{config_path}:/config.yml:ro",
        str(apptainer_image),
        "--config",
        "/config.yml",
    ]

else:
    raise ValueError("execution.mode must be local, docker, apptainer, or singularity.")

subprocess.run(cmd, check=True)
Path(snakemake.output.done).parent.mkdir(parents=True, exist_ok=True)
Path(snakemake.output.done).write_text("ok", encoding="utf-8")
