import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Union

import psutil
import pynvml

LOGGER = logging.getLogger(__name__)


@dataclass
class Percent:
    value: Union[float, int]
    formatted: str = field(init=False)
    def __post_init__(self):
        if self.value > 1:
            self.value = self.value / 100
        self.formatted = f"{100 * self.value:.1f}%"


@dataclass
class CpuInfo:
    count: int
    percent: Percent


@dataclass
class Bytes:
    value: int
    mega: str = field(init=False)
    human: str = field(init=False)
    def __post_init__(self):
        self.mega = bytes2mega(self.value)
        self.human = bytes2human(self.value)


@dataclass
class Bits:
    value: int
    mega: str = field(init=False)
    human: str = field(init=False)
    def __post_init__(self):
        _bytes = math.ceil(self.value // 8)
        self.mega = bytes2mega(_bytes)
        self.human = bytes2human(_bytes)


@dataclass
class MemInfo:
    used: Bytes
    free: Bytes
    total: Bytes
    percent: Percent = field(init=False, default=None)
    def __post_init__(self):
        self.percent = Percent(round(self.used.value / self.total.value, 3))


@dataclass
class Process:
    pid: int
    device_id: int
    started: str
    username: str
    name: str
    command: str
    cpu: float
    mem: Bytes
    gpu: Bytes


@dataclass
class GpuInfo:
    i: int
    name: str
    fan_speed: int
    temperature: int
    mem: MemInfo
    util: Percent
    processes: List[Process]


@dataclass
class Info:
    cpu: CpuInfo
    mem: MemInfo
    gpus: List[GpuInfo]


def bytes2human(n, format="%(value).2f%(symbol)s"):
    units = ('B', 'k', 'm', 'G', 'T', 'P', 'E', 'Z', 'Y')
    prefix = {}
    for i, s in enumerate(units[1:]):
        prefix[s] = 1 << (i + 1) * 10
    for symbol in reversed(units[1:]):
        if abs(n) >= prefix[symbol]:
            value = float(n) / prefix[symbol]
            return format % locals()
    return format % dict(symbol=units[0], value=n)


def bytes2mega(n):
    return f"{n//1024//1024}m"


def get_cpu_info():
    return CpuInfo(count=psutil.cpu_count(), percent=Percent(psutil.cpu_percent()))


def get_mem_info():
    mem = psutil.virtual_memory()
    return MemInfo(
        used=Bytes(mem.used),
        free=Bytes(mem.available),
        total=Bytes(mem.total),
    )


def get_gpu_info():
    def get_driver_version():
        return pynvml.nvmlSystemGetDriverVersion()  # 545.23.08

    def get_cuda_version():
        version = pynvml.nvmlSystemGetCudaDriverVersion()
        return f"{version // 1000}.{version % 1000 // 10}"

    def get_mem_info(_handle):
        _mem = pynvml.nvmlDeviceGetMemoryInfo(_handle)
        return MemInfo(
            used=Bytes(_mem.used),
            free=Bytes(_mem.free),
            total=Bytes(_mem.total),
        )

    def get_processes_on_device(_handle, _device_id: int):
        _processes = []
        for proc in pynvml.nvmlDeviceGetComputeRunningProcesses(_handle):
            try:
                pid = proc.pid
                ps = psutil.Process(pid)
                _processes.append(
                    Process(
                        pid=pid,
                        device_id=_device_id,
                        started=datetime.fromtimestamp(ps.create_time()).strftime('%Y-%m-%d %H:%M:%S'),
                        username=ps.username(),
                        name=ps.name(),
                        command=' '.join(ps.cmdline()),
                        cpu=Percent(ps.cpu_percent()),
                        mem=Bytes(ps.memory_info().rss),
                        gpu=Bytes(proc.usedGpuMemory),
                    )
                )
            except psutil.NoSuchProcess:
                pass
        return _processes

    def get_gpu_info(_device_id: int):
        handle = pynvml.nvmlDeviceGetHandleByIndex(_device_id)
        return GpuInfo(
            i=_device_id,
            name=pynvml.nvmlDeviceGetName(handle),
            fan_speed=pynvml.nvmlDeviceGetFanSpeed(handle),
            temperature=pynvml.nvmlDeviceGetTemperature(handle, 0),
            mem=get_mem_info(handle),
            util=Percent(pynvml.nvmlDeviceGetUtilizationRates(handle).gpu / 100),
            processes=get_processes_on_device(handle, _device_id),
        )

    pynvml.nvmlInit()

    try:
        device_count = pynvml.nvmlDeviceGetCount()
        if device_count == 0:
            return []
        return [get_gpu_info(device_id) for device_id in range(device_count)]
    finally:
        pynvml.nvmlShutdown()


def get_info():
    return Info(
        cpu=get_cpu_info(),
        mem=get_mem_info(),
        gpus=get_gpu_info(),
    )
