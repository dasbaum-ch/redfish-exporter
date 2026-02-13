from dataclasses import dataclass, field
from typing import Optional, List

NO_DATA_ENTRY: str = "<no data>"

@dataclass(frozen=True)
class HostConfig:
    """Static configuration for a Redfish host.

    Attributes:
        fqdn: Fully Qualified Domain Name of the host.
        username: Username for authentication.
        password: Password for authentication.
        verify_ssl: If True, verify SSL certificates. Defaults to True.
        chassis: List of chassis IDs to monitor. Defaults to ["1"].
        group: Group name for the host. Defaults to "none".
        max_retries: Maximum number of retries for failed requests. Defaults to 3.
        backoff: Backoff factor for retries. Defaults to 2.
        cool_down: Cool-down period in seconds after max retries. Defaults to 120.
    """
    fqdn: str
    username: str
    password: str
    verify_ssl: bool = True
    chassis: List[str] = field(default_factory=lambda: ["1"])
    group: str = "none"
    max_retries: int = 3
    backoff: int = 2
    cool_down: int = 120

@dataclass
class RedfishSessionState:
    """State container for Redfish session management.

    Attributes:
        token: Current session token.
        logout_url: URL to log out from the session.
        vendor: Vendor name of the Redfish host.
    """
    token: Optional[str] = None
    logout_url: Optional[str] = None
    vendor: Optional[str] = None

    @property
    def is_hpe(self) -> bool:
        """Check if the host vendor is HPE.

        Returns:
            bool: True if the vendor is HPE, False otherwise.
        """
        return bool(self.vendor and self.vendor.strip().upper().startswith("HPE"))

@dataclass
class PowerMetrics:
    """Container for power metrics extracted from a Redfish host.

    Attributes:
        voltage: Input voltage in volts.
        watts: Power consumption in watts.
        amps: Current draw in amps.
        serial: Serial number of the power supply.
    """
    voltage: Optional[float] = None
    watts: Optional[float] = None
    amps: Optional[float] = None
    serial: Optional[str] = None
