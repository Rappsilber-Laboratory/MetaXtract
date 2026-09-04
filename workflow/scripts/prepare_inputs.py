from pathlib import Path
from urllib.parse import urlparse
import json


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


cfg = snakemake.config
workflow_dir = Path(snakemake.params.workflow_dir)
input_cfg = cfg.get("inputs", {}) or {}
input_mode = str(input_cfg.get("mode", "local")).lower()
records = []

if input_mode == "local":
    local_files = [resolve_path(path, workflow_dir) for path in input_cfg.get("local_files", [])]
    if not local_files:
        raise ValueError("inputs.local_files must contain at least one RAW file when inputs.mode is local.")

    seen = set()
    for raw_path in local_files:
        if not raw_path.exists():
            raise FileNotFoundError(f"RAW file not found: {raw_path}")
        sample = raw_path.stem
        if sample in seen:
            raise ValueError(f"Duplicate sample name in local inputs: {sample}")
        seen.add(sample)
        records.append({"sample": sample, "path": unix(raw_path), "source": "local"})

elif input_mode == "pride":
    from ftplib import FTP

    pride_cfg = cfg.get("pride", {}) or {}
    pride_url = str(pride_cfg.get("url", "ftp://ftp.pride.ebi.ac.uk/pride/data/archive")).rstrip("/")
    pride_year = int(pride_cfg.get("year", 2025))
    pride_month = str(pride_cfg.get("month", 1)).zfill(2)
    max_files = int(pride_cfg.get("max_files", 2))
    copy_dir = resolve_path(pride_cfg.get("copy_dir", "results/data"), workflow_dir)
    copy_dir.mkdir(parents=True, exist_ok=True)

    url = urlparse(pride_url)
    host, base = url.hostname, url.path
    month_dir = f"{base}/{pride_year}/{pride_month}"
    files = []

    with FTP(host, timeout=30) as ftp:
        ftp.login()
        try:
            ftp.voidcmd("OPTS MLST type;size;modify;")
            entries = list(ftp.mlsd(month_dir))
        except Exception:
            entries = []
            ftp.cwd(month_dir)
            tmp = []
            ftp.retrlines("LIST", tmp.append)
            for line in tmp:
                parts = line.split(maxsplit=8)
                if len(parts) < 9:
                    continue
                kind = "dir" if line.startswith("d") else "file"
                entries.append((parts[8], {"type": kind}))

        project_dirs = [name for name, meta in entries if meta.get("type") == "dir"]
        for project in project_dirs:
            project_path = f"{month_dir}/{project}"
            try:
                try:
                    ftp.voidcmd("OPTS MLST type;size;modify;")
                    subentries = list(ftp.mlsd(project_path))
                except Exception:
                    subentries = []
                    ftp.cwd(project_path)
                    tmp = []
                    ftp.retrlines("LIST", tmp.append)
                    for line in tmp:
                        parts = line.split(maxsplit=8)
                        if len(parts) < 9:
                            continue
                        kind = "dir" if line.startswith("d") else "file"
                        size = parts[4] if len(parts) > 4 else "0"
                        subentries.append((parts[8], {"type": kind, "size": size}))

                for name, meta in subentries:
                    if name.lower().endswith(".raw"):
                        files.append(
                            {
                                "path": f"{project_path}/{name}",
                                "size": int(meta.get("size", "0") or 0),
                                "sample": Path(name).stem,
                            }
                        )
            except Exception:
                pass

    files.sort(key=lambda item: item["path"], reverse=True)
    selected = files if max_files == 0 else files[:max_files]

    with FTP(host, timeout=60) as ftp:
        ftp.login()
        for rec in selected:
            dst = copy_dir / Path(rec["path"]).name
            if not dst.exists() or (rec["size"] and dst.stat().st_size != rec["size"]):
                print("Downloading", rec["path"])
                with open(dst, "wb") as handle:
                    ftp.retrbinary(f"RETR {rec['path']}", handle.write)
            records.append({"sample": rec["sample"], "path": unix(dst.resolve()), "source": rec["path"]})

else:
    raise ValueError("inputs.mode must be local or pride.")

execution_mode = str((cfg.get("execution", {}) or {}).get("mode", "local")).lower()
manifest = {
    "input_mode": input_mode,
    "execution_mode": execution_mode,
    "file_count": len(records),
    "files": records,
}

Path(snakemake.output.manifest).parent.mkdir(parents=True, exist_ok=True)
Path(snakemake.output.manifest).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
Path(snakemake.output.flag).write_text("ok", encoding="utf-8")
