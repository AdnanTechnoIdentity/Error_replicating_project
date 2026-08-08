# NexusShop — Demo Target Application
# Hackathon Demo App Specification

## Purpose

A fake e-commerce platform that simulates realistic production services
(Payments, Orders, Users). It can deliberately trigger error scenarios that
the Nexus AI incident response system will detect, investigate, and resolve.

Used **only for hackathon demos.**

The demo story:

    NexusShop is the "customer's app" running in production.
    Nexus is the AI engineering platform watching over it.

    NexusShop breaks → Nexus detects → Nexus investigates → Nexus fixes.

------------------------------------------------------------
## 1. WHAT TO BUILD
------------------------------------------------------------

### Backend

A single Python FastAPI application that simulates 3 microservices
via route prefixes:

- `/payments/...` — Payments service
- `/orders/...`   — Orders service
- `/users/...`    — Users service

It has three responsibilities:

1. **Normal business endpoints** — realistic-looking routes that work under
   normal operation, so the demo feels like a real running app.

2. **Chaos controller** — dedicated endpoints to manually inject any error
   scenario into any service on demand.

3. **Webhook sender** — when an error fires, it immediately sends a signed
   webhook to Nexus so the AI incident response workflow starts.

### Frontend

A simple React dashboard (Vite + plain CSS or Tailwind).
Do NOT use MUI — keep it visually distinct from Nexus.
Use a red/orange color scheme so judges can clearly tell:

    NexusShop (target app, red/orange)  vs  Nexus (AI platform, indigo/dark)

The dashboard shows:

- 3 service health cards: Payments | Orders | Users
- Live error feed / recent events
- One-click "Trigger Error" buttons
- Simulated metrics: response time, error rate, DB connections

------------------------------------------------------------
## 2. TECH STACK
------------------------------------------------------------

| Layer     | Technology                                |
|-----------|-------------------------------------------|
| Backend   | Python 3.12 + FastAPI + Uvicorn           |
| Storage   | SQLite in-memory (no PostgreSQL needed)   |
| Async     | asyncio + httpx                           |
| Security  | hmac + hashlib (webhook signature)       |
| Frontend  | React 19 + Vite (separate from Nexus web) |
| Infra     | Docker Compose (alongside Nexus services) |

------------------------------------------------------------
## 3. DIRECTORY STRUCTURE
------------------------------------------------------------

```
nexus-demo-app/
├── backend/
│   ├── main.py                  # FastAPI app entry point
│   ├── routers/
│   │   ├── payments.py          # POST /payments/charge, GET /payments/status
│   │   ├── orders.py            # POST /orders/create, GET /orders/{id}
│   │   └── users.py             # POST /users/login, GET /users/{id}
│   ├── chaos/
│   │   ├── controller.py        # POST /chaos/trigger — main chaos endpoint
│   │   └── scenarios.py         # All 8 error scenario implementations
│   ├── webhook/
│   │   └── sender.py            # Signs and POSTs webhook to Nexus
│   ├── state.py                 # In-memory service state (health, error history)
│   ├── requirements.txt
│   └── .env.example
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── ServiceCard.tsx  # Health card per service
│   │   │   ├── ErrorFeed.tsx    # Live recent errors list
│   │   │   └── ChaosPanel.tsx   # Trigger buttons
│   │   └── services/api.ts
│   ├── package.json
│   └── vite.config.ts
│
├── docker-compose.yml
└── .env.example
```

Place this inside the monorepo at:

    nexus/apps/demo-app/

------------------------------------------------------------
## 4. NORMAL BUSINESS ENDPOINTS
------------------------------------------------------------

These make the app feel like a real running service.

### Payments Service

    POST /payments/charge
    Body: { "amount": 150.00, "currency": "USD", "card_token": "tok_xxx" }
    Response: { "transaction_id": "TXN-...", "status": "SUCCESS" }

    GET /payments/status/{transaction_id}
    Response: { "transaction_id": "...", "status": "SUCCESS", "amount": 150.00 }

    GET /payments/health
    Response: { "service": "payments", "status": "HEALTHY", "db_connections": 4 }

### Orders Service

    POST /orders/create
    Body: { "user_id": "U-001", "items": [...], "total": 299.99 }
    Response: { "order_id": "ORD-...", "status": "CONFIRMED" }

    GET /orders/{order_id}
    Response: { "order_id": "...", "status": "CONFIRMED", "items": [...] }

    GET /orders/health
    Response: { "service": "orders", "status": "HEALTHY" }

### Users Service

    POST /users/login
    Body: { "email": "user@example.com", "password": "..." }
    Response: { "token": "eyJ...", "user_id": "U-001" }

    GET /users/{user_id}
    Response: { "id": "U-001", "email": "...", "name": "..." }

    GET /users/health
    Response: { "service": "users", "status": "HEALTHY" }

------------------------------------------------------------
## 5. THE 8 ERROR SCENARIOS
------------------------------------------------------------

All scenarios live in `chaos/scenarios.py`.

The chaos controller accepts:

    POST /chaos/trigger
    Body: { "service": "payments", "scenario": "db_timeout" }

Each scenario must:
1. **Actually simulate** the condition — not just log a fake message
2. **Update in-memory state** so the frontend shows the service as red/degraded
3. **Send the webhook to Nexus immediately**
4. **Auto-recover after 60–120 seconds** or when `POST /chaos/recover` is called

---

### Scenario 1: `db_timeout`

**What it simulates:**
Database query hangs, connection times out after 30 seconds.

**Implementation:**
```python
await asyncio.sleep(30)
raise Exception("Database connection timeout after 30000ms")
```

**Severity:** HIGH

**Webhook error:**
`"Database connection timeout after 30s — payments_db unreachable"`

**Metadata:**
```json
{
  "timeout_ms": 30000,
  "db_host": "payments-db.internal",
  "affected_endpoints": ["/payments/charge", "/payments/status"]
}
```

---

### Scenario 2: `db_pool_exhausted`

**What it simulates:**
All database connections are in use, new requests cannot acquire a connection.

**Implementation:**
Spawn 50 concurrent async tasks that each hold a fake DB connection
(asyncio.Lock) and don't release it.

**Severity:** HIGH

**Webhook error:**
`"Database connection pool exhausted — 50/50 connections in use"`

**Metadata:**
```json
{
  "connections_active": 50,
  "connections_max": 50,
  "wait_queue_depth": 127,
  "affected_service": "payments"
}
```

---

### Scenario 3: `api_gateway_timeout`

**What it simulates:**
Upstream service takes too long; API gateway cuts the connection.

**Implementation:**
Every request to `/payments/charge` sleeps 65 seconds, causing
the caller's 60-second timeout to fire first.

**Severity:** HIGH

**Webhook error:**
`"API gateway timeout — upstream payments service not responding (>60s)"`

**Metadata:**
```json
{
  "gateway_timeout_ms": 60000,
  "upstream": "payments-service",
  "error_code": "UPSTREAM_TIMEOUT"
}
```

---

### Scenario 4: `auth_failure`

**What it simulates:**
JWT validation is broken — every authenticated request returns 401.

**Implementation:**
Override the JWT verify function to always raise `HTTPException(401)`.

**Severity:** MEDIUM

**Webhook error:**
`"Mass authentication failures — 401 rate spiked to 98% of requests"`

**Metadata:**
```json
{
  "error_rate_401": 0.98,
  "affected_endpoints": ["/users/login", "/orders/create"],
  "failure_reason": "JWT signature verification failed"
}
```

---

### Scenario 5: `memory_spike`

**What it simulates:**
A memory leak causes heap usage to spike, risking OOM kill.

**Implementation:**
Allocate a 500MB byte array and hold a reference to it in a module-level
variable so the GC cannot collect it.

**Severity:** MEDIUM

**Webhook error:**
`"Memory spike detected — heap utilization at 94%, OOM risk"`

**Metadata:**
```json
{
  "heap_used_mb": 960,
  "heap_max_mb": 1024,
  "heap_percent": 93.75,
  "service": "orders"
}
```

---

### Scenario 6: `payment_failure`

**What it simulates:**
The payment gateway rejects all transactions (e.g. credentials expired,
gateway outage).

**Implementation:**
Every `POST /payments/charge` returns HTTP 500 with a realistic error body:
```json
{
  "error": "GATEWAY_REJECTED",
  "message": "Payment processor unavailable",
  "code": "PG_503"
}
```

**Severity:** HIGH

**Webhook error:**
`"Payment processing failure — gateway returning PG_503 on all transactions"`

**Metadata:**
```json
{
  "gateway_error_code": "PG_503",
  "failed_transactions": 47,
  "revenue_at_risk_usd": 14230.00
}
```

---

### Scenario 7: `deadlock`

**What it simulates:**
Two concurrent database writes are waiting on each other's locks.

**Implementation:**
Create two asyncio tasks that each acquire Lock A then try to acquire Lock B
(and vice versa), causing a deadlock. Log the deadlock detection after a
timeout.

**Severity:** MEDIUM

**Webhook error:**
`"Database deadlock detected — orders table write operations blocking"`

**Metadata:**
```json
{
  "table": "orders",
  "lock_wait_ms": 15000,
  "deadlock_count": 3,
  "affected_queries": ["INSERT INTO orders", "UPDATE inventory"]
}
```

---

### Scenario 8: `rate_limit`

**What it simulates:**
A downstream third-party service (e.g. shipping API, fraud check) starts
returning 429 Too Many Requests.

**Implementation:**
For 60 seconds, every call to a downstream-dependent endpoint returns:
```json
{
  "error": "RATE_LIMITED",
  "retry_after": 60
}
```

**Severity:** LOW

**Webhook error:**
`"Rate limit exceeded — downstream fraud-check API returning 429"`

**Metadata:**
```json
{
  "downstream_service": "fraud-check-api",
  "requests_throttled": 89,
  "retry_after_seconds": 60
}
```

------------------------------------------------------------
## 6. CHAOS CONTROLLER API
------------------------------------------------------------

### Trigger an error

    POST /chaos/trigger
    Headers: X-Chaos-Key: <CHAOS_SECRET>
    Body:
    {
      "service": "payments",    // "payments" | "orders" | "users"
      "scenario": "db_timeout"  // one of the 8 scenario keys
    }

    Response:
    {
      "triggered": true,
      "service": "payments",
      "scenario": "db_timeout",
      "webhook_sent": true,
      "auto_recovery_in_seconds": 90
    }

### Recover a service

    POST /chaos/recover
    Headers: X-Chaos-Key: <CHAOS_SECRET>
    Body: { "service": "payments" }   // or "all"

    Response: { "recovered": ["payments"] }

### Get current state (used by frontend polling)

    GET /state

    Response:
    {
      "services": {
        "payments": {
          "status": "CRITICAL",
          "active_scenario": "db_timeout",
          "response_time_ms": 30412,
          "error_rate": 0.97,
          "db_connections": 50
        },
        "orders": { "status": "HEALTHY", ... },
        "users":  { "status": "HEALTHY", ... }
      },
      "recent_errors": [
        {
          "id": "ERR-001",
          "service": "payments",
          "scenario": "db_timeout",
          "severity": "HIGH",
          "timestamp": "2026-08-08T14:30:22Z",
          "message": "Database connection timeout after 30s"
        }
      ]
    }

------------------------------------------------------------
## 7. WEBHOOK CONTRACT (Nexus Integration)
------------------------------------------------------------

When a chaos scenario fires, the backend sends:

    POST /api/incidents/ingest   (on the Nexus API, port 8000)

### Headers

    Content-Type: application/json
    X-Nexus-Signature: sha256=<hmac-sha256 of raw JSON body using WEBHOOK_SECRET>

### Payload

```json
{
  "service": "payments",
  "project": "payments",
  "error": "Database connection pool exhausted — 50/50 connections in use",
  "severity": "HIGH",
  "scenario": "db_pool_exhausted",
  "timestamp": "2026-08-08T14:30:22Z",
  "metadata": {
    "connections_active": 50,
    "connections_max": 50,
    "wait_queue_depth": 127
  }
}
```

### Signature algorithm

```python
import hmac, hashlib, json

def sign_payload(payload: dict, secret: str) -> str:
    body = json.dumps(payload, separators=(",", ":"))
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"sha256={sig}"
```

Nexus must verify this signature before starting any workflow.
If the signature is invalid, return HTTP 401 and do not process.

------------------------------------------------------------
## 8. FRONTEND DASHBOARD
------------------------------------------------------------

Keep it minimal but visually effective.

### Layout

```
┌─────────────────────────────────────────────────────────┐
│  🛒 NexusShop  •  Live System Status  ●  DEGRADED       │
├──────────────┬──────────────┬──────────────────────────-┤
│  PAYMENTS    │   ORDERS     │   USERS                   │
│  🔴 CRITICAL │   🟢 HEALTHY │   🟢 HEALTHY              │
│  RT: 30,412ms│   RT: 84ms  │   RT: 92ms                │
│  ERR: 97%    │   ERR: 0%   │   ERR: 0%                 │
│  DB: 50/50   │   DB: 4/50  │   DB: 2/50                │
├──────────────┴──────────────┴───────────────────────────┤
│  CHAOS PANEL                                            │
│  Service: [Payments ▼]  Scenario: [DB Pool Exhausted ▼] │
│  [  🔴 TRIGGER ERROR  ]   [ ✅ Recover All ]            │
├─────────────────────────────────────────────────────────┤
│  RECENT ERRORS                                          │
│  14:30:22  payments  HIGH   DB pool exhausted          │
│  14:28:01  payments  HIGH   DB connection timeout      │
│  14:15:44  orders    MEDIUM Deadlock detected          │
└─────────────────────────────────────────────────────────┘
```

### Service card — color states

| Status   | Card color | Dot  |
|----------|------------|------|
| HEALTHY  | Green      | 🟢   |
| DEGRADED | Amber      | 🟡   |
| CRITICAL | Red        | 🔴   |

### Frontend polls `GET /state` every 2 seconds — no websockets needed.

### Frontend env

```
VITE_API_URL=http://localhost:9000
```

------------------------------------------------------------
## 9. ENVIRONMENT VARIABLES
------------------------------------------------------------

### Backend `.env.example`

```
# Nexus integration
NEXUS_WEBHOOK_URL=http://localhost:8000/api/incidents/ingest
WEBHOOK_SECRET=nexus-demo-secret-change-me

# Chaos panel protection
CHAOS_SECRET=chaos-panel-secret

# Demo app
APP_HOST=0.0.0.0
APP_PORT=9000
```

### Frontend `.env.example`

```
VITE_API_URL=http://localhost:9000
VITE_CHAOS_SECRET=chaos-panel-secret
```

------------------------------------------------------------
## 10. PYTHON REQUIREMENTS
------------------------------------------------------------

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
httpx==0.27.2
python-dotenv==1.0.1
pydantic==2.8.2
```

No database drivers needed — all data is in-memory.

------------------------------------------------------------
## 11. DOCKER COMPOSE SERVICE
------------------------------------------------------------

Add to the main Nexus `infra/docker-compose.yml`:

```yaml
demo-backend:
  build: ../apps/demo-app/backend
  ports:
    - "9000:9000"
  environment:
    - NEXUS_WEBHOOK_URL=http://api:8000/api/incidents/ingest
    - WEBHOOK_SECRET=${WEBHOOK_SECRET:-nexus-demo-secret-change-me}
    - CHAOS_SECRET=${CHAOS_SECRET:-chaos-panel-secret}
  depends_on:
    - api

demo-frontend:
  build: ../apps/demo-app/frontend
  ports:
    - "5174:80"
  depends_on:
    - demo-backend
```

------------------------------------------------------------
## 12. DEMO FLOW (How to use during presentation)
------------------------------------------------------------

STEP 1 — Show NexusShop running normally

    Open http://localhost:5174
    All 3 services: 🟢 HEALTHY
    Show normal API calls working

STEP 2 — Trigger an incident

    Select: Payments → DB Pool Exhausted
    Click: TRIGGER ERROR
    Watch: Payments card turns 🔴 CRITICAL

STEP 3 — Switch to Nexus (http://localhost:5173)

    The incident appears automatically in Active Incidents
    Temporal workflow has already started
    Show the workflow timeline progressing in real time

STEP 4 — AI investigation completes

    Log Agent: analyzed logs
    Git Agent: checked recent commits
    Failure Library: found 2 similar past incidents
    Root Cause Agent: 94% confidence

STEP 5 — Approve the fix in Nexus

    Click Review → Approve
    Temporal signal resumes the workflow
    Remediation executes
    Verification passes

STEP 6 — Return to NexusShop

    Click: Recover All
    Payments card returns to 🟢 HEALTHY
    Incident is marked RESOLVED in Nexus

STEP 7 — Durability demo (optional but impressive)

    Trigger another error in NexusShop
    While Nexus is investigating — kill the Temporal worker process
    Restart the worker
    Show: workflow resumes exactly where it left off
    This proves Temporal's value to judges

------------------------------------------------------------
## 13. IMPORTANT CONSTRAINTS
------------------------------------------------------------

1. **Self-contained** — no external dependencies beyond FastAPI and stdlib
2. **In-memory only** — no database setup, no migrations, no persistence
3. **Realistic simulations** — actual async delays and real Python exceptions,
   not just fake log messages
4. **Visually distinct** — red/orange theme, not indigo. Judges must instantly
   see "this is the broken app, that is the AI platform"
5. **No auth on the dashboard** — it's a local demo tool, keep it simple
6. **Webhook signature must be verified by Nexus** before any workflow starts
7. **Auto-recovery** — every scenario recovers automatically after 90 seconds
   so the demo can loop without manual cleanup
8. **The chaos key protects the trigger endpoint** — prevents accidental
   triggers during the demo if someone pokes the API

------------------------------------------------------------
## 14. MONOREPO PLACEMENT
------------------------------------------------------------

Place inside the existing Nexus monorepo:

    nexus/
    └── apps/
        ├── web/          ← Nexus frontend (already exists)
        ├── api/          ← Nexus backend (already exists)
        └── demo-app/     ← NexusShop demo app (build this)
            ├── backend/
            └── frontend/

============================================================
END DEMO APP CONTEXT
============================================================
