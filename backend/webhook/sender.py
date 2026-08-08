import hmac
import hashlib
import json
import os
import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

NEXUS_WEBHOOK_URL = os.getenv("NEXUS_WEBHOOK_URL", "http://localhost:8000/api/incidents/ingest")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "nexus-demo-secret-change-me")


def _sign(payload: dict) -> str:
    body = json.dumps(payload, separators=(",", ":"))
    sig = hmac.new(WEBHOOK_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"sha256={sig}"


async def send_webhook(
    service: str,
    scenario: str,
    error: str,
    severity: str,
    metadata: dict,
) -> bool:
    payload = {
        "service": service,
        "project": service,
        "error": error,
        "severity": severity,
        "scenario": scenario,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metadata": metadata,
    }
    headers = {
        "Content-Type": "application/json",
        "X-Nexus-Signature": _sign(payload),
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(NEXUS_WEBHOOK_URL, json=payload, headers=headers)
            resp.raise_for_status()
            logger.info("Webhook sent: %s/%s → %s", service, scenario, resp.status_code)
            return True
    except Exception as exc:
        logger.warning("Webhook delivery failed: %s", exc)
        return False
