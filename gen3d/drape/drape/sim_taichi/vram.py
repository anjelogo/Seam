from __future__ import annotations

import ctypes
import platform
import shutil
import subprocess
import threading
import time
from ctypes import wintypes

_INTERVAL = 0.25
_BASELINE_SAMPLES = 4
_PDH_FMT_DOUBLE = 0x00000200
_PDH_MORE_DATA = 0x800007D2
_ADAPTER_COUNTER = r"\GPU Adapter Memory(*)\Dedicated Usage"


class _CounterValue(ctypes.Structure):
    _fields_ = [("status", wintypes.DWORD), ("value", ctypes.c_double)]


class _CounterItem(ctypes.Structure):
    _fields_ = [("name", wintypes.LPWSTR), ("value", _CounterValue)]


class _AdapterMemory:
    def __init__(self) -> None:
        self._pdh = ctypes.WinDLL("pdh.dll")
        for name in ("PdhGetFormattedCounterArrayW", "PdhOpenQueryW", "PdhAddEnglishCounterW", "PdhCollectQueryData"):
            getattr(self._pdh, name).restype = wintypes.DWORD
        self._query = ctypes.c_void_p()
        self._counter = ctypes.c_void_p()
        self._instance: str | None = None
        if self._pdh.PdhOpenQueryW(None, 0, ctypes.byref(self._query)):
            raise OSError("PdhOpenQueryW failed")
        if self._pdh.PdhAddEnglishCounterW(self._query, _ADAPTER_COUNTER, 0, ctypes.byref(self._counter)):
            self.close()
            raise OSError(f"PdhAddEnglishCounterW failed for {_ADAPTER_COUNTER}")

    def sample(self) -> float | None:
        if not self._query or self._pdh.PdhCollectQueryData(self._query):
            return None
        size = wintypes.DWORD(0)
        count = wintypes.DWORD(0)
        status = self._pdh.PdhGetFormattedCounterArrayW(
            self._counter, _PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count), None
        )
        if status != _PDH_MORE_DATA or not size.value:
            return None
        buffer = ctypes.create_string_buffer(size.value)
        if self._pdh.PdhGetFormattedCounterArrayW(
            self._counter, _PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count), buffer
        ):
            return None
        items = ctypes.cast(buffer, ctypes.POINTER(_CounterItem))
        values = {
            items[index].name: items[index].value.value
            for index in range(count.value)
            if not items[index].value.status and items[index].value.value > 0.0
        }
        if not values:
            return None
        # lock onto the busiest adapter once so the idle virtual display never wins a later sample
        if self._instance is None or self._instance not in values:
            self._instance = max(values, key=lambda key: values[key])
        return values[self._instance] / (1024.0 * 1024.0)

    def close(self) -> None:
        if self._query:
            self._pdh.PdhCloseQuery(self._query)
            self._query = ctypes.c_void_p()


class _NvidiaSmi:
    def sample(self) -> float | None:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        values = [float(line) for line in result.stdout.splitlines() if line.strip()]
        return max(values) if values else None

    def close(self) -> None:
        pass


def _open_source(arch: str):
    if arch == "cuda" and shutil.which("nvidia-smi"):
        return _NvidiaSmi()
    if arch == "vulkan" and platform.system() == "Windows":
        try:
            return _AdapterMemory()
        except OSError:
            return None
    return None


class VramSampler:
    def __init__(self, arch: str) -> None:
        self.arch = arch
        self.peak_raw: float | None = None
        self.baseline: float | None = None
        self.samples = 0
        self._source = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def peak(self) -> float | None:
        if self.peak_raw is None:
            return None
        return max(0.0, self.peak_raw - (self.baseline or 0.0))

    def __enter__(self) -> VramSampler:
        self._source = _open_source(self.arch)
        if self._source is None:
            return self
        idle = []
        for _ in range(_BASELINE_SAMPLES):
            value = self._read()
            if value is not None:
                idle.append(value)
            time.sleep(_INTERVAL)
        if idle:
            self.baseline = min(idle)
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()
        return self

    def _read(self) -> float | None:
        try:
            value = self._source.sample()
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return None
        if value is not None:
            self.samples += 1
        return value

    def _poll(self) -> None:
        while not self._stop.is_set():
            value = self._read()
            if value is not None:
                self.peak_raw = value if self.peak_raw is None else max(self.peak_raw, value)
            self._stop.wait(_INTERVAL)

    def fields(self) -> dict:
        return dict(
            vram_mb=_rounded(self.peak),
            vram_peak_mb=_rounded(self.peak),
            vram_baseline_mb=_rounded(self.baseline),
            vram_peak_raw_mb=_rounded(self.peak_raw),
            vram_samples=self.samples,
        )

    def __exit__(self, exc_type, exc, trace) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        if self._source is not None:
            self._source.close()


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 1)
