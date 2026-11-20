import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT.parent / ".env")
load_dotenv(ROOT / ".env")


def _num(name, default, lo, hi, cast=float):
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        val = cast(raw)
    except ValueError:
        raise SystemExit(f"{name} harus berupa angka, diterima: {raw!r}")
    if not lo <= val <= hi:
        raise SystemExit(f"{name} harus di antara {lo} dan {hi}")
    return val


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    token: str
    interval: float
    retention_hours: int
    db_path: str
    max_ws: int


def load_config() -> Config:
    return Config(
        host=os.getenv("AUROELIC_HOST", "127.0.0.1"),
        port=_num("AUROELIC_PORT", 8000, 1, 65535, int),
        token=os.getenv("AUROELIC_TOKEN", "").strip(),
        interval=_num("AUROELIC_INTERVAL", 2.0, 1, 60),
        retention_hours=_num("AUROELIC_RETENTION_HOURS", 24, 1, 720, int),
        db_path=os.getenv("AUROELIC_DB_PATH", "auroelic.db"),
        max_ws=_num("AUROELIC_MAX_WS", 50, 1, 1000, int),
    )
