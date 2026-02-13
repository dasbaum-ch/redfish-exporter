# config.py
from dataclasses import dataclass, field

NO_DATA_ENTRY = "<no data>"

@dataclass(frozen=True)
class HostConfig:
    """
    Static configuration for a Redfish host.

    Attributes:
        fqdn: Fully Qualified Domain Name of the host.
        username: Username for authentication.
        password: Password for authentication.
        verify_ssl: If True, verify SSL certificates.
        chassis: List of chassis IDs to monitor.
        group: Group name for the host.
        max_retries: Maximum number of retries for failed requests.
        backoff: Backoff factor for retries.
        cool_down: Cool-down period in seconds after max retries.
    """

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
    """
    Container for power metrics extracted from a Redfish host.

    Attributes:
        voltage: Input voltage in volts.
        watts: Power consumption in watts.
        amps: Current draw in amps.
        serial: Serial number of the power supply.
    """
    voltage: float | None = None
    watts: float | None = None
    amps: float | None = None
    serial: str | None = None
