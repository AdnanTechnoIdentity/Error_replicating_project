import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

load_dotenv()


class _JSONFormatter(logging.Formatter):
    """One JSON object per stdout line — machine-parseable by Nexus log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        obj: dict = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ("event", "service", "scenario", "severity",
                    "trace_id", "duration_ms", "status_code", "method", "path"):
            val = getattr(record, key, None)
            if val is not None:
                obj[key] = val
        if record.exc_info:
            obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(obj, default=str)


def _setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JSONFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


_setup_logging()

from state import app_state
from routers import payments, orders, users
from chaos.controller import router as chaos_router

_logger = logging.getLogger("nexusshop.core")


class _RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = uuid.uuid4().hex[:8]
        request.state.trace_id = trace_id
        start = time.perf_counter()

        _logger.info("request_start", extra={
            "event": "request_start", "trace_id": trace_id,
            "method": request.method, "path": request.url.path,
        })

        try:
            response: Response = await call_next(request)
        except Exception as exc:
            elapsed = round((time.perf_counter() - start) * 1000, 1)
            _logger.error("request_unhandled_exception", exc_info=exc, extra={
                "event": "request_unhandled_exception", "trace_id": trace_id,
                "method": request.method, "path": request.url.path, "duration_ms": elapsed,
            })
            raise

        elapsed = round((time.perf_counter() - start) * 1000, 1)
        status = response.status_code
        log_level = "error" if status >= 500 else "warning" if status >= 400 else "info"
        getattr(_logger, log_level)("request_end", extra={
            "event": "request_end", "trace_id": trace_id,
            "method": request.method, "path": request.url.path,
            "status_code": status, "duration_ms": elapsed,
        })
        response.headers["X-Trace-Id"] = trace_id
        return response


app = FastAPI(title="NexusShop Demo API", version="1.0.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(_RequestLogMiddleware)

app.include_router(payments.router)
app.include_router(orders.router)
app.include_router(users.router)
app.include_router(chaos_router)


@app.get("/state")
async def get_state():
    return app_state.to_dict()


@app.get("/health")
async def root_health():
    return {"status": "ok", "app": "NexusShop"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("APP_HOST", "0.0.0.0"),
        port=int(os.getenv("APP_PORT", "9000")),
        reload=False,
    )
