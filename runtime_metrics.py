from __future__ import annotations

import os
import sys
import threading
import time
import csv
from dataclasses import dataclass
from pathlib import Path


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]


def _windows_rss_bytes() -> int | None:
    if sys.platform != "win32":
        return None
    try:
        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        get_current_process = ctypes.windll.kernel32.GetCurrentProcess
        get_current_process.restype = wintypes.HANDLE
        get_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_memory_info.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        get_memory_info.restype = wintypes.BOOL
        process = get_current_process()
        ok = get_memory_info(
            process,
            ctypes.byref(counters),
            counters.cb,
        )
        return int(counters.WorkingSetSize) if ok else None
    except Exception:
        return None


def _linux_rss_bytes() -> int | None:
    try:
        with open("/proc/self/status", "r", encoding="ascii") as status_file:
            for line in status_file:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass

    try:
        with open("/proc/self/statm", "r", encoding="ascii") as statm_file:
            resident_pages = int(statm_file.read().split()[1])
        return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError, IndexError):
        return None


def get_process_rss_bytes() -> int | None:
    """Return this process's resident memory, including native/.NET allocations."""
    if sys.platform == "win32":
        return _windows_rss_bytes()
    if sys.platform.startswith("linux"):
        return _linux_rss_bytes()

    # Optional fallback for other platforms. psutil is not required by MetaXtract.
    try:
        import psutil

        return int(psutil.Process(os.getpid()).memory_info().rss)
    except Exception:
        return None


@dataclass(frozen=True)
class FileUsage:
    elapsed_seconds: float
    start_rss_bytes: int | None
    end_rss_bytes: int | None
    peak_rss_bytes: int | None


class FileUsageMonitor:
    """Sample process RSS while one input file is being processed."""

    def __init__(self, sample_interval_seconds: float = 0.2):
        self.sample_interval_seconds = max(0.05, float(sample_interval_seconds))
        self.started_at: float | None = None
        self.start_rss_bytes: int | None = None
        self.peak_rss_bytes: int | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._result: FileUsage | None = None

    def start(self) -> FileUsageMonitor:
        if self.started_at is not None:
            return self
        self.started_at = time.perf_counter()
        self.start_rss_bytes = get_process_rss_bytes()
        self.peak_rss_bytes = self.start_rss_bytes
        self._thread = threading.Thread(
            target=self._sample_until_stopped,
            name="metaxtract-memory-monitor",
            daemon=True,
        )
        self._thread.start()
        return self

    def _sample(self) -> int | None:
        rss_bytes = get_process_rss_bytes()
        if rss_bytes is not None and (
            self.peak_rss_bytes is None or rss_bytes > self.peak_rss_bytes
        ):
            self.peak_rss_bytes = rss_bytes
        return rss_bytes

    def _sample_until_stopped(self) -> None:
        while not self._stop_event.wait(self.sample_interval_seconds):
            self._sample()

    def stop(self) -> FileUsage:
        if self._result is not None:
            return self._result
        if self.started_at is None:
            self.start()

        self._stop_event.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=self.sample_interval_seconds * 2)

        end_rss_bytes = self._sample()
        elapsed_seconds = time.perf_counter() - float(self.started_at)
        self._result = FileUsage(
            elapsed_seconds=elapsed_seconds,
            start_rss_bytes=self.start_rss_bytes,
            end_rss_bytes=end_rss_bytes,
            peak_rss_bytes=self.peak_rss_bytes,
        )
        return self._result


def format_bytes(byte_count: int | None) -> str:
    if byte_count is None:
        return "unavailable"
    return f"{byte_count / (1024 * 1024):.1f} MiB"


def bytes_to_gb(byte_count: int | None) -> str:
    if byte_count is None:
        return ""
    return f"{byte_count / (1024 ** 3):.6f}"


def format_duration(seconds: float) -> str:
    hours, remainder = divmod(max(0.0, seconds), 3600)
    minutes, remaining_seconds = divmod(remainder, 60)
    if hours >= 1:
        return f"{int(hours):02d}:{int(minutes):02d}:{remaining_seconds:05.2f}"
    if minutes >= 1:
        return f"{int(minutes):02d}:{remaining_seconds:05.2f}"
    return f"{remaining_seconds:.2f} s"


def format_file_usage(usage: FileUsage) -> str:
    runtime = f"Runtime: {format_duration(usage.elapsed_seconds)}"
    if usage.start_rss_bytes is None or usage.end_rss_bytes is None:
        return f"{runtime} | Memory RSS: unavailable"

    change_bytes = usage.end_rss_bytes - usage.start_rss_bytes
    change_sign = "+" if change_bytes >= 0 else "-"
    change = format_bytes(abs(change_bytes))
    return (
        f"{runtime} | Memory RSS (start -> end): "
        f"{format_bytes(usage.start_rss_bytes)} -> {format_bytes(usage.end_rss_bytes)}"
        f" | Peak: {format_bytes(usage.peak_rss_bytes)}"
        f" | Change: {change_sign}{change}"
    )


RUNTIME_TSV_HEADERS = [
    "raw_file",
    "sample_name",
    "status",
    "runtime_s",
    "start_memory_gb",
    "end_memory_gb",
    "peak_memory_gb",
    "memory_change_gb",
]


def runtime_usage_row(input_file: str | Path, status: str, usage: FileUsage) -> dict[str, str]:
    path = Path(input_file)
    change_gb = ""
    if usage.start_rss_bytes is not None and usage.end_rss_bytes is not None:
        change_gb = f"{(usage.end_rss_bytes - usage.start_rss_bytes) / (1024 ** 3):.6f}"
    return {
        "raw_file": str(input_file),
        "sample_name": path.stem,
        "status": str(status),
        "runtime_s": f"{usage.elapsed_seconds:.3f}",
        "start_memory_gb": bytes_to_gb(usage.start_rss_bytes),
        "end_memory_gb": bytes_to_gb(usage.end_rss_bytes),
        "peak_memory_gb": bytes_to_gb(usage.peak_rss_bytes),
        "memory_change_gb": change_gb,
    }


def append_runtime_usage_tsv(
    output_path: str | Path,
    input_file: str | Path,
    status: str,
    usage: FileUsage,
) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not output_path.exists() or output_path.stat().st_size == 0
    with output_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RUNTIME_TSV_HEADERS, delimiter="\t")
        if write_header:
            writer.writeheader()
        writer.writerow(runtime_usage_row(input_file, status, usage))
    return output_path
