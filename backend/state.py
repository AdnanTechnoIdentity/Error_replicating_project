import asyncio
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from datetime import datetime, timezone


@dataclass
class ServiceState:
    status: str = "HEALTHY"
    active_scenario: Optional[str] = None
    response_time_ms: int = 80
    error_rate: float = 0.0
    db_connections: int = 4
    db_max: int = 50


_HEALTHY_DEFAULTS: Dict[str, Dict] = {
    "payments": {"response_time_ms": 80, "db_connections": 4},
    "orders": {"response_time_ms": 84, "db_connections": 4},
    "users": {"response_time_ms": 92, "db_connections": 2},
}


class AppState:
    def __init__(self) -> None:
        self.services: Dict[str, ServiceState] = {
            "payments": ServiceState(db_connections=4),
            "orders": ServiceState(db_connections=4),
            "users": ServiceState(db_connections=2),
        }
        self.recent_errors: List[Dict] = []
        self.recovery_tasks: Dict[str, asyncio.Task] = {}
        self.background_tasks: Dict[str, List[asyncio.Task]] = {
            "payments": [],
            "orders": [],
            "users": [],
        }
        # Per-service release events for scenarios that hold resources
        self._release_events: Dict[str, Optional[asyncio.Event]] = {
            "payments": None,
            "orders": None,
            "users": None,
        }
        # Holds reference to prevent GC during memory_spike
        self._memory_holder: Optional[bytearray] = None

        # In-memory "database"
        self.transactions: Dict[str, Dict] = {}
        self.orders: Dict[str, Dict] = {}
        self.users: Dict[str, Dict] = {
            "U-001": {"id": "U-001", "email": "alice@example.com", "name": "Alice Johnson"},
            "U-002": {"id": "U-002", "email": "bob@example.com", "name": "Bob Smith"},
        }
        self._error_counter: int = 0

    def add_error(self, service: str, scenario: str, severity: str, message: str) -> Dict:
        self._error_counter += 1
        event = {
            "id": f"ERR-{self._error_counter:03d}",
            "service": service,
            "scenario": scenario,
            "severity": severity,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "message": message,
        }
        self.recent_errors.insert(0, event)
        self.recent_errors = self.recent_errors[:50]
        return event

    def recover(self, service: str) -> None:
        svc = self.services[service]
        svc.status = "HEALTHY"
        svc.active_scenario = None
        svc.error_rate = 0.0
        defaults = _HEALTHY_DEFAULTS[service]
        svc.response_time_ms = defaults["response_time_ms"]
        svc.db_connections = defaults["db_connections"]

    def to_dict(self) -> Dict:
        return {
            "services": {
                name: {
                    "status": svc.status,
                    "active_scenario": svc.active_scenario,
                    "response_time_ms": svc.response_time_ms,
                    "error_rate": svc.error_rate,
                    "db_connections": svc.db_connections,
                    "db_max": svc.db_max,
                }
                for name, svc in self.services.items()
            },
            "recent_errors": self.recent_errors,
        }


app_state = AppState()
