# redfish.py
from exporter.config import HostConfig, RedfishSessionState
from exporter.health import HostHealth


class RedfishHost:
    """
    Main class for managing a Redfish host connection and session state.

    Attributes:
        cfg: Host configuration.
        health: Host health manager.
        session: Redfish session state.
    """

    def __init__(self, config: HostConfig) -> None:
        """
        Initialize a RedfishHost with the given configuration.

        Args:
            config: Host configuration.
        """
        self.cfg = config
        self.health = HostHealth(config)
        self.session = RedfishSessionState()

    @property
    def fqdn(self) -> str:
        """Get the Fully Qualified Domain Name of the host.

        Returns:
            str: The FQDN of the host.
        """
        return self.cfg.fqdn

    @property
    def group(self) -> str:
        """Get the group name of the host.

        Returns:
            str: The group name.
        """
        return self.cfg.group
