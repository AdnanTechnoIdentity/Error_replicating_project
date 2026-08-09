import json
import logging
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from state import app_state

logger = logging.getLogger("nexusshop.users")
router = APIRouter(prefix="/users", tags=["users"])


def _log(level: str, event: str, trace_id: str = "-", **fields) -> None:
    payload = json.dumps({"event": event, "trace_id": trace_id, "service": "users", **fields}, default=str)
    getattr(logger, level)(payload)


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
async def login(body: LoginRequest, request: Request):
    trace_id = getattr(request.state, "trace_id", "-")
    svc = app_state.services["users"]
    scenario = svc.active_scenario

    _log("info", "login_attempt", trace_id, email=body.email, active_scenario=scenario)

    if scenario == "auth_failure":
        _log("error", "login_blocked_auth_failure", trace_id, email=body.email,
             reason="JWT signature verification failed — signing key mismatch")
        raise HTTPException(status_code=401, detail="JWT signature verification failed")

    if scenario in ("cascade_failure", "disk_full"):
        _log("error", "login_blocked_scenario", trace_id, scenario=scenario)
        raise HTTPException(status_code=503, detail=f"Service unavailable — {scenario}")

    user = next((u for u in app_state.users.values() if u["email"] == body.email), None)
    if not user:
        _log("warning", "login_user_not_found", trace_id, email=body.email)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    fake_token = f"eyJ.demo.{uuid.uuid4().hex}"
    _log("info", "login_success", trace_id, user_id=user["id"])
    return {"token": fake_token, "user_id": user["id"]}


@router.get("/health")
async def users_health():
    svc = app_state.services["users"]
    return {"service": "users", "status": svc.status}


@router.get("/{user_id}")
async def get_user(user_id: str, request: Request):
    trace_id = getattr(request.state, "trace_id", "-")
    svc = app_state.services["users"]

    if svc.active_scenario == "auth_failure":
        _log("error", "get_user_blocked_auth_failure", trace_id, user_id=user_id)
        raise HTTPException(status_code=401, detail="JWT signature verification failed")

    if svc.active_scenario in ("cascade_failure", "disk_full"):
        _log("error", "get_user_blocked_scenario", trace_id, scenario=svc.active_scenario)
        raise HTTPException(status_code=503, detail=f"Service unavailable — {svc.active_scenario}")

    user = app_state.users.get(user_id)
    if not user:
        _log("warning", "user_not_found", trace_id, user_id=user_id)
        raise HTTPException(status_code=404, detail="User not found")

    _log("info", "user_fetched", trace_id, user_id=user_id)
    return user
