#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from ftplib import FTP, error_perm
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple


@dataclass(frozen=True)
class FtpEntry:
    name: str
    kind: str  # "file" | "dir" | "unknown"


class PrideFtpWalker:
    def __init__(self, host: str, base: str, timeout: int, retries: int, throttle: float, log_path: Path):
        self.host = host
        self.base = self._norm_base(base)
        self.timeout = timeout
        self.retries = retries
        self.throttle = throttle
        self.log_path = log_path
        self.ftp: Optional[FTP] = None

    def _norm_base(self, p: str) -> str:
        p = p.strip()
        if not p.startswith("/"):
            p = "/" + p
        return p.rstrip("/")

    def log(self, msg: str) -> None:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")

    def connect(self) -> None:
        self.close()
        self.ftp = FTP(self.host, timeout=self.timeout)
        self.ftp.login()
        try:
            self.ftp.voidcmd("OPTS MLST type;size;modify;")
        except Exception:
            pass
        self.log(f"connected host={self.host} base={self.base}")
        print(f"connected host={self.host} base={self.base}")

    def close(self) -> None:
        try:
            if self.ftp is not None:
                try:
                    self.ftp.quit()
                except Exception:
                    try:
                        self.ftp.close()
                    except Exception:
                        pass
        finally:
            self.ftp = None

    def _ensure(self) -> FTP:
        if self.ftp is None:
            self.connect()
        return self.ftp  # type: ignore[return-value]

    def list_dir(self, path: str) -> List[FtpEntry]:
        path = path.rstrip("/") or "/"
        for attempt in range(self.retries + 1):
            try:
                if self.throttle > 0:
                    time.sleep(self.throttle)
                ftp = self._ensure()

                try:
                    out: List[FtpEntry] = []
                    for name, facts in ftp.mlsd(path):
                        t = (facts.get("type") or "").lower()
                        if t in ("dir", "cdir", "pdir"):
                            k = "dir"
                        elif t == "file":
                            k = "file"
                        else:
                            k = "unknown"
                        out.append(FtpEntry(name=name, kind=k))
                    return out
                except Exception:
                    pass

                lines: List[str] = []
                ftp.cwd(path)
                ftp.retrlines("LIST", lines.append)
                out2: List[FtpEntry] = []
                for line in lines:
                    parts = re.split(r"\s+", line, maxsplit=8)
                    if len(parts) < 9:
                        continue
                    perms = parts[0]
                    name = parts[8]
                    if perms.startswith("d"):
                        k = "dir"
                    elif perms.startswith("-"):
                        k = "file"
                    else:
                        k = "unknown"
                    out2.append(FtpEntry(name=name, kind=k))
                return out2

            except (OSError, EOFError, error_perm) as e:
                self.log(f"list_dir_error path={path} attempt={attempt+1} err={repr(e)}")
                print(f"list_dir_error path={path} attempt={attempt+1} err={repr(e)}")
                try:
                    self.connect()
                except Exception as e2:
                    self.log(f"reconnect_error err={repr(e2)}")
                    print(f"reconnect_error err={repr(e2)}")
                if attempt < self.retries:
                    time.sleep(min(30.0, 1.0 * (2 ** attempt)))
                    continue
                return []
        return []


def parse_years(spec: str) -> List[int]:
    spec = spec.strip()
    if "-" in spec:
        a, b = spec.split("-", 1)
        a, b = int(a), int(b)
        if a > b:
            a, b = b, a
        return list(range(a, b + 1))
    return [int(x) for x in spec.split(",") if x.strip()]


def parse_months(spec: str) -> List[int]:
    spec = spec.strip()
    if spec.lower() in ("all", "*"):
        return list(range(1, 13))
    if "-" in spec:
        a, b = spec.split("-", 1)
        a, b = int(a), int(b)
        if a > b:
            a, b = b, a
        return list(range(a, b + 1))
    return [int(x) for x in spec.split(",") if x.strip()]


KNOWN_MS_BASE = {
    "raw", "mzml", "mzxml", "mgf", "wiff", "wiff2", "d", "mzid", "mzidentml",
    "msf", "baf", "tdf", "tdf_bin", "cdf", "ibf"
}
ARCHIVES = {"zip", "gz", "bz2", "xz", "7z", "tar"}


def split_extensions(name: str) -> List[str]:
    n = name.lower().strip()
    if n in (".", "..") or not n:
        return []
    if n.startswith(".") and n.count(".") == 1:
        return [n[1:]]
    parts = n.split(".")
    if len(parts) <= 1:
        return []
    return [p for p in parts[1:] if p]


def classify(name: str, is_dir: bool, treat_d_dir_as_file: bool) -> Tuple[Optional[str], Optional[str]]:
    exts = split_extensions(name)
    if not exts:
        return None, None

    if is_dir:
        if treat_d_dir_as_file and exts[-1] == "d":
            return "d", None
        return None, None

    base = exts[-1]
    archive = None

    if base in ARCHIVES and len(exts) >= 2:
        archive = base
        base = exts[-2]

    if base in KNOWN_MS_BASE:
        return base, archive
    return None, archive if (archive == "zip") else None


def walk_project(
    walker: PrideFtpWalker,
    root: str,
    max_depth: int,
    treat_d_dir_as_file: bool,
) -> Counter:
    counts: Counter = Counter()
    seen: Set[str] = set()
    stack: List[Tuple[str, int]] = [(root, 0)]

    while stack:
        path, depth = stack.pop()
        if path in seen:
            continue
        seen.add(path)

        entries = walker.list_dir(path)
        if not entries:
            continue

        for e in entries:
            if e.name in (".", ".."):
                continue
            full = f"{path}/{e.name}"
            if e.kind == "dir":
                base_ext, _ = classify(e.name, is_dir=True, treat_d_dir_as_file=treat_d_dir_as_file)
                if base_ext is not None:
                    counts[base_ext] += 1
                if depth < max_depth:
                    stack.append((full, depth + 1))
                continue

            if e.kind == "file":
                base_ext, archive = classify(e.name, is_dir=False, treat_d_dir_as_file=treat_d_dir_as_file)
                if base_ext is not None:
                    counts[base_ext] += 1
                if archive == "zip":
                    counts["zip"] += 1
                continue

    return counts


def count_year(
    walker: PrideFtpWalker,
    year: int,
    months: Iterable[int],
    max_depth: int,
    treat_d_dir_as_file: bool,
) -> Counter:
    year_counts: Counter = Counter()

    for m in months:
        mm = f"{m:02d}"
        month_path = f"{walker.base}/{year}/{mm}"
        month_entries = walker.list_dir(month_path)
        if not month_entries:
            continue

        proj_dirs = [e.name for e in month_entries if e.kind == "dir"]
        walker.log(f"year_month {year}-{mm} projects={len(proj_dirs)}")
        print(f"year_month {year}-{mm} projects={len(proj_dirs)}")

        for proj in proj_dirs:
            proj_path = f"{month_path}/{proj}"
            year_counts.update(walk_project(
                walker=walker,
                root=proj_path,
                max_depth=max_depth,
                treat_d_dir_as_file=treat_d_dir_as_file,
            ))

    return year_counts


def write_tsv(out_path: Path, years: List[int], per_year: Dict[int, Counter], columns: List[str]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["year", *columns])
        for y in years:
            c = per_year.get(y, Counter())
            w.writerow([y, *[c.get(col, 0) for col in columns]])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="ftp.pride.ebi.ac.uk")
    ap.add_argument("--base", default="/pride/data/archive")
    ap.add_argument("--years", default="2005-2025")
    ap.add_argument("--months", default="all")
    ap.add_argument("--out", default="pride_yearly_ms_filetype_counts_2000_2025.tsv")
    ap.add_argument("--log", default=None)
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--retries", type=int, default=1)
    ap.add_argument("--throttle", type=float, default=0.0)
    ap.add_argument("--max-depth", type=int, default=4)
    ap.add_argument("--treat-d-dirs", action="store_true")
    args = ap.parse_args()

    years = parse_years(args.years)
    months = parse_months(args.months)

    out_path = Path(args.out)
    log_path = Path(args.log) if args.log else out_path.with_suffix(".log")

    walker = PrideFtpWalker(
        host=args.host,
        base=args.base,
        timeout=args.timeout,
        retries=args.retries,
        throttle=args.throttle,
        log_path=log_path,
    )

    cols = sorted(set(KNOWN_MS_BASE) | {"zip"}, key=lambda x: (x != "raw", x))
    per_year: Dict[int, Counter] = {}

    walker.log(f"start years={years[0]}..{years[-1]} months={list(months)} max_depth={args.max_depth}")
    print((f"start years={years[0]}..{years[-1]} months={list(months)} max_depth={args.max_depth}"))

    try:
        walker.connect()
        for y in years:
            walker.log(f"count_year_start {y}")
            print(f"count_year_start {y}")
            per_year[y] = count_year(
                walker=walker,
                year=y,
                months=months,
                max_depth=args.max_depth,
                treat_d_dir_as_file=args.treat_d_dirs,
            )
            walker.log(f"count_year_done {y} totals={sum(per_year[y].values())}")
            print(f"count_year_done {y} totals={sum(per_year[y].values())}")
    finally:
        walker.close()
        walker.log("done")
        print("done")

    write_tsv(out_path, years, per_year, cols)
    walker.log(f"wrote_tsv path={out_path.resolve()}")
    print(f"wrote_tsv path={out_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
