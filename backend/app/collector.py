import os
import platform
import socket
import time

import psutil

SKIP_FS = {"squashfs", "tmpfs", "devtmpfs", "devfs", "iso9660", "proc", "sysfs", "cgroup", "cgroup2"}


class Collector:
    def __init__(self, disk_interval=10):
        self.disk_interval = disk_interval
        psutil.cpu_percent(None)
        self._net, self._net_t = self._net_counters(), time.monotonic()
        self._disk, self._disk_t = None, 0
        self._procs = {}
        self.boot_time = psutil.boot_time()
        self.static = self._static_info()

    @staticmethod
    def _net_counters():
        rx = tx = 0
        for name, c in psutil.net_io_counters(pernic=True).items():
            if not name.startswith("lo"):
                rx += c.bytes_recv
                tx += c.bytes_sent
        return rx, tx

    @staticmethod
    def _ip():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("10.255.255.255", 1))  # sends no packets, only selects the interface
                return s.getsockname()[0]
        except OSError:
            for addrs in psutil.net_if_addrs().values():
                for a in addrs:
                    if a.family == socket.AF_INET and not a.address.startswith("127."):
                        return a.address
            return "127.0.0.1"

    def _static_info(self):
        model = platform.processor() or platform.machine()
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.lower().startswith("model name"):
                        model = line.split(":", 1)[1].strip()
                        break
        except OSError:
            pass
        try:
            os_name = platform.freedesktop_os_release().get("PRETTY_NAME")
        except (OSError, AttributeError):
            os_name = None
        freq = psutil.cpu_freq()
        return {
            "hostname": socket.gethostname(),
            "os": os_name or platform.platform(),
            "kernel": platform.release(),
            "arch": platform.machine(),
            "cpu_model": model,
            "cores_logical": psutil.cpu_count(logical=True),
            "cores_physical": psutil.cpu_count(logical=False) or psutil.cpu_count(logical=True),
            "cpu_max_mhz": round(freq.max or freq.current) if freq else None,
            "ram_total": psutil.virtual_memory().total,
            "boot_time": self.boot_time,
        }

    def system(self):
        return {**self.static, "ip": self._ip()}

    def _disks(self):
        now = time.monotonic()
        if self._disk and now - self._disk_t < self.disk_interval:
            return self._disk
        parts, seen = [], set()
        for p in psutil.disk_partitions(all=False):
            if p.fstype in SKIP_FS or p.device in seen:
                continue
            try:
                u = psutil.disk_usage(p.mountpoint)
            except OSError:
                continue  # unreadable partition: skipped, never faked
            if u.total:
                seen.add(p.device)
                parts.append({"device": p.device, "mountpoint": p.mountpoint, "fstype": p.fstype,
                              "total": u.total, "used": u.used, "free": u.free, "percent": u.percent})
        if not parts:
            u = psutil.disk_usage("/")
            parts = [{"device": "/", "mountpoint": "/", "fstype": "-", "total": u.total, "used": u.used,
                      "free": u.free, "percent": u.percent}]
        total, used = sum(p["total"] for p in parts), sum(p["used"] for p in parts)
        free = sum(p["free"] for p in parts)
        # percentage uses the psutil/df formula: used / (used + free), consistent with `df`
        self._disk = {"total": total, "used": used, "free": free,
                      "percent": round(used / (used + free) * 100, 1) if used + free else 0.0, "partitions": parts}
        self._disk_t = now
        return self._disk

    def sample(self):
        ts, mono = time.time(), time.monotonic()
        vm, sw = psutil.virtual_memory(), psutil.swap_memory()
        rx, tx = self._net_counters()
        dt = max(mono - self._net_t, 1e-3)
        rx_rate, tx_rate = max(0, rx - self._net[0]) / dt, max(0, tx - self._net[1]) / dt
        self._net, self._net_t = (rx, tx), mono
        try:
            load = [round(x, 2) for x in os.getloadavg()]
        except (AttributeError, OSError):
            load = None
        freq = psutil.cpu_freq()
        return {
            "ts": ts,
            "cpu": {"percent": psutil.cpu_percent(None), "per_core": psutil.cpu_percent(None, percpu=True),
                    "load": load, "freq_mhz": round(freq.current) if freq else None,
                    "cores_logical": self.static["cores_logical"], "cores_physical": self.static["cores_physical"]},
            "mem": {"total": vm.total, "used": vm.total - vm.available, "available": vm.available,
                    "percent": round((vm.total - vm.available) / vm.total * 100, 1),
                    "swap_total": sw.total, "swap_used": sw.used},
            "disk": self._disks(),
            "net": {"rx_rate": rx_rate, "tx_rate": tx_rate, "rx_total": rx, "tx_total": tx},
            "uptime": {"boot_time": self.boot_time, "seconds": ts - self.boot_time},
        }

    def top_processes(self, by="cpu", n=3):
        key = "cpu_percent" if by == "cpu" else "memory_percent"
        if by == "cpu":  # per-process CPU needs two measurement points; the first call always returns 0.0
            for p in psutil.process_iter():
                try:
                    self._procs.setdefault(p.pid, p).cpu_percent()
                except (psutil.Error, OSError):
                    pass
            time.sleep(0.5)
        alive, rows = set(), []
        for p in psutil.process_iter():
            alive.add(p.pid)
            proc = self._procs.setdefault(p.pid, p)
            try:
                rows.append((getattr(proc, key)(), proc.name()))
            except (psutil.Error, OSError):
                continue
        self._procs = {k: v for k, v in self._procs.items() if k in alive}
        rows.sort(reverse=True)
        return ", ".join(f"{name} ({v:.1f}%)" for v, name in rows[:n])

    def cause(self, metric, snap):
        if metric in ("cpu", "mem"):
            return "Top processes: " + self.top_processes(metric)
        worst = max(snap["disk"]["partitions"], key=lambda p: p["percent"])
        return f"Partition {worst['mountpoint']} is {worst['percent']:.1f}% full"
