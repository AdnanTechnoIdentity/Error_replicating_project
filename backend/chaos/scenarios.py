"""All chaos scenario implementations with structured logging."""
import asyncio
import json
import logging
import os
import random
import uuid as _uuid

from state import app_state
from webhook.sender import send_webhook

logger = logging.getLogger("nexusshop.chaos")

AUTO_RECOVERY_SECONDS = 90

# ── Realistic fake users / products for traffic simulation ────────────────────

_FAKE_USERS = [
    {"user_id": "U-001", "email": "alice.johnson@gmail.com",  "card_token": "tok_visa_4242"},
    {"user_id": "U-007", "email": "robert.chen@hotmail.com",  "card_token": "tok_mc_5500"},
    {"user_id": "U-019", "email": "sarah.williams@yahoo.com", "card_token": "tok_visa_4111"},
    {"user_id": "U-042", "email": "david.kumar@outlook.com",  "card_token": "tok_amex_3782"},
    {"user_id": "U-103", "email": "emma.rodriguez@gmail.com", "card_token": "tok_mc_5105"},
    {"user_id": "U-217", "email": "james.okafor@icloud.com",  "card_token": "tok_visa_4000"},
]

_FAKE_ITEMS = [
    {"sku": "SKU-SHOE-001",  "name": "Air Runner Pro",    "price": 149.99},
    {"sku": "SKU-WATCH-003", "name": "Smart Series X",    "price": 299.99},
    {"sku": "SKU-SHIRT-007", "name": "Merino Wool Tee",   "price":  59.99},
    {"sku": "SKU-BAG-012",   "name": "Leather Tote",      "price":  89.99},
    {"sku": "SKU-HDPH-021",  "name": "NC Headphones Pro", "price": 249.99},
]

# Full Python tracebacks — Nexus log-agent parses these to identify root cause file/line
_TRACEBACKS: dict = {
    "db_timeout": (
        "Traceback (most recent call last):\n"
        '  File "/app/routers/payments.py", line 47, in charge\n'
        "    result = await db_pool.execute(\n"
        '        "INSERT INTO transactions (id, user_id, amount, status) VALUES (%s,%s,%s,%s)",\n'
        '        [txn_id, body.user_id, body.amount, "PENDING"],\n'
        "    )\n"
        '  File "/app/database/pool.py", line 134, in execute\n'
        "    conn = await self._pool.acquire(timeout=self._timeout)\n"
        '  File "/app/database/pool.py", line 89, in acquire\n'
        '    raise asyncio.TimeoutError(\n'
        '        f"Could not acquire DB connection after {timeout * 1000:.0f}ms"\n'
        "    )\n"
        "asyncio.TimeoutError: Could not acquire DB connection after 30000ms"
    ),
    "db_pool_exhausted": (
        "Traceback (most recent call last):\n"
        '  File "/app/routers/payments.py", line 47, in charge\n'
        "    async with db_pool.acquire() as conn:\n"
        '  File "/app/database/pool.py", line 201, in __aenter__\n'
        "    self._conn = await self._pool.acquire(timeout=5.0)\n"
        '  File "/app/database/pool.py", line 89, in acquire\n'
        "    raise PoolExhaustedError(\n"
        '        f"All {self.maxsize} connections in use. Queue depth: {len(self._waiters)}"\n'
        "    )\n"
        "PoolExhaustedError: All 50 connections in use. Queue depth: 127"
    ),
    "api_gateway_timeout": (
        "Traceback (most recent call last):\n"
        '  File "/app/middleware/timeout.py", line 23, in __call__\n'
        "    response = await asyncio.wait_for(\n"
        "        self.app(scope, receive, send), timeout=60.0\n"
        "    )\n"
        "asyncio.TimeoutError: Request timed out after 60.0s\n"
        "\nDuring handling of the above exception, another exception occurred:\n\n"
        '  File "/app/middleware/timeout.py", line 31, in __call__\n'
        '    raise GatewayTimeoutError(f"Upstream {upstream!r} did not respond within 60s")\n'
        "GatewayTimeoutError: Upstream 'payments-service' did not respond within 60s"
    ),
    "auth_failure": (
        "Traceback (most recent call last):\n"
        '  File "/app/middleware/auth.py", line 56, in verify_token\n'
        '    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])\n'
        '  File "/usr/local/lib/python3.12/site-packages/jwt/api_jwt.py", line 168, in decode\n'
        "    self._validate_signature(tdata, signing_input, header, key)\n"
        '  File "/usr/local/lib/python3.12/site-packages/jwt/api_jws.py", line 280, in _validate_signature\n'
        '    raise InvalidSignatureError("Signature verification failed")\n'
        "jwt.exceptions.InvalidSignatureError: Signature verification failed"
    ),
    "memory_spike": (
        "Traceback (most recent call last):\n"
        '  File "/app/workers/analytics.py", line 312, in build_dashboard_report\n'
        "    self._cache.extend(self._fetch_all_orders(date_range))\n"
        '  File "/app/workers/analytics.py", line 289, in _fetch_all_orders\n'
        "    return [Order.from_dict(r) for r in cursor.fetchall()]\n"
        '  File "/app/models/order.py", line 78, in from_dict\n'
        "    return cls(**data, _computed=cls._run_enrichment(data))\n"
        "MemoryError: Unable to allocate 512.0 MiB for array with shape (67108864,) and data type float64\n"
        "Process RSS: 960 MiB / 1024 MiB limit — OOM kill imminent"
    ),
    "payment_failure": (
        "Traceback (most recent call last):\n"
        '  File "/app/routers/payments.py", line 61, in charge\n'
        "    result = await payment_gateway.charge(\n"
        "        amount=body.amount, currency=body.currency, card_token=body.card_token\n"
        "    )\n"
        '  File "/app/integrations/payment_gateway.py", line 93, in charge\n'
        "    response = await self._http.post(self.endpoint, json=payload, timeout=10.0)\n"
        '  File "/app/integrations/payment_gateway.py", line 112, in _handle_response\n'
        '    raise GatewayError(code="PG_503", http_status=response.status_code,\n'
        '                       message=response.json().get("error"))\n'
        "GatewayError: [PG_503] Payment processor unavailable — upstream returned 503 Service Unavailable"
    ),
    "deadlock": (
        "Traceback (most recent call last):\n"
        '  File "/app/routers/orders.py", line 58, in create_order\n'
        "    async with db.transaction() as tx:\n"
        '        await tx.execute("INSERT INTO orders (id, user_id, total, status) VALUES (%s,%s,%s,%s)")\n'
        '        await tx.execute("UPDATE inventory SET qty = qty - %s WHERE sku = %s")\n'
        '  File "/app/database/transaction.py", line 44, in execute\n'
        "    await self._conn.execute(query, *args)\n"
        '  File "/app/database/connection.py", line 112, in execute\n'
        "    raise DeadlockError(\n"
        '        "Deadlock found when trying to get lock; try restarting transaction"\n'
        "    )\n"
        "DeadlockError: Deadlock found when trying to get lock; try restarting transaction\n"
        "Blocking query: UPDATE inventory SET qty = qty - 1 WHERE sku = 'SKU-SHOE-001'\n"
        "Victim query:   INSERT INTO orders (id, user_id, total, status) VALUES (...)"
    ),
    "rate_limit": (
        "Traceback (most recent call last):\n"
        '  File "/app/routers/orders.py", line 72, in create_order\n'
        "    fraud_score = await fraud_client.check(\n"
        "        user_id=body.user_id, amount=body.total, ip=request.client.host\n"
        "    )\n"
        '  File "/app/integrations/fraud_check.py", line 48, in check\n'
        "    response = await self._client.post(\n"
        '        "https://fraud-check.internal/v2/verify", json=payload, timeout=5.0\n'
        "    )\n"
        '  File "/app/integrations/fraud_check.py", line 67, in _handle_response\n'
        "    raise RateLimitError(\n"
        "        f\"Rate limited: retry after {response.headers['Retry-After']}s \"\n"
        "        f\"(quota: {response.headers['X-RateLimit-Limit']}/min, \"\n"
        "        f\"used: {response.headers['X-RateLimit-Used']}/min)\"\n"
        "    )\n"
        "RateLimitError: Rate limited by fraud-check-api: retry after 60s (quota: 100/min, used: 189/min)"
    ),
    "cpu_spike": (
        "# CPU profile — worker thread blocked in O(n\u00b3) hot loop\n"
        "Traceback (most recent call last):\n"
        '  File "/app/workers/analytics.py", line 198, in generate_dashboard_report\n'
        "    result = self._cross_join_filter(orders, products, customers)\n"
        '  File "/app/workers/analytics.py", line 231, in _cross_join_filter\n'
        "    return [\n"
        "        (o, p, c)\n"
        "        for o in orders      # 10,000 orders\n"
        "        for p in products    # 10,000 products\n"
        "        for c in customers   # 10,000 customers\n"
        "        if o.product_id == p.id and o.user_id == c.id\n"
        "    ]\n"
        "TimeoutError: Worker did not respond within 3500ms — CPU-starved\n"
        "CPU: 98.3% across 4 cores. Load avg: 15.4 (1m) / 8.2 (5m)"
    ),
    "cascade_failure": (
        "Traceback (most recent call last):\n"
        '  File "/app/routers/payments.py", line 47, in charge\n'
        "    conn = await db_pool.acquire(timeout=5.0)\n"
        '  File "/app/database/pool.py", line 89, in acquire\n'
        '    raise asyncio.TimeoutError("payments-db unreachable after 5000ms")\n'
        "asyncio.TimeoutError: payments-db unreachable after 5000ms\n"
        "\nThe above exception caused the following cascade:\n\n"
        '  File "/app/routers/orders.py", line 58, in create_order\n'
        "    payment_ok = await payment_service.verify(txn_id=txn_id, timeout=3.0)\n"
        '  File "/app/integrations/payment_service.py", line 34, in verify\n'
        "    raise ServiceUnavailableError(\n"
        '        "payments-service circuit breaker OPEN — 5 consecutive failures in 30s"\n'
        "    )\n"
        "ServiceUnavailableError: payments-service circuit breaker OPEN\n\n"
        '  File "/app/routers/users.py", line 29, in login\n'
        "    session = await session_store.create(user_id=user_id, ttl=3600)\n"
        '  File "/app/cache/redis_client.py", line 78, in execute\n'
        "    raise ConnectionRefusedError(\n"
        '        "[Errno 111] Connection refused — session-redis:6379 unreachable"\n'
        "    )\n"
        "ConnectionRefusedError: [Errno 111] Connection refused — session-redis:6379 unreachable"
    ),
    "disk_full": (
        "Traceback (most recent call last):\n"
        '  File "/app/routers/orders.py", line 65, in create_order\n'
        '    await db.execute("INSERT INTO orders (id, user_id, items, total, status) VALUES (%s,%s,%s,%s,%s)")\n'
        '  File "/app/database/connection.py", line 112, in execute\n'
        "    await self._conn.execute(query, *args)\n"
        '  File "/usr/local/lib/python3.12/site-packages/asyncpg/connection.py", line 352\n'
        "    raise asyncpg.exceptions.DiskFullError(\n"
        "        'could not write to file \"pg_wal/000000010000000000000089\": No space left on device'\n"
        "    )\n"
        'asyncpg.exceptions.DiskFullError: could not write to file "pg_wal/000000010000000000000089": No space left on device\n'
        "Disk: /var/lib/postgresql 499.97 GiB / 500.00 GiB (99.99% full) — 0 inodes free"
    ),
}

_SCENARIO_ERRORS: dict = {
    "db_timeout":          {"endpoint": "charge", "http_status": 504,
                            "error_class": "asyncio.TimeoutError",
                            "short_error": "Could not acquire DB connection after 30000ms"},
    "db_pool_exhausted":   {"endpoint": "charge", "http_status": 503,
                            "error_class": "PoolExhaustedError",
                            "short_error": "All 50 connections in use. Queue depth: 127"},
    "api_gateway_timeout": {"endpoint": "charge", "http_status": 504,
                            "error_class": "GatewayTimeoutError",
                            "short_error": "Upstream did not respond within 60s"},
    "auth_failure":        {"endpoint": "login",  "http_status": 401,
                            "error_class": "jwt.exceptions.InvalidSignatureError",
                            "short_error": "Signature verification failed"},
    "memory_spike":        {"endpoint": "create", "http_status": 503,
                            "error_class": "MemoryError",
                            "short_error": "Unable to allocate 512.0 MiB — heap at 94%"},
    "payment_failure":     {"endpoint": "charge", "http_status": 500,
                            "error_class": "GatewayError",
                            "short_error": "[PG_503] Payment processor unavailable"},
    "deadlock":            {"endpoint": "create", "http_status": 503,
                            "error_class": "DeadlockError",
                            "short_error": "Deadlock found when trying to get lock; try restarting transaction"},
    "rate_limit":          {"endpoint": "create", "http_status": 429,
                            "error_class": "RateLimitError",
                            "short_error": "Rate limited by fraud-check-api: retry after 60s"},
    "cpu_spike":           {"endpoint": "charge", "http_status": 503,
                            "error_class": "TimeoutError",
                            "short_error": "Worker did not respond within 3500ms — CPU starved"},
    "cascade_failure":     {"endpoint": "charge", "http_status": 503,
                            "error_class": "ServiceUnavailableError",
                            "short_error": "payments-service circuit breaker OPEN — 5 consecutive failures"},
    "disk_full":           {"endpoint": "charge", "http_status": 507,
                            "error_class": "asyncpg.exceptions.DiskFullError",
                            "short_error": "No space left on device — pg_wal/000000010000000000000089"},
}


def _emit(level: str, event: str, **fields) -> None:
    """Emit one JSON log line that Nexus can grep/parse from stdout."""
    payload = json.dumps({"event": event, "nexus_source": "nexusshop", **fields}, default=str)
    getattr(logger, level)(payload)


def _mark_service(service: str, status: str, scenario: str, error_rate: float,
                  response_time_ms: int, db_connections: int) -> None:
    svc = app_state.services[service]
    old_status = svc.status
    svc.status = status
    svc.active_scenario = scenario
    svc.error_rate = error_rate
    svc.response_time_ms = response_time_ms
    svc.db_connections = db_connections
    if old_status != status:
        lvl = "error" if status == "CRITICAL" else "warning" if status == "DEGRADED" else "info"
        _emit(lvl, "service_status_changed",
              service=service, old_status=old_status, new_status=status, scenario=scenario)


async def _schedule_auto_recovery(service: str, delay: int = AUTO_RECOVERY_SECONDS) -> None:
    _emit("info", "auto_recovery_scheduled", service=service, delay_seconds=delay)
    await asyncio.sleep(delay)
    if app_state.services[service].active_scenario:
        _cleanup_service(service)
        app_state.recover(service)
        _emit("info", "auto_recovery_complete", service=service)


def _cleanup_service(service: str) -> None:
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


async def _simulate_failed_traffic(service: str, scenario: str) -> None:
    """Emit realistic failed-request logs — simulates real users hitting the broken service."""
    err_cfg = _SCENARIO_ERRORS.get(scenario)
    if not err_cfg:
        return
    idx = 0
    await asyncio.sleep(0.8)  # brief ramp-up before traffic begins
    while True:
        user = _FAKE_USERS[idx % len(_FAKE_USERS)]
        item = _FAKE_ITEMS[idx % len(_FAKE_ITEMS)]
        amount = round(item["price"] * random.randint(1, 3), 2)
        request_id = _uuid.uuid4().hex[:8]
        endpoint = f"POST /{service}/{err_cfg['endpoint']}"
        _emit("error", "user_request_failed",
              service=service, scenario=scenario,
              request_id=request_id,
              user_id=user["user_id"], email=user["email"],
              endpoint=endpoint,
              amount=amount, card_token=user["card_token"],
              sku=item["sku"], product=item["name"],
              http_status=err_cfg["http_status"],
              error_class=err_cfg["error_class"],
              error=err_cfg["short_error"],
              traceback=_TRACEBACKS.get(scenario, ""),
              msg=(f"[{request_id}] {user['email']} \u2192 {endpoint} "
                   f"\u2192 HTTP {err_cfg['http_status']} {err_cfg['error_class']}: {err_cfg['short_error']}"))
        idx += 1
        await asyncio.sleep(random.uniform(1.2, 3.8))


# ── Scenario 1 — db_timeout ──────────────────────────────────────────────────

async def scenario_db_timeout(service: str) -> None:
    _mark_service(service, "CRITICAL", "db_timeout", 0.97, 30412, 1)
    app_state.add_error(service, "db_timeout", "HIGH", "Database connection timeout after 30s")

    _emit("error", "scenario_triggered",
          service=service, scenario="db_timeout", severity="HIGH",
          error_message=f"Database connection timeout after 30s — {service}_db unreachable",
          traceback=_TRACEBACKS["db_timeout"],
          metadata={"timeout_ms": 30000, "db_host": f"{service}-db.internal",
                    "retry_count": 3, "last_successful_query_ms_ago": 30412})

    webhook_sent = await send_webhook(
        service=service, scenario="db_timeout",
        error=f"Database connection timeout after 30s — {service}_db unreachable",
        severity="HIGH",
        metadata={"timeout_ms": 30000, "db_host": f"{service}-db.internal",
                  "affected_endpoints": [f"/{service}/charge", f"/{service}/status"]},
    )
    _emit("info", "webhook_dispatched", service=service, scenario="db_timeout", webhook_sent=webhook_sent)

    release = asyncio.Event()
    app_state._release_events[service] = release

    async def _hold_connection():
        _emit("warning", "db_connection_held", service=service,
              msg="Simulating hung DB connection — coroutine blocked on read()")
        try:
            await asyncio.wait_for(release.wait(), timeout=30)
        except asyncio.TimeoutError:
            _emit("error", "db_connection_timeout_expired", service=service,
                  msg="DB connection wait expired after 30s — ETIMEDOUT raised")

    app_state.background_tasks[service].append(asyncio.create_task(_hold_connection()))
    app_state.recovery_tasks[service] = asyncio.create_task(_schedule_auto_recovery(service))


# ── Scenario 2 — db_pool_exhausted ───────────────────────────────────────────

async def scenario_db_pool_exhausted(service: str) -> None:
    _mark_service(service, "CRITICAL", "db_pool_exhausted", 0.99, 5000, 50)
    app_state.add_error(service, "db_pool_exhausted", "HIGH",
                        "Database connection pool exhausted — 50/50 connections in use")

    _emit("error", "scenario_triggered",
          service=service, scenario="db_pool_exhausted", severity="HIGH",
          error_message="Database connection pool exhausted — 50/50 connections in use",
          traceback=_TRACEBACKS["db_pool_exhausted"],
          metadata={"connections_active": 50, "connections_max": 50,
                    "wait_queue_depth": 127, "avg_hold_duration_ms": 4823,
                    "oldest_held_ms": 89412})

    webhook_sent = await send_webhook(
        service=service, scenario="db_pool_exhausted",
        error="Database connection pool exhausted — 50/50 connections in use",
        severity="HIGH",
        metadata={"connections_active": 50, "connections_max": 50,
                  "wait_queue_depth": 127, "affected_service": service},
    )
    _emit("info", "webhook_dispatched", service=service, scenario="db_pool_exhausted", webhook_sent=webhook_sent)

    release = asyncio.Event()
    app_state._release_events[service] = release
    lock = asyncio.Lock()
    _emit("warning", "db_pool_filling", service=service,
          msg="Spawning 50 tasks to exhaust connection pool")

    async def _hold_fake_connection(_i: int):
        async with lock:
            try:
                await release.wait()
            except asyncio.CancelledError:
                pass

    tasks = [asyncio.create_task(_hold_fake_connection(i)) for i in range(50)]
    app_state.background_tasks[service].extend(tasks)
    app_state.recovery_tasks[service] = asyncio.create_task(_schedule_auto_recovery(service))


# ── Scenario 3 — api_gateway_timeout ─────────────────────────────────────────

async def scenario_api_gateway_timeout(service: str) -> None:
    _mark_service(service, "CRITICAL", "api_gateway_timeout", 0.95, 65000, 3)
    app_state.add_error(service, "api_gateway_timeout", "HIGH",
                        "API gateway timeout — upstream payments service not responding (>60s)")

    _emit("error", "scenario_triggered",
          service=service, scenario="api_gateway_timeout", severity="HIGH",
          error_message=f"API gateway timeout — upstream {service} service not responding (>60s)",
          traceback=_TRACEBACKS["api_gateway_timeout"],
          metadata={"gateway_timeout_ms": 60000, "upstream": f"{service}-service",
                    "error_code": "UPSTREAM_TIMEOUT",
                    "nginx_error": "upstream timed out while reading response header"})

    webhook_sent = await send_webhook(
        service=service, scenario="api_gateway_timeout",
        error=f"API gateway timeout — upstream {service} service not responding (>60s)",
        severity="HIGH",
        metadata={"gateway_timeout_ms": 60000, "upstream": f"{service}-service",
                  "error_code": "UPSTREAM_TIMEOUT"},
    )
    _emit("info", "webhook_dispatched", service=service, scenario="api_gateway_timeout", webhook_sent=webhook_sent)
    app_state.recovery_tasks[service] = asyncio.create_task(_schedule_auto_recovery(service))


# ── Scenario 4 — auth_failure ─────────────────────────────────────────────────

async def scenario_auth_failure(service: str) -> None:
    _mark_service(service, "DEGRADED", "auth_failure", 0.98, 120, 3)
    app_state.add_error(service, "auth_failure", "MEDIUM",
                        "Mass authentication failures — 401 rate spiked to 98%")

    _emit("error", "scenario_triggered",
          service=service, scenario="auth_failure", severity="MEDIUM",
          error_message="Mass authentication failures — 401 rate spiked to 98% of requests",
          traceback=_TRACEBACKS["auth_failure"],
          metadata={"error_rate_401": 0.98,
                    "affected_endpoints": ["/users/login", "/orders/create"],
                    "failure_reason": "JWT signature verification failed",
                    "suspect": "JWT_SECRET may have rotated — signing key mismatch",
                    "requests_rejected_last_60s": 847})

    webhook_sent = await send_webhook(
        service=service, scenario="auth_failure",
        error="Mass authentication failures — 401 rate spiked to 98% of requests",
        severity="MEDIUM",
        metadata={"error_rate_401": 0.98, "affected_endpoints": ["/users/login", "/orders/create"],
                  "failure_reason": "JWT signature verification failed"},
    )
    _emit("info", "webhook_dispatched", service=service, scenario="auth_failure", webhook_sent=webhook_sent)
    app_state.recovery_tasks[service] = asyncio.create_task(_schedule_auto_recovery(service))


# ── Scenario 5 — memory_spike ─────────────────────────────────────────────────

async def scenario_memory_spike(service: str) -> None:
    _mark_service(service, "DEGRADED", "memory_spike", 0.15, 2400, 4)
    app_state.add_error(service, "memory_spike", "MEDIUM",
                        "Memory spike detected — heap utilization at 94%, OOM risk")

    _emit("warning", "memory_allocation_start", service=service,
          msg="Allocating 500 MB to simulate memory leak — GC cannot collect pinned ref")
    app_state._memory_holder = bytearray(500 * 1024 * 1024)

    _emit("error", "scenario_triggered",
          service=service, scenario="memory_spike", severity="MEDIUM",
          error_message="Memory spike detected — heap utilization at 94%, OOM risk",
          traceback=_TRACEBACKS["memory_spike"],
          metadata={"heap_used_mb": 960, "heap_max_mb": 1024, "heap_percent": 93.75,
                    "gc_collections_blocked": True, "largest_object_mb": 500})

    webhook_sent = await send_webhook(
        service=service, scenario="memory_spike",
        error="Memory spike detected — heap utilization at 94%, OOM risk",
        severity="MEDIUM",
        metadata={"heap_used_mb": 960, "heap_max_mb": 1024, "heap_percent": 93.75},
    )
    _emit("info", "webhook_dispatched", service=service, scenario="memory_spike", webhook_sent=webhook_sent)
    app_state.recovery_tasks[service] = asyncio.create_task(_schedule_auto_recovery(service))


# ── Scenario 6 — payment_failure ─────────────────────────────────────────────

async def scenario_payment_failure(service: str) -> None:
    _mark_service(service, "CRITICAL", "payment_failure", 1.0, 210, 4)
    app_state.add_error(service, "payment_failure", "HIGH",
                        "Payment processing failure — gateway returning PG_503 on all transactions")

    _emit("error", "scenario_triggered",
          service=service, scenario="payment_failure", severity="HIGH",
          error_message="Payment processing failure — gateway returning PG_503 on all transactions",
          traceback=_TRACEBACKS["payment_failure"],
          metadata={"gateway_error_code": "PG_503", "failed_transactions": 47,
                    "revenue_at_risk_usd": 14230.00,
                    "gateway_response_body": '{"error":"Service Unavailable","retry_after":3600}',
                    "gateway_endpoint": "https://api.payment-gateway.internal/v1/charge"})

    webhook_sent = await send_webhook(
        service=service, scenario="payment_failure",
        error="Payment processing failure — gateway returning PG_503 on all transactions",
        severity="HIGH",
        metadata={"gateway_error_code": "PG_503", "failed_transactions": 47,
                  "revenue_at_risk_usd": 14230.00},
    )
    _emit("info", "webhook_dispatched", service=service, scenario="payment_failure", webhook_sent=webhook_sent)
    app_state.recovery_tasks[service] = asyncio.create_task(_schedule_auto_recovery(service))


# ── Scenario 7 — deadlock ─────────────────────────────────────────────────────

async def scenario_deadlock(service: str) -> None:
    _mark_service(service, "DEGRADED", "deadlock", 0.60, 15000, 4)
    app_state.add_error(service, "deadlock", "MEDIUM",
                        "Database deadlock detected — orders table write operations blocking")

    _emit("error", "scenario_triggered",
          service=service, scenario="deadlock", severity="MEDIUM",
          error_message="Database deadlock detected — orders table write operations blocking",
          traceback=_TRACEBACKS["deadlock"],
          metadata={"table": "orders", "lock_wait_ms": 15000, "deadlock_count": 3,
                    "blocked_queries": ["INSERT INTO orders", "UPDATE inventory"],
                    "victim_query": "INSERT INTO orders", "victim_pid": 4821})

    webhook_sent = await send_webhook(
        service=service, scenario="deadlock",
        error="Database deadlock detected — orders table write operations blocking",
        severity="MEDIUM",
        metadata={"table": "orders", "lock_wait_ms": 15000, "deadlock_count": 3,
                  "affected_queries": ["INSERT INTO orders", "UPDATE inventory"]},
    )
    _emit("info", "webhook_dispatched", service=service, scenario="deadlock", webhook_sent=webhook_sent)

    lock_a = asyncio.Lock()
    lock_b = asyncio.Lock()

    async def _task_a():
        _emit("warning", "deadlock_task_a_start", service=service,
              msg="task_a: acquired lock_orders, waiting for lock_inventory")
        async with lock_a:
            await asyncio.sleep(0.1)
            try:
                await asyncio.wait_for(lock_b.acquire(), timeout=15)
                lock_b.release()
            except (asyncio.TimeoutError, asyncio.CancelledError):
                _emit("error", "deadlock_confirmed", service=service,
                      msg="task_a timed out on lock_inventory — deadlock confirmed",
                      lock_wait_ms=15000)

    async def _task_b():
        _emit("warning", "deadlock_task_b_start", service=service,
              msg="task_b: acquired lock_inventory, waiting for lock_orders — DEADLOCK CYCLE")
        async with lock_b:
            await asyncio.sleep(0.1)
            try:
                await asyncio.wait_for(lock_a.acquire(), timeout=15)
                lock_a.release()
            except (asyncio.TimeoutError, asyncio.CancelledError):
                _emit("error", "deadlock_cycle_detected", service=service,
                      msg="task_b cannot acquire lock_orders held by task_a — cycle confirmed")

    app_state.background_tasks[service].extend([
        asyncio.create_task(_task_a()),
        asyncio.create_task(_task_b()),
    ])
    app_state.recovery_tasks[service] = asyncio.create_task(_schedule_auto_recovery(service))


# ── Scenario 8 — rate_limit ───────────────────────────────────────────────────

async def scenario_rate_limit(service: str) -> None:
    _mark_service(service, "DEGRADED", "rate_limit", 0.45, 180, 3)
    app_state.add_error(service, "rate_limit", "LOW",
                        "Rate limit exceeded — downstream fraud-check API returning 429")

    _emit("warning", "scenario_triggered",
          service=service, scenario="rate_limit", severity="LOW",
          error_message="Rate limit exceeded — downstream fraud-check API returning 429",
          traceback=_TRACEBACKS["rate_limit"],
          metadata={"downstream_service": "fraud-check-api", "requests_throttled": 89,
                    "retry_after_seconds": 60, "rate_limit_quota": "100/min",
                    "current_rate": "189/min",
                    "api_endpoint": "https://fraud-check.internal/v2/verify"})

    webhook_sent = await send_webhook(
        service=service, scenario="rate_limit",
        error="Rate limit exceeded — downstream fraud-check API returning 429",
        severity="LOW",
        metadata={"downstream_service": "fraud-check-api", "requests_throttled": 89,
                  "retry_after_seconds": 60},
    )
    _emit("info", "webhook_dispatched", service=service, scenario="rate_limit", webhook_sent=webhook_sent)
    app_state.recovery_tasks[service] = asyncio.create_task(_schedule_auto_recovery(service))


# ── Scenario 9 — cpu_spike ────────────────────────────────────────────────────

async def scenario_cpu_spike(service: str) -> None:
    _mark_service(service, "DEGRADED", "cpu_spike", 0.20, 3500, 4)
    app_state.add_error(service, "cpu_spike", "MEDIUM",
                        "CPU spike detected — utilization at 98%, workers saturated")

    _emit("error", "scenario_triggered",
          service=service, scenario="cpu_spike", severity="MEDIUM",
          error_message="CPU spike detected — utilization at 98%, all worker threads saturated",
          traceback=_TRACEBACKS["cpu_spike"],
          metadata={"cpu_percent": 98.3, "cpu_cores": 4, "saturated_cores": 4,
                    "thread_count": 128, "load_avg_1m": 15.4, "load_avg_5m": 8.2,
                    "suspect_function": "report_generator.build_analytics()",
                    "pid": os.getpid()})

    webhook_sent = await send_webhook(
        service=service, scenario="cpu_spike",
        error="CPU spike detected — utilization at 98%, all worker threads saturated",
        severity="MEDIUM",
        metadata={"cpu_percent": 98.3, "cpu_cores": 4, "saturated_cores": 4,
                  "load_avg_1m": 15.4},
    )
    _emit("info", "webhook_dispatched", service=service, scenario="cpu_spike", webhook_sent=webhook_sent)

    release = asyncio.Event()
    app_state._release_events[service] = release
    _emit("warning", "cpu_burn_started", service=service,
          msg="Starting 4 CPU-burn coroutines to simulate saturated worker pool")

    async def _cpu_burn():
        while not release.is_set():
            _ = sum(i * i for i in range(50_000))
            await asyncio.sleep(0)

    tasks = [asyncio.create_task(_cpu_burn()) for _ in range(4)]
    app_state.background_tasks[service].extend(tasks)
    app_state.recovery_tasks[service] = asyncio.create_task(_schedule_auto_recovery(service))


# ── Scenario 10 — cascade_failure ────────────────────────────────────────────

async def scenario_cascade_failure(origin_service: str) -> None:
    all_services = ["payments", "orders", "users"]

    _emit("critical", "scenario_triggered",
          service=origin_service, scenario="cascade_failure", severity="HIGH",
          error_message=f"Cascade failure from {origin_service} — all 3 services affected",
          traceback=_TRACEBACKS["cascade_failure"],
          metadata={"origin_service": origin_service, "affected_services": all_services,
                    "propagation_chain": [
                        f"{origin_service} DB unresponsive",
                        "orders cannot verify payment — circuit breaker open",
                        "users auth cannot reach session store — 401 spike",
                    ],
                    "impact": "full site outage — 0% of transactions succeeding"})

    for svc in all_services:
        _mark_service(svc, "CRITICAL", "cascade_failure", 0.99, 30000, 50)
        app_state.add_error(svc, "cascade_failure", "HIGH",
                            f"Cascade failure — propagated from {origin_service}")
        _emit("error", "cascade_propagated_to",
              service=svc, origin=origin_service, scenario="cascade_failure",
              msg=f"{svc} marked CRITICAL — cascade from {origin_service}")

    webhook_sent = await send_webhook(
        service=origin_service, scenario="cascade_failure",
        error=f"Cascade failure from {origin_service} — all 3 services affected",
        severity="HIGH",
        metadata={"origin_service": origin_service, "affected_services": all_services,
                  "impact": "full site outage"},
    )
    _emit("info", "webhook_dispatched", service=origin_service, scenario="cascade_failure",
          webhook_sent=webhook_sent, note="single webhook — no duplicate incidents")

    for svc in all_services:
        app_state.recovery_tasks[svc] = asyncio.create_task(_schedule_auto_recovery(svc))


# ── Scenario 11 — disk_full ───────────────────────────────────────────────────

async def scenario_disk_full(service: str) -> None:
    _mark_service(service, "CRITICAL", "disk_full", 0.85, 450, 4)
    app_state.add_error(service, "disk_full", "HIGH",
                        "Disk full — write operations failing with ENOSPC")

    _emit("error", "scenario_triggered",
          service=service, scenario="disk_full", severity="HIGH",
          error_message="Disk full — write operations failing with ENOSPC",
          traceback=_TRACEBACKS["disk_full"],
          metadata={"disk_mount": "/var/lib/postgresql", "disk_used_gb": 499.97,
                    "disk_total_gb": 500.0, "disk_percent": 99.99, "inode_free": 0,
                    "largest_dir": "/var/lib/postgresql/data/pg_wal",
                    "largest_dir_gb": 84.2,
                    "oom_killed_processes": ["pg_walwriter"]})

    webhook_sent = await send_webhook(
        service=service, scenario="disk_full",
        error="Disk full — write operations failing with ENOSPC",
        severity="HIGH",
        metadata={"disk_used_gb": 499.97, "disk_total_gb": 500.0,
                  "disk_percent": 99.99, "inode_free": 0},
    )
    _emit("info", "webhook_dispatched", service=service, scenario="disk_full", webhook_sent=webhook_sent)
    app_state.recovery_tasks[service] = asyncio.create_task(_schedule_auto_recovery(service))


# ── Dispatch table ────────────────────────────────────────────────────────────

SCENARIOS = {
    "db_timeout": scenario_db_timeout,
    "db_pool_exhausted": scenario_db_pool_exhausted,
    "api_gateway_timeout": scenario_api_gateway_timeout,
    "auth_failure": scenario_auth_failure,
    "memory_spike": scenario_memory_spike,
    "payment_failure": scenario_payment_failure,
    "deadlock": scenario_deadlock,
    "rate_limit": scenario_rate_limit,
    "cpu_spike": scenario_cpu_spike,
    "cascade_failure": scenario_cascade_failure,
    "disk_full": scenario_disk_full,
}


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
