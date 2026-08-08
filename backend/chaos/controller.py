import os
import logging
from typing import Literal, Union

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from state import app_state
from chaos.scenarios import SCENARIOS, cleanup_and_recover, AUTO_RECOVERY_SECONDS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chaos", tags=["chaos"])

CHAOS_SECRET = os.getenv("CHAOS_SECRET", "chaos-panel-secret")

ServiceName = Literal["payments", "orders", "users"]
VALID_SERVICES = {"payments", "orders", "users"}


def _require_key(x_chaos_key: str = Header(default="")) -> None:
    if x_chaos_key != CHAOS_SECRET:
        raise HTTPException(status_code=403, detail="Invalid chaos key")


class TriggerRequest(BaseModel):
    service: str
    scenario: str


class RecoverRequest(BaseModel):
    service: Union[str, Literal["all"]]


@router.post("/trigger")
async def trigger_chaos(body: TriggerRequest, x_chaos_key: str = Header(default="")):
    _require_key(x_chaos_key)

    if body.service not in VALID_SERVICES:
        raise HTTPException(status_code=400, detail=f"Unknown service: {body.service}")

    handler = SCENARIOS.get(body.scenario)
    if not handler:
        raise HTTPException(status_code=400, detail=f"Unknown scenario: {body.scenario}")

    # Cancel any existing recovery for this service before starting a new scenario
    old_recovery = app_state.recovery_tasks.get(body.service)
    if old_recovery and not old_recovery.done():
        old_recovery.cancel()
    cleanup_and_recover(body.service)

    await handler(body.service)

    return {
        "triggered": True,
        "service": body.service,
        "scenario": body.scenario,
        "webhook_sent": True,
        "auto_recovery_in_seconds": AUTO_RECOVERY_SECONDS,
    }


@router.post("/recover")
async def recover_chaos(body: RecoverRequest, x_chaos_key: str = Header(default="")):
    _require_key(x_chaos_key)

    targets = list(VALID_SERVICES) if body.service == "all" else [body.service]

    for svc in targets:
        if svc not in VALID_SERVICES:
            raise HTTPException(status_code=400, detail=f"Unknown service: {svc}")
        old_recovery = app_state.recovery_tasks.get(svc)
        if old_recovery and not old_recovery.done():
            old_recovery.cancel()
        cleanup_and_recover(svc)

    return {"recovered": targets}
