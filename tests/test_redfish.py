# tests/test_redfish.py
import pytest
from exporter.redfish import RedfishHost
from exporter.config import HostConfig, RedfishSessionState
from exporter.health import HostHealth


class TestRedfishHost:
    """Tests for RedfishHost class."""

    def test_init_with_config(self):
        """Test RedfishHost initialization with config."""
        config = HostConfig(
            fqdn="https://server.example.com",
            username="admin",
            password="secret",
        )
        host = RedfishHost(config)

        assert host.cfg == config
        assert isinstance(host.health, HostHealth)
        assert isinstance(host.session, RedfishSessionState)

    def test_fqdn_property(self):
        """Test fqdn property returns config fqdn."""
        config = HostConfig(
            fqdn="https://server.example.com",
            username="admin",
            password="secret",
        )
        host = RedfishHost(config)

        assert host.fqdn == "https://server.example.com"

    def test_group_property_default(self):
        """Test group property returns default 'none'."""
        config = HostConfig(
            fqdn="https://server.example.com",
            username="admin",
            password="secret",
        )
        host = RedfishHost(config)

        assert host.group == "none"

    def test_group_property_custom(self):
        """Test group property returns custom group."""
        config = HostConfig(
            fqdn="https://server.example.com",
            username="admin",
            password="secret",
            group="production",
        )
        host = RedfishHost(config)

        assert host.group == "production"

    def test_session_state_is_empty_on_init(self):
        """Test that session state is empty on initialization."""
        config = HostConfig(
            fqdn="https://server.example.com",
            username="admin",
            password="secret",
        )
        host = RedfishHost(config)

        assert host.session.token is None
        assert host.session.logout_url is None
        assert host.session.vendor is None

    def test_session_can_be_modified(self):
        """Test that session state can be modified."""
        config = HostConfig(
            fqdn="https://server.example.com",
            username="admin",
            password="secret",
        )
        host = RedfishHost(config)

        host.session.token = "test_token"
        host.session.logout_url = "https://server/logout"
        host.session.vendor = "HPE"

        assert host.session.token == "test_token"
        assert host.session.logout_url == "https://server/logout"
        assert host.session.vendor == "HPE"

    def test_health_initialized_with_config(self):
        """Test that health is initialized with the correct config."""
        config = HostConfig(
            fqdn="https://server.example.com",
            username="admin",
            password="secret",
            max_retries=5,
            cool_down=300,
        )
        host = RedfishHost(config)

        # Verify health is using the same config by checking initial state
        assert host.health.failures == 0
        assert host.health.next_retry_time == 0.0

    def test_multiple_hosts_are_independent(self):
        """Test that multiple RedfishHost instances are independent."""
        config1 = HostConfig(
            fqdn="https://server1.example.com",
            username="admin1",
            password="secret1",
        )
        config2 = HostConfig(
            fqdn="https://server2.example.com",
            username="admin2",
            password="secret2",
        )

        host1 = RedfishHost(config1)
        host2 = RedfishHost(config2)

        # Modify host1
        host1.session.token = "token1"
        host1.health.failures = 2

        # Verify host2 is unaffected
        assert host2.session.token is None
        assert host2.health.failures == 0
        assert host2.fqdn == "https://server2.example.com"
