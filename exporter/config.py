# config.py
import time
from dataclasses import dataclass, field

NO_DATA_ENTRY = "<no data>"

@dataclass(frozen=True)
class HostConfig:
    """Static host config"""

    fqdn: str
    username: str
    password: str
    verify_ssl: bool = True
    chassis: list[str] = field(default_factory=lambda: ["1"])
    group: str = "none"
    max_retries: int = 3
    backoff: int = 2
    cool_down: int = 120

@dataclass
class RedfishSessionState:
    """Save state for login, logout, sessions and vendor."""

    token: str | None = None
    logout_url: str | None = None
    vendor: str | None = None

    @property
    def is_hpe(self) -> bool:
        return bool(self.vendor and self.vendor.strip().upper().startswith("HPE"))

@dataclass
class PowerMetrics:
    """Container for Power metrics."""

    voltage: float | None = None
    watts: float | None = None
    amps: float | None = None
    serial: str | None = None
