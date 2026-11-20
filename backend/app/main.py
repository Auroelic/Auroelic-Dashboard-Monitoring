import asyncio
import logging
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .alerts import AlertEngine
from .collector import Collector
from .config import load_config
from .schemas import Thresholds
from .store import RANGES, Store

log = logging.getLogger("auroelic")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

cfg = load_config()
store = Store(cfg.db_path, cfg.retention_hours)
collector = Collector()
engine = AlertEngine(store, store.get_thresholds())
state = {"latest": None}


class Hub:
    def __init__(self):
        self.clients = set()

    async def broadcast(self, msg):
        dead = []
        for ws in list(self.clients):
            try:
                await asyncio.wait_for(ws.send_json(msg), 2)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


hub = Hub()


async def sampler():
    last_prune = 0
    while True:
        t0 = time.monotonic()
        try:
            snap = await asyncio.to_thread(collector.sample)
            values = {"cpu": snap["cpu"]["percent"], "mem": snap["mem"]["percent"], "disk": snap["disk"]["percent"]}
            events = await asyncio.to_thread(
                engine.evaluate, snap["ts"], values, lambda m: collector.cause(m, snap))
            snap["status"] = engine.status()
            snap["interval"] = cfg.interval
            store.add_sample(snap["ts"], values["cpu"], values["mem"], values["disk"],
                             snap["net"]["rx_rate"], snap["net"]["tx_rate"])
            state["latest"] = snap
            await hub.broadcast({"type": "snapshot", "data": snap})
            for ev in events:
                await hub.broadcast({"type": "alert", "data": ev})
            if t0 - last_prune > 3600:
                last_prune = t0
                store.prune()
        except Exception:
            log.exception("Gagal mengambil sampel")
        await asyncio.sleep(max(0.1, cfg.interval - (time.monotonic() - t0)))


@asynccontextmanager
async def lifespan(_):
    task = asyncio.create_task(sampler())
    yield
    task.cancel()


app = FastAPI(title="Auroelic", docs_url=None, redoc_url=None, lifespan=lifespan)


def token_ok(provided):
    return not cfg.token or (bool(provided) and secrets.compare_digest(provided, cfg.token))


async def auth(request: Request):
    h = request.headers.get("authorization", "")
    tok = h[7:] if h.lower().startswith("bearer ") else request.headers.get("x-api-key", "")
    if not token_ok(tok):
        raise HTTPException(401, "Token tidak valid atau belum diisi")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.update({
        "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                                   "font-src https://fonts.gstatic.com; connect-src 'self' ws: wss:; img-src 'self' data:",
    })
    if request.url.path.startswith("/api"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.exception_handler(Exception)
async def unhandled(_, exc):
    log.exception("Error tidak tertangani: %s", exc)
    return JSONResponse({"detail": "Terjadi kesalahan internal"}, status_code=500)


@app.get("/api/health")
async def health():
    latest = state["latest"]
    age = time.time() - latest["ts"] if latest else None
    return {"app": "Auroelic", "ok": age is not None and age < cfg.interval * 5, "sample_age": age,
            "auth_required": bool(cfg.token)}


@app.get("/api/snapshot", dependencies=[Depends(auth)])
async def snapshot():
    if not state["latest"]:
        raise HTTPException(503, "Sampel pertama belum tersedia")
    return state["latest"]


@app.get("/api/system", dependencies=[Depends(auth)])
async def system():
    return collector.system()


@app.get("/api/history", dependencies=[Depends(auth)])
async def history(range: str = Query("5m", pattern="^(5m|1h|6h|24h)$")):
    return {"range": range, "points": await asyncio.to_thread(store.history, RANGES[range])}


@app.get("/api/alerts", dependencies=[Depends(auth)])
async def alerts(status: str = Query("all", pattern="^(all|open|resolved)$"), limit: int = Query(30, ge=1, le=200)):
    return {"alerts": await asyncio.to_thread(store.alerts, status, limit)}


@app.get("/api/settings", dependencies=[Depends(auth)])
async def get_settings():
    return engine.t


@app.put("/api/settings", dependencies=[Depends(auth)])
async def put_settings(body: Thresholds):
    store.set_thresholds(body)
    engine.t = body.model_dump()
    return engine.t


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    if not token_ok(ws.query_params.get("token", "")) or len(hub.clients) >= cfg.max_ws:
        await ws.close(code=4401)
        return
    await ws.accept()
    hub.clients.add(ws)
    try:
        if state["latest"]:
            await ws.send_json({"type": "snapshot", "data": state["latest"]})
        while True:
            await ws.receive_text()  # klien mengirim ping berkala
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(ws)


app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[2] / "frontend", html=True), name="ui")
