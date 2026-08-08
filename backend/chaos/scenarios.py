"""All 8 chaos scenario implementations."""
import asyncio
import logging
from typing import Optional

from state import app_state
from webhook.sender import send_webhook

logger = logging.getLogger(__name__)

AUTO_RECOVERY_SECONDS = 90

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _mark_service(service: str, status: str, scenario: str, error_rate: float,
                  response_time_ms: int, db_connections: int) -> None:
    svc = app_state.services[service]
    svc.status = status
    svc.active_scenario = scenario
    svc.error_rate = error_rate
    svc.response_time_ms = response_time_ms
    svc.db_connections = db_connections


async def _schedule_auto_recovery(service: str, delay: int = AUTO_RECOVERY_SECONDS) -> None:
    await asyncio.sleep(delay)
    if app_state.services[service].active_scenario:
        _cleanup_service(service)
        app_state.recover(service)
        logger.info("Auto-recovered service: %s", service)


def _cleanup_service(service: str) -> None:
    """Cancel background tasks and release events for a service."""
    for task in app_state.background_tasks.get(service, []):
        task.cancel()
    app_state.background_tasks[service] = []

    ev = app_state._release_events.get(service)
    if ev:
        ev.set()
    app_state._release_events[service] = None

    if service == "orders":
        app_state._memory_holder = None


def cleanup_and_recover(service: str) -> None:
    _cleanup_service(service)
    app_state.recover(service)


# ──────────────────────────────────────────────
# Scenario 1 — db_timeout
# ──────────────────────────────────────────────

async def scenario_db_timeout(service: str) -> None:
    _mark_service(service, "CRITICAL", "db_timeout", 0.97, 30412, 1)
    app_state.add_error(service, "db_timeout", "HIGH",
                        "Database connection timeout after 30s")

    webhook_sent = await send_webhook(
        service=service,
        scenario="db_timeout",
        error=f"Database connection timeout after 30s — {service}_db unreachable",
        severity="HIGH",
        metadata={
            "timeout_ms": 30000,
            "db_host": f"{service}-db.internal",
            "affected_endpoints": [f"/{service}/charge", f"/{service}/status"],
        },
    )
    logger.info("db_timeout triggered, webhook_sent=%s", webhook_sent)

    release = asyncio.Event()
    app_state._release_events[service] = release

    async def _hold_connection():
        try:
            await asyncio.wait_for(release.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass

    t = asyncio.create_task(_hold_connection())
    app_state.background_tasks[service].append(t)

    recovery_task = asyncio.create_task(_schedule_auto_recovery(service))
    app_state.recovery_tasks[service] = recovery_task


# ──────────────────────────────────────────────
# Scenario 2 — db_pool_exhausted
# ──────────────────────────────────────────────

async def scenario_db_pool_exhausted(service: str) -> None:
    _mark_service(service, "CRITICAL", "db_pool_exhausted", 0.99, 5000, 50)
    app_state.add_error(service, "db_pool_exhausted", "HIGH",
                        "Database connection pool exhausted — 50/50 connections in use")

    webhook_sent = await send_webhook(
        service=service,
        scenario="db_pool_exhausted",
        error="Database connection pool exhausted — 50/50 connections in use",
        severity="HIGH",
        metadata={
            "connections_active": 50,
            "connections_max": 50,
            "wait_queue_depth": 127,
            "affected_service": service,
        },
    )
    logger.info("db_pool_exhausted triggered, webhook_sent=%s", webhook_sent)

    release = asyncio.Event()
    app_state._release_events[service] = release

    lock = asyncio.Lock()

    async def _hold_fake_connection(_i: int):
        async with lock:
            try:
                await release.wait()
            except asyncio.CancelledError:
                pass

    tasks = [asyncio.create_task(_hold_fake_connection(i)) for i in range(50)]
    app_state.background_tasks[service].extend(tasks)

    recovery_task = asyncio.create_task(_schedule_auto_recovery(service))
    app_state.recovery_tasks[service] = recovery_task


# ──────────────────────────────────────────────
# Scenario 3 — api_gateway_timeout
# ──────────────────────────────────────────────

async def scenario_api_gateway_timeout(service: str) -> None:
    _mark_service(service, "CRITICAL", "api_gateway_timeout", 0.95, 65000, 3)
    app_state.add_error(service, "api_gateway_timeout", "HIGH",
                        "API gateway timeout — upstream payments service not responding (>60s)")

    webhook_sent = await send_webhook(
        service=service,
        scenario="api_gateway_timeout",
        error=f"API gateway timeout — upstream {service} service not responding (>60s)",
        severity="HIGH",
        metadata={
            "gateway_timeout_ms": 60000,
            "upstream": f"{service}-service",
            "error_code": "UPSTREAM_TIMEOUT",
        },
    )
    logger.info("api_gateway_timeout triggered, webhook_sent=%s", webhook_sent)

    recovery_task = asyncio.create_task(_schedule_auto_recovery(service))
    app_state.recovery_tasks[service] = recovery_task


# ──────────────────────────────────────────────
# Scenario 4 — auth_failure
# ──────────────────────────────────────────────

async def scenario_auth_failure(service: str) -> None:
    _mark_service(service, "DEGRADED", "auth_failure", 0.98, 120, 3)
    app_state.add_error(service, "auth_failure", "MEDIUM",
                        "Mass authentication failures — 401 rate spiked to 98%")

    webhook_sent = await send_webhook(
        service=service,
        scenario="auth_failure",
        error="Mass authentication failures — 401 rate spiked to 98% of requests",
        severity="MEDIUM",
        metadata={
            "error_rate_401": 0.98,
            "affected_endpoints": ["/users/login", "/orders/create"],
            "failure_reason": "JWT signature verification failed",
        },
    )
    logger.info("auth_failure triggered, webhook_sent=%s", webhook_sent)

    recovery_task = asyncio.create_task(_schedule_auto_recovery(service))
    app_state.recovery_tasks[service] = recovery_task


# ──────────────────────────────────────────────
# Scenario 5 — memory_spike
# ──────────────────────────────────────────────

async def scenario_memory_spike(service: str) -> None:
    _mark_service(service, "DEGRADED", "memory_spike", 0.15, 2400, 4)
    app_state.add_error(service, "memory_spike", "MEDIUM",
                        "Memory spike detected — heap utilization at 94%, OOM risk")

    # Allocate 500 MB and pin it so GC cannot collect
    app_state._memory_holder = bytearray(500 * 1024 * 1024)

    webhook_sent = await send_webhook(
        service=service,
        scenario="memory_spike",
        error="Memory spike detected — heap utilization at 94%, OOM risk",
        severity="MEDIUM",
        metadata={
            "heap_used_mb": 960,
            "heap_max_mb": 1024,
            "heap_percent": 93.75,
            "service": service,
        },
    )
    logger.info("memory_spike triggered, webhook_sent=%s", webhook_sent)

    recovery_task = asyncio.create_task(_schedule_auto_recovery(service))
    app_state.recovery_tasks[service] = recovery_task


# ──────────────────────────────────────────────
# Scenario 6 — payment_failure
# ──────────────────────────────────────────────

async def scenario_payment_failure(service: str) -> None:
    _mark_service(service, "CRITICAL", "payment_failure", 1.0, 210, 4)
    app_state.add_error(service, "payment_failure", "HIGH",
                        "Payment processing failure — gateway returning PG_503 on all transactions")

    webhook_sent = await send_webhook(
        service=service,
        scenario="payment_failure",
        error="Payment processing failure — gateway returning PG_503 on all transactions",
        severity="HIGH",
        metadata={
            "gateway_error_code": "PG_503",
            "failed_transactions": 47,
            "revenue_at_risk_usd": 14230.00,
        },
    )
    logger.info("payment_failure triggered, webhook_sent=%s", webhook_sent)

    recovery_task = asyncio.create_task(_schedule_auto_recovery(service))
    app_state.recovery_tasks[service] = recovery_task


# ──────────────────────────────────────────────
# Scenario 7 — deadlock
# ──────────────────────────────────────────────

async def scenario_deadlock(service: str) -> None:
    _mark_service(service, "DEGRADED", "deadlock", 0.60, 15000, 4)
    app_state.add_error(service, "deadlock", "MEDIUM",
                        "Database deadlock detected — orders table write operations blocking")

    webhook_sent = await send_webhook(
        service=service,
        scenario="deadlock",
        error="Database deadlock detected — orders table write operations blocking",
        severity="MEDIUM",
        metadata={
            "table": "orders",
            "lock_wait_ms": 15000,
            "deadlock_count": 3,
            "affected_queries": ["INSERT INTO orders", "UPDATE inventory"],
        },
    )
    logger.info("deadlock triggered, webhook_sent=%s", webhook_sent)

    lock_a = asyncio.Lock()
    lock_b = asyncio.Lock()

    async def _task_a():
        async with lock_a:
            await asyncio.sleep(0.1)
            try:
                await asyncio.wait_for(lock_b.acquire(), timeout=15)
                lock_b.release()
            except (asyncio.TimeoutError, asyncio.CancelledError):
                logger.debug("Deadlock task_a timed out (expected)")

    async def _task_b():
        async with lock_b:
            await asyncio.sleep(0.1)
            try:
                await asyncio.wait_for(lock_a.acquire(), timeout=15)
                lock_a.release()
            except (asyncio.TimeoutError, asyncio.CancelledError):
                logger.debug("Deadlock task_b timed out (expected)")

    t_a = asyncio.create_task(_task_a())
    t_b = asyncio.create_task(_task_b())
    app_state.background_tasks[service].extend([t_a, t_b])

    recovery_task = asyncio.create_task(_schedule_auto_recovery(service))
    app_state.recovery_tasks[service] = recovery_task


# ──────────────────────────────────────────────
# Scenario 8 — rate_limit
# ──────────────────────────────────────────────

async def scenario_rate_limit(service: str) -> None:
    _mark_service(service, "DEGRADED", "rate_limit", 0.45, 180, 3)
    app_state.add_error(service, "rate_limit", "LOW",
                        "Rate limit exceeded — downstream fraud-check API returning 429")

    webhook_sent = await send_webhook(
        service=service,
        scenario="rate_limit",
        error="Rate limit exceeded — downstream fraud-check API returning 429",
        severity="LOW",
        metadata={
            "downstream_service": "fraud-check-api",
            "requests_throttled": 89,
            "retry_after_seconds": 60,
        },
    )
    logger.info("rate_limit triggered, webhook_sent=%s", webhook_sent)

    recovery_task = asyncio.create_task(_schedule_auto_recovery(service))
    app_state.recovery_tasks[service] = recovery_task


# ──────────────────────────────────────────────
# Dispatch table
# ──────────────────────────────────────────────

SCENARIOS = {
    "db_timeout": scenario_db_timeout,
    "db_pool_exhausted": scenario_db_pool_exhausted,
    "api_gateway_timeout": scenario_api_gateway_timeout,
    "auth_failure": scenario_auth_failure,
    "memory_spike": scenario_memory_spike,
    "payment_failure": scenario_payment_failure,
    "deadlock": scenario_deadlock,
    "rate_limit": scenario_rate_limit,
}
