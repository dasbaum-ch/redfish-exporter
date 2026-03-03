# tests/test_config.py
import pytest
from exporter.config import (
    HostConfig,
    RedfishSessionState,
    PowerMetrics,
    NO_DATA_ENTRY,
)


class TestHostConfig:
    """Tests for HostConfig dataclass."""

    def test_host_config_required_fields(self):
        """Test HostConfig with only required fields."""
        config = HostConfig(
            fqdn="https://server.example.com",
            username="admin",
            password="secret",
        )
        assert config.fqdn == "https://server.example.com"
        assert config.username == "admin"
        assert config.password == "secret"

    def test_host_config_default_values(self):
        """Test HostConfig default values."""
        config = HostConfig(
            fqdn="https://server.example.com",
            username="admin",
            password="secret",
        )
        assert config.verify_ssl is True
        assert config.chassis == ["1"]
        assert config.group == "none"
        assert config.max_retries == 3
        assert config.backoff == 2
        assert config.cool_down == 120

    def test_host_config_custom_values(self):
        """Test HostConfig with custom values."""
        config = HostConfig(
            fqdn="https://server.example.com",
            username="admin",
            password="secret",
            verify_ssl=False,
            chassis=["1", "2"],
            group="production",
            max_retries=5,
            backoff=3,
            cool_down=300,
        )
        assert config.verify_ssl is False
        assert config.chassis == ["1", "2"]
        assert config.group == "production"
        assert config.max_retries == 5
        assert config.backoff == 3
        assert config.cool_down == 300

    def test_host_config_is_frozen(self):
        """Test that HostConfig is immutable (frozen)."""
        config = HostConfig(
            fqdn="https://server.example.com",
            username="admin",
            password="secret",
        )
        with pytest.raises(AttributeError):
            config.fqdn = "https://other.example.com"


class TestRedfishSessionState:
    """Tests for RedfishSessionState dataclass."""

    def test_session_state_default_values(self):
        """Test RedfishSessionState default values."""
        state = RedfishSessionState()
        assert state.token is None
        assert state.logout_url is None
        assert state.vendor is None

    def test_session_state_with_values(self):
        """Test RedfishSessionState with set values."""
        state = RedfishSessionState(
            token="abc123",
            logout_url="https://server/logout",
            vendor="HPE",
        )
        assert state.token == "abc123"
        assert state.logout_url == "https://server/logout"
        assert state.vendor == "HPE"

    def test_session_state_is_mutable(self):
        """Test that RedfishSessionState is mutable."""
        state = RedfishSessionState()
        state.token = "new_token"
        assert state.token == "new_token"

    def test_is_hpe_with_hpe_vendor(self):
        """Test is_hpe property returns True for HPE vendor."""
        state = RedfishSessionState(vendor="HPE")
        assert state.is_hpe is True

    def test_is_hpe_with_hpe_prefix(self):
        """Test is_hpe property returns True for vendor starting with HPE."""
        state = RedfishSessionState(vendor="HPE ProLiant")
        assert state.is_hpe is True

    def test_is_hpe_case_insensitive(self):
        """Test is_hpe property is case-insensitive."""
        state = RedfishSessionState(vendor="hpe")
        assert state.is_hpe is True

        state2 = RedfishSessionState(vendor="Hpe Server")
        assert state2.is_hpe is True

    def test_is_hpe_with_whitespace(self):
        """Test is_hpe property handles leading whitespace."""
        state = RedfishSessionState(vendor="  HPE")
        assert state.is_hpe is True

    def test_is_hpe_with_non_hpe_vendor(self):
        """Test is_hpe property returns False for non-HPE vendor."""
        state = RedfishSessionState(vendor="Dell")
        assert state.is_hpe is False

    def test_is_hpe_with_none_vendor(self):
        """Test is_hpe property returns False when vendor is None."""
        state = RedfishSessionState(vendor=None)
        assert state.is_hpe is False

    def test_is_hpe_with_empty_vendor(self):
        """Test is_hpe property returns False for empty vendor string."""
        state = RedfishSessionState(vendor="")
        assert state.is_hpe is False


class TestPowerMetrics:
    """Tests for PowerMetrics dataclass."""

    def test_power_metrics_default_values(self):
        """Test PowerMetrics default values."""
        metrics = PowerMetrics()
        assert metrics.voltage is None
        assert metrics.watts is None
        assert metrics.amps is None
        assert metrics.serial is None

    def test_power_metrics_with_values(self):
        """Test PowerMetrics with set values."""
        metrics = PowerMetrics(
            voltage=120.5,
            watts=500.0,
            amps=4.2,
            serial="PSU12345",
        )
        assert metrics.voltage == 120.5
        assert metrics.watts == 500.0
        assert metrics.amps == 4.2
        assert metrics.serial == "PSU12345"

    def test_power_metrics_partial_values(self):
        """Test PowerMetrics with only some values set."""
        metrics = PowerMetrics(watts=300.0)
        assert metrics.watts == 300.0
        assert metrics.voltage is None
        assert metrics.amps is None
        assert metrics.serial is None

    def test_power_metrics_partial_values_with_none(self):
        """Test PowerMetrics with some values set to None."""
        metrics = PowerMetrics(
            voltage=None,
            watts=300.0,
            amps=None,
            serial="PSU12345",
        )
        assert metrics.voltage is None
        assert metrics.watts == 300.0
        assert metrics.amps is None
        assert metrics.serial == "PSU12345"


class TestModuleConstants:
    """Tests for module-level constants."""

    def test_no_data_entry_constant(self):
        """Test NO_DATA_ENTRY constant value."""
        assert NO_DATA_ENTRY == "<no data>"

    def test_no_data_entry_constant_type(self):
        """Test NO_DATA_ENTRY constant type is str."""
        assert isinstance(NO_DATA_ENTRY, str)
