# redfish.py
from exporter.config import HostConfig, RedfishSessionState
from exporter.health import HostHealth

class RedfishHost:
    """Main config class for exporter."""

    def __init__(self, config: HostConfig):
        self.cfg = config
        self.health = HostHealth(config)
        self.session = RedfishSessionState()

    @property
    def fqdn(self) -> str:
        return self.cfg.fqdn

    @property
    def group(self) -> str:
        return self.cfg.group
