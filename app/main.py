"""Local-first FastAPI dashboard and scrape orchestration."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app import config
from app.browser import BrowserSession
from app.models import Source, SourceCreate
from app.scraper import PageBlockedError, scrape_source
from app.storage import Storage

storage = Storage(config.DATABASE_PATH)
scrape_lock = asyncio.Lock()
STATIC_DIR = Path(__file__).resolve().parent / "static"


def load_sources() -> list[Source]:
    if not config.SOURCES_PATH.exists():
        config.SOURCES_PATH.parent.mkdir(parents=True, exist_ok=True)
        config.SOURCES_PATH.write_text('{"sources": []}', encoding="utf-8")
    try:
        payload = json.loads(config.SOURCES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Kaynak yapılandırması okunamadı: {exc}") from exc
    parsed = []
    for item in payload.get("sources", []):
        try:
            parsed.append(Source.model_validate(item))
        except Exception:
            # One malformed entry must not break the local dashboard.
            continue
    return parsed


def save_sources(sources: list[Source]) -> None:
    config.SOURCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"sources": [item.model_dump(mode="json") for item in sources]}
    temporary = config.SOURCES_PATH.with_suffix(config.SOURCES_PATH.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, config.SOURCES_PATH)


class LocalOnlyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client_host = request.client.host if request.client else ""
        try:
            client_is_local = ipaddress.ip_address(client_host).is_loopback
        except ValueError:
            client_is_local = client_host == "testclient"
        host_header = (urlparse("//" + request.headers.get("host", "")).hostname or "").lower()
        allowed_hosts = {"127.0.0.1", "localhost", "::1", "testserver"}
        if not client_is_local or host_header not in allowed_hosts:
            return Response("Bu uygulama yalnızca yerel kullanım içindir.", status_code=403)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin:
                origin_host = (urlparse(origin).hostname or "").lower()
                if origin_host not in {"127.0.0.1", "localhost", "::1"}:
                    return Response("Cross-origin istek engellendi.", status_code=403)
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.init()
    config.SOURCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="Banka Kampanyaları Scraper",
    description="Açık kampanya sayfaları için yerel, salt-okunur Playwright aracı.",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(LocalOnlyMiddleware)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def dashboard():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
async def status():
    return {
        "ok": True,
        "scrape_running": scrape_lock.locked(),
        "stats": storage.stats(),
        "source_count": len(load_sources()),
        "browser_cdp": config.BROWSER_CDP_URL,
        "browser_mode": "auto-launch" if config.AUTO_LAUNCH_BROWSER else "connect-existing",
    }


@app.get("/api/sources")
async def list_sources():
    return [source.model_dump(mode="json") for source in load_sources()]


@app.post("/api/sources", status_code=201)
async def create_source(payload: SourceCreate):
    sources = load_sources()
    if any(item.campaign_url.rstrip("/") == payload.campaign_url.rstrip("/") for item in sources):
        raise HTTPException(status_code=409, detail="Bu kampanya URL'si zaten tanımlı.")
    source = Source(id=uuid.uuid4().hex[:16], **payload.model_dump())
    sources.append(source)
    save_sources(sources)
    return source.model_dump(mode="json")


@app.patch("/api/sources/{source_id}/toggle")
async def toggle_source(source_id: str):
    sources = load_sources()
    found = False
    updated = []
    for source in sources:
        if source.id == source_id:
            source = source.model_copy(update={"active": not source.active})
            found = True
        updated.append(source)
    if not found:
        raise HTTPException(status_code=404, detail="Kaynak bulunamadı.")
    save_sources(updated)
    return next(item.model_dump(mode="json") for item in updated if item.id == source_id)


@app.delete("/api/sources/{source_id}")
async def delete_source(source_id: str):
    sources = load_sources()
    updated = [source for source in sources if source.id != source_id]
    if len(updated) == len(sources):
        raise HTTPException(status_code=404, detail="Kaynak bulunamadı.")
    save_sources(updated)
    # Previously collected campaigns remain in the local database as history.
    return {"deleted": True, "source_id": source_id}


@app.get("/api/campaigns")
async def list_campaigns(limit: int = 300, source_id: str | None = None):
    return storage.campaigns(limit=limit, source_id=source_id)


@app.get("/api/runs")
async def list_runs(limit: int = 30):
    return storage.runs(limit=limit)


@app.get("/api/export")
async def export_data(format: str = "json"):
    if format.lower() == "csv":
        return Response(
            content=storage.export_csv(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="bank-campaigns.csv"'},
        )
    if format.lower() == "json":
        return Response(
            content=storage.export_json(),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="bank-campaigns.json"'},
        )
    raise HTTPException(status_code=400, detail="format csv veya json olmalı.")


@app.post("/api/scrape")
async def run_scrape():
    if scrape_lock.locked():
        raise HTTPException(status_code=409, detail="Bir tarama zaten çalışıyor.")
    await scrape_lock.acquire()
    run_id = uuid.uuid4().hex
    details: list[dict] = []
    session = BrowserSession()
    run_created = False
    overall_status = "failed"
    try:
        active_sources = [source for source in load_sources() if source.active]
        storage.create_run(run_id, len(active_sources))
        run_created = True
        if not active_sources:
            message = "Etkin kaynak bulunamadı. Önce bir kampanya URL'si ekleyip etkinleştirin."
            storage.finish_run(run_id, "failed", [])
            return {"run_id": run_id, "status": "failed", "details": [], "message": message}
        try:
            context = await session.start()
        except Exception as exc:
            details = [{
                "source_id": source.id,
                "bank_name": source.bank_name,
                "status": "error",
                "found": 0,
                "saved": 0,
                "message": str(exc)[:500],
            } for source in active_sources]
            overall_status = "failed"
        else:
            for source in active_sources:
                try:
                    campaigns = await scrape_source(context, source)
                    saved = storage.save_campaigns(campaigns)
                    details.append({
                        "source_id": source.id,
                        "bank_name": source.bank_name,
                        "status": "success",
                        "found": len(campaigns),
                        "saved": saved,
                        "message": "Tamamlandı" if campaigns else "Sayfada kampanya kartı bulunamadı; seçicileri kontrol edin.",
                    })
                except PageBlockedError as exc:
                    details.append({
                        "source_id": source.id, "bank_name": source.bank_name, "status": "blocked",
                        "found": 0, "saved": 0, "message": str(exc)[:500],
                    })
                except Exception as exc:
                    details.append({
                        "source_id": source.id, "bank_name": source.bank_name, "status": "error",
                        "found": 0, "saved": 0, "message": f"{type(exc).__name__}: {exc}"[:500],
                    })
                await asyncio.sleep(config.PAGE_DELAY_SECONDS)
            succeeded = sum(item["status"] == "success" for item in details)
            overall_status = "success" if succeeded == len(details) else ("partial" if succeeded else "failed")
        storage.finish_run(run_id, overall_status, details)
        return {"run_id": run_id, "status": overall_status, "details": details}
    except Exception:
        if run_created:
            storage.finish_run(run_id, "failed", details)
        raise
    finally:
        await session.close()
        scrape_lock.release()


if __name__ == "__main__":
    import uvicorn

    if config.HOST not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Güvenlik nedeniyle HOST yalnızca loopback olabilir.")
    uvicorn.run(app, host=config.HOST, port=config.PORT)
