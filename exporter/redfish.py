# redfish.py
from .config import HostConfig, RedfishSessionState
from .health import HostHealth


class RedfishHost:
    """Manages a Redfish host connection and session state."""

    def __init__(self, config: HostConfig) -> None:
        self.cfg = config
        self.health = HostHealth(config)
        self.session = RedfishSessionState()

    @property
    def fqdn(self) -> str:
        return self.cfg.fqdn

    @property
    def group(self) -> str:
        return self.cfg.group
