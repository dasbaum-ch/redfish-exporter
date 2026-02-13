# redfish.py
from exporter.config import HostConfig, RedfishSessionState
from exporter.health import HostHealth

class RedfishHost:
    """
    Main class for managing a Redfish host connection and session state.

    Attributes:
        cfg: HostConfig instance with static configuration.
        health: HostHealth instance for managing connection health.
        session: RedfishSessionState instance for session management.
    """
    def __init__(self, config: HostConfig):
        """
        Initialize a RedfishHost with the given configuration.

        Args:
            config: HostConfig instance with connection details.
        """
        self.cfg = config
        self.health = HostHealth(config)
        self.session = RedfishSessionState()

    @property
    def fqdn(self) -> str:
        return self.cfg.fqdn

    @property
    def group(self) -> str:
        return self.cfg.group
