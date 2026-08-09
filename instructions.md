# Incident Reporting — Integration Guide

## How the listener works

```
Your Application Container
        │ stdout/stderr logs
        ▼
log_monitor.py
  docker.containers.get("my-app")
  .logs(stream=True, follow=True)   ← follows log stream in real-time
        │
        │ scans each line for trigger keywords
        ▼
  matches_trigger(log)
  ─ "Exception"
  ─ "Traceback"
  ─ "OOMKilled"
  ─ "Connection refused"
  ─ "Segmentation fault"
  ─ "panic:"
  ─ "ERROR"
        │ match found
        ▼
  investigate(log)                  ← Gemini agent
        │ calls two retrieval tools
        ├─ Neo4j graph DB    → runbooks by symptom, source symbols, service context
        └─ Milvus vector DB  → semantic search over KB docs & source code
        │
        ▼
  Root cause report printed to console
```

`log_monitor.py` uses `docker.from_env()` — it connects to the Docker socket
and calls `container.logs()` by container name.
The watched name is hardcoded as `"my-app"` on line 49 of `log_monitor.py`.

---

## What the target application must provide

### 1. Container name

Set the container name to `my-app` in Docker Compose:

```yaml
services:
  your-app:
    container_name: my-app   # MUST match what log_monitor watches
```

Or change the name in `log_monitor.py`:

```python
follow_logs("your-actual-container-name")
```

### 2. Log format — errors to stdout/stderr

The application just needs to print errors to **stdout or stderr**.
Docker captures both automatically. No special log driver needed.

Trigger keywords that fire an investigation:

| Keyword              | Typical source                   |
|----------------------|----------------------------------|
| `ERROR`              | Any logger at ERROR level        |
| `Exception`          | Python/Java/C# exception messages|
| `Traceback`          | Python stack traces              |
| `Connection refused` | Network/DB connection failures   |
| `panic:`             | Go runtime panics                |
| `OOMKilled`          | Out-of-memory events             |
| `Segmentation fault` | C/C++ crashes                    |

If using a structured/JSON logger, ensure `ERROR` still appears as a plain
string somewhere in the output line.

### 3. Knowledge base documents

The investigation agent's quality depends entirely on the KB docs.
Add markdown files to `incident-reporting/knowledge-base/`:

```
knowledge-base/
├── architecture.md
├── database-runbook.md
├── web-runbook.md
├── error-handling-standards.md
└── your-app-runbook.md      ← ADD: your app's specific runbook
```

Each runbook must have YAML frontmatter:

```yaml
---
title: Your App Runbook
service: my-app
category: database          # or: network, memory, authentication, etc.
keywords:
  - Connection refused
  - timeout
  - OOMKilled
---

## Connection Refused

### Cause
The database host is unreachable ...

### Fix
1. Check DB container is running ...
```

After adding docs, rebuild the knowledge graph:

```bash
python graph_db.py
python vector_db.py
```

---

## Docker Compose — full integration

```yaml
version: "3.9"

services:
  # ── Your real application ──────────────────────────────────────
  your-app:
    build: ./your-app           # or image: your-image:tag
    container_name: my-app      # MUST match what log_monitor watches
    environment:
      - DATABASE_URL=postgresql://db:5432/appdb
    depends_on:
      - db

  # ── Supporting infrastructure ──────────────────────────────────
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: appdb
      POSTGRES_PASSWORD: secret

  neo4j:
    image: neo4j:5
    environment:
      NEO4J_AUTH: neo4j/nexus-dev-password
    ports:
      - "7687:7687"

  milvus:
    image: milvusdb/milvus:v2.4.0
    ports:
      - "19530:19530"

  # ── Incident monitor ───────────────────────────────────────────
  log-monitor:
    build: ./incident-reporting
    environment:
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - NEO4J_URI=bolt://neo4j:7687
      - NEO4J_USER=neo4j
      - NEO4J_PASSWORD=nexus-dev-password
      - MILVUS_URI=http://milvus:19530
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock   # CRITICAL: gives access to Docker daemon
    depends_on:
      - your-app
      - neo4j
      - milvus
```

The `/var/run/docker.sock` mount is what makes `docker.from_env()` work
inside the container — it lets the monitor follow logs of `my-app`.

---

## Dockerfile for the log monitor

`incident-reporting/` needs its own Dockerfile (does not exist yet):

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "-u", "log_monitor.py"]
```

---

## What the investigation agent does with a detected log

Example trigger: `"ERROR database query failed: Connection refused host=db:5432"`

1. Gemini receives the raw log line
2. Calls `find_runbooks_by_symptom("Connection refused", "my-app")` → finds `database-runbook.md`
3. Calls `semantic_search("Connection refused database")` → finds relevant KB chunks via Milvus
4. Calls `get_service_context("my-app")` → loads service architecture from Neo4j
5. Gemini synthesises: **root cause + suggested fix**

---

## Environment variables required

```env
# Required
GEMINI_API_KEY=your-key-here

# Optional overrides (defaults shown)
GEMINI_MODEL=gemini-2.5-flash
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=nexus-dev-password
MILVUS_URI=http://localhost:19530
```

---

## Integration checklist

- [ ] Container name is `my-app` (or `follow_logs()` updated in `log_monitor.py`)
- [ ] Application logs errors to stdout/stderr with at least one trigger keyword
- [ ] `knowledge-base/your-app-runbook.md` created with `service: my-app` frontmatter
- [ ] `graph_db.py` re-run after adding KB docs
- [ ] `vector_db.py` re-run after adding KB docs
- [ ] `GEMINI_API_KEY` set in environment / `.env`
- [ ] `/var/run/docker.sock` mounted into log-monitor container
- [ ] Neo4j running and reachable at configured URI
- [ ] Milvus running and reachable at configured URI
