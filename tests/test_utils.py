# tests/test_utils.py
import pytest
from unittest.mock import patch, MagicMock
from aiohttp import ClientTimeout, BasicAuth
from exporter.utils import (
    get_aiohttp_request_kwargs,
    safe_get,
    validate_host_config,
    safe_update_metrics,
)
from exporter.config import HostConfig, PowerMetrics
from exporter.redfish import RedfishHost


class TestGetAiohttpRequestKwargs:
    """Tests for get_aiohttp_request_kwargs function."""

    def test_basic_kwargs_with_ssl_true(self):
        """Test kwargs generation with SSL verification enabled."""
        kwargs = get_aiohttp_request_kwargs(verify_ssl=True)
        assert kwargs["ssl"] is True
        assert isinstance(kwargs["timeout"], ClientTimeout)
        assert kwargs["timeout"].total == 10
        assert kwargs["headers"] == {}
        assert kwargs["auth"] is None

    def test_basic_kwargs_with_ssl_false(self):
        """Test kwargs generation with SSL verification disabled."""
        kwargs = get_aiohttp_request_kwargs(verify_ssl=False)
        assert kwargs["ssl"] is False

    def test_custom_timeout(self):
        """Test kwargs with custom timeout."""
        kwargs = get_aiohttp_request_kwargs(verify_ssl=True, timeout_seconds=30)
        assert kwargs["timeout"].total == 30

    def test_custom_headers(self):
        """Test kwargs with custom headers."""
        headers = {"X-Auth-Token": "abc123", "Content-Type": "application/json"}
        kwargs = get_aiohttp_request_kwargs(verify_ssl=True, headers=headers)
        assert kwargs["headers"] == headers

    def test_with_auth(self):
        """Test kwargs with authentication."""
        auth = BasicAuth("user", "pass")
        kwargs = get_aiohttp_request_kwargs(verify_ssl=True, auth=auth)
        assert kwargs["auth"] == auth

    def test_all_options(self):
        """Test kwargs with all options specified."""
        headers = {"X-Custom": "value"}
        auth = BasicAuth("user", "pass")
        kwargs = get_aiohttp_request_kwargs(
            verify_ssl=False,
            timeout_seconds=60,
            headers=headers,
            auth=auth,
        )
        assert kwargs["ssl"] is False
        assert kwargs["timeout"].total == 60
        assert kwargs["headers"] == headers
        assert kwargs["auth"] == auth


class TestSafeGet:
    """Tests for safe_get function."""

    def test_single_key_exists(self):
        """Test safe_get with a single key that exists."""
        data = {"key": "value"}
        assert safe_get(data, "key") == "value"

    def test_single_key_missing(self):
        """Test safe_get with a single missing key."""
        data = {"key": "value"}
        assert safe_get(data, "other") is None

    def test_single_key_missing_with_default(self):
        """Test safe_get with a missing key and custom default."""
        data = {"key": "value"}
        assert safe_get(data, "other", default="fallback") == "fallback"

    def test_nested_keys_exist(self):
        """Test safe_get with nested keys that exist."""
        data = {"level1": {"level2": {"level3": "deep_value"}}}
        assert safe_get(data, "level1", "level2", "level3") == "deep_value"

    def test_nested_keys_partial_exists(self):
        """Test safe_get where nested path is incomplete."""
        data = {"level1": {"level2": "value"}}
        assert safe_get(data, "level1", "level2", "level3") is None

    def test_nested_key_missing_at_start(self):
        """Test safe_get where first key is missing."""
        data = {"level1": {"level2": "value"}}
        assert safe_get(data, "missing", "level2") is None

    def test_none_data(self):
        """Test safe_get with None data."""
        assert safe_get(None, "key") is None

    def test_none_data_with_default(self):
        """Test safe_get with None data and custom default."""
        assert safe_get(None, "key", default="default_value") == "default_value"

    def test_empty_dict(self):
        """Test safe_get with empty dictionary."""
        assert safe_get({}, "key") is None

    def test_value_is_none(self):
        """Test safe_get where the value itself is None."""
        data = {"key": None}
        assert safe_get(data, "key") is None

    def test_value_is_false(self):
        """Test safe_get where the value is False (falsy but valid)."""
        data = {"key": False}
        assert safe_get(data, "key") is False

    def test_value_is_zero(self):
        """Test safe_get where the value is 0 (falsy but valid)."""
        data = {"key": 0}
        assert safe_get(data, "key") == 0

    def test_non_dict_intermediate_value(self):
        """Test safe_get where intermediate value is not a dict."""
        data = {"level1": "not_a_dict"}
        assert safe_get(data, "level1", "level2") is None


class TestValidateHostConfig:
    """Tests for validate_host_config function."""

    def test_valid_full_config(self):
        """Test validation with all fields provided."""
        config = {
            "fqdn": "https://server.example.com",
            "username": "admin",
            "password": "secret",
            "verify_ssl": False,
            "chassis": ["1", "2"],
            "group": "production",
            "max_retries": 5,
            "backoff": 3,
            "cool_down": 300,
        }
        global_config = {}
        result = validate_host_config(config, global_config)

        assert result["fqdn"] == "https://server.example.com"
        assert result["username"] == "admin"
        assert result["password"] == "secret"
        assert result["verify_ssl"] is False
        assert result["chassis"] == ["1", "2"]
        assert result["group"] == "production"
        assert result["max_retries"] == 5
        assert result["backoff"] == 3
        assert result["cool_down"] == 300

    def test_minimal_config_with_global_defaults(self):
        """Test validation with minimal host config and global defaults."""
        config = {"fqdn": "https://server.example.com"}
        global_config = {
            "username": "global_admin",
            "password": "global_secret",
        }
        result = validate_host_config(config, global_config)

        assert result["fqdn"] == "https://server.example.com"
        assert result["username"] == "global_admin"
        assert result["password"] == "global_secret"
        assert result["verify_ssl"] is True  # Default
        assert result["chassis"] == ["1"]  # Default
        assert result["group"] == "none"  # Default

    def test_string_config_converted_to_dict(self):
        """Test that string config is converted to dict with fqdn."""
        config = "https://server.example.com"
        global_config = {
            "username": "admin",
            "password": "secret",
        }
        result = validate_host_config(config, global_config)
        assert result["fqdn"] == "https://server.example.com"

    def test_host_config_overrides_global(self):
        """Test that host config overrides global config."""
        config = {
            "fqdn": "https://server.example.com",
            "username": "host_user",
            "password": "host_pass",
            "verify_ssl": False,
        }
        global_config = {
            "username": "global_user",
            "password": "global_pass",
            "verify_ssl": True,
        }
        result = validate_host_config(config, global_config)

        assert result["username"] == "host_user"
        assert result["password"] == "host_pass"
        assert result["verify_ssl"] is False

    def test_missing_fqdn_raises_error(self):
        """Test that missing fqdn raises ValueError."""
        config = {
            "username": "admin",
            "password": "secret",
        }
        global_config = {}
        with pytest.raises(ValueError, match="Missing required field in config: fqdn"):
            validate_host_config(config, global_config)

    def test_missing_username_raises_error(self):
        """Test that missing username raises ValueError."""
        config = {
            "fqdn": "https://server.example.com",
            "password": "secret",
        }
        global_config = {}
        with pytest.raises(
            ValueError, match="Missing required field in config: username"
        ):
            validate_host_config(config, global_config)

    def test_missing_password_raises_error(self):
        """Test that missing password raises ValueError."""
        config = {
            "fqdn": "https://server.example.com",
            "username": "admin",
        }
        global_config = {}
        with pytest.raises(
            ValueError, match="Missing required field in config: password"
        ):
            validate_host_config(config, global_config)

    def test_global_config_provides_all_defaults(self):
        """Test that all optional fields come from global config."""
        config = {
            "fqdn": "https://server.example.com",
        }
        global_config = {
            "username": "global_admin",
            "password": "global_secret",
            "verify_ssl": False,
            "chassis": ["1", "2", "3"],
            "group": "global_group",
            "max_retries": 10,
            "backoff": 5,
            "cool_down": 600,
        }
        result = validate_host_config(config, global_config)

        assert result["verify_ssl"] is False
        assert result["chassis"] == ["1", "2", "3"]
        assert result["group"] == "global_group"
        assert result["max_retries"] == 10
        assert result["backoff"] == 5
        assert result["cool_down"] == 600


class TestSafeUpdateMetrics:
    """Tests for safe_update_metrics function."""

    def test_safe_update_metrics_with_valid_metrics(self):
        """Test that metrics are updated when valid PowerMetrics is provided."""
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
            )
        )
        metrics = PowerMetrics(
            serial="PSU001",
            voltage=230,
            watts=500,
            amps=2.17,
        )

        with patch(
            "exporter.metrics.update_prometheus_metrics"
        ) as mock_update:
            safe_update_metrics(host, metrics)
            mock_update.assert_called_once_with(host, metrics)

    def test_safe_update_metrics_with_none(self):
        """Test that no update happens when metrics is None."""
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
            )
        )

        with patch(
            "exporter.metrics.update_prometheus_metrics"
        ) as mock_update:
            safe_update_metrics(host, None)
            mock_update.assert_not_called()
