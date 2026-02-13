# tests/test_api.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from exporter.api import (
    fetch_with_retry,
    normalize_url,
    process_power_supply,
    get_power_data,
    get_system_info,
)
from exporter.redfish import RedfishHost
from exporter.config import HostConfig


class TestNormalizeUrl:
    def test_url_with_trailing_slash(self):
        assert normalize_url("http://example.com/api/") == "http://example.com/api"

    def test_url_without_trailing_slash(self):
        assert normalize_url("http://example.com/api") == "http://example.com/api"

    def test_root_url_with_trailing_slash(self):
        assert normalize_url("http://example.com/") == "http://example.com"

    def test_empty_string(self):
        assert normalize_url("") == ""


def create_mock_response(data, status=200, headers=None):
    """Create a mock aiohttp response."""
    mock_response = MagicMock()
    mock_response.status = status
    mock_response.json = AsyncMock(return_value=data)
    mock_response.headers = headers or {
        "X-Auth-Token": "test-token",
        "Location": "/logout",
    }
    return mock_response


def create_mock_session(response_data, status=200):
    """Create a mock aiohttp session with proper async context manager."""
    session = MagicMock()
    mock_response = create_mock_response(response_data, status)

    # Create async context manager using MagicMock
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    session.get.return_value = mock_cm
    session.post.return_value = mock_cm
    return session


class TestFetchWithRetry:
    @pytest.mark.asyncio
    async def test_fetch_success_non_hpe(self):
        session = create_mock_session({"key": "value"})
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
            )
        )
        # Set vendor to non-HPE to skip vendor probing
        host.session.vendor = "Dell"

        result = await fetch_with_retry(
            session, host, "http://localhost:5000/redfish/v1"
        )
        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_fetch_host_in_cooldown(self):
        session = create_mock_session({"key": "value"})
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
                cool_down=60,
            )
        )
        # Mark many failures to trigger cooldown
        for _ in range(10):
            host.health.mark_failure()

        result = await fetch_with_retry(
            session, host, "http://localhost:5000/redfish/v1"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_with_hpe_token(self):
        session = create_mock_session({"data": "test"})
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
            )
        )
        host.session.vendor = "HPE"
        host.session.token = "existing-token"

        result = await fetch_with_retry(
            session, host, "http://localhost:5000/redfish/v1"
        )
        assert result == {"data": "test"}

    @pytest.mark.asyncio
    async def test_fetch_http_error_retry(self):
        session = MagicMock()
        mock_response = create_mock_response({}, status=500)

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        session.get.return_value = mock_cm

        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
                max_retries=2,
                backoff=0,
            )
        )
        host.session.vendor = "Dell"

        result = await fetch_with_retry(
            session, host, "http://localhost:5000/redfish/v1"
        )
        assert result is None
        # Should have retried
        assert session.get.call_count == 2

    @pytest.mark.asyncio
    async def test_fetch_401_clears_hpe_token(self):
        session = MagicMock()
        mock_response = create_mock_response({}, status=401)

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        session.get.return_value = mock_cm

        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
                max_retries=1,
                backoff=0,
            )
        )
        host.session.vendor = "HPE"
        host.session.token = "test-token"

        await fetch_with_retry(session, host, "http://localhost:5000/redfish/v1")
        # Token should be cleared on 401
        assert host.session.token is None


class TestProcessPowerSupply:
    @pytest.mark.asyncio
    async def test_process_legacy_power_api(self):
        session = create_mock_session({})
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
            )
        )
        host.session.vendor = "Dell"

        psu_data = {
            "SerialNumber": "PSU123",
            "LineInputVoltage": 230,
            "PowerInputWatts": 500,
            "InputCurrentAmps": 2.17,
        }

        result = await process_power_supply(session, host, psu_data, "Power")
        assert result is not None
        assert result.serial == "PSU123"
        assert result.voltage == 230
        assert result.watts == 500
        assert result.amps == 2.17

    @pytest.mark.asyncio
    async def test_process_legacy_power_api_calculates_amps(self):
        session = create_mock_session({})
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
            )
        )
        host.session.vendor = "Dell"

        psu_data = {
            "SerialNumber": "PSU123",
            "LineInputVoltage": 200,
            "PowerInputWatts": 400,
        }

        result = await process_power_supply(session, host, psu_data, "Power")
        assert result is not None
        assert result.amps == 2.0  # 400 / 200

    @pytest.mark.asyncio
    async def test_process_power_subsystem_api(self):
        metrics_data = {
            "InputVoltage": {"Reading": 240},
            "InputPowerWatts": {"Reading": 600},
            "InputCurrentAmps": {"Reading": 2.5},
        }
        session = create_mock_session(metrics_data)
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
            )
        )
        host.session.vendor = "Dell"

        psu_data = {
            "SerialNumber": "PSU456",
            "Metrics": {"@odata.id": "/redfish/v1/PowerSubsystem/1/Metrics"},
        }

        result = await process_power_supply(session, host, psu_data, "PowerSubsystem")
        assert result is not None
        assert result.serial == "PSU456"
        assert result.voltage == 240
        assert result.watts == 600
        assert result.amps == 2.5

    @pytest.mark.asyncio
    async def test_process_legacy_uses_last_power_output(self):
        session = create_mock_session({})
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
            )
        )
        host.session.vendor = "Dell"

        psu_data = {
            "SerialNumber": "PSU789",
            "LineInputVoltage": 220,
            "LastPowerOutputWatts": 350,
        }

        result = await process_power_supply(session, host, psu_data, "Power")
        assert result is not None
        assert result.watts == 350


class TestGetPowerData:
    @pytest.mark.asyncio
    async def test_get_power_data_no_root(self):
        session = MagicMock()
        mock_response = create_mock_response({}, status=500)

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        session.get.return_value = mock_cm

        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
                max_retries=1,
                backoff=0,
            )
        )
        host.session.vendor = "Dell"

        # Should not raise, just return early
        await get_power_data(session, host, False)

    @pytest.mark.asyncio
    async def test_get_power_data_no_chassis(self):
        session = create_mock_session({"RedfishVersion": "1.0.0"})
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
            )
        )
        host.session.vendor = "Dell"

        # Should not raise, just return early
        await get_power_data(session, host, False)


class TestGetSystemInfo:
    @pytest.mark.asyncio
    async def test_get_system_info_no_root(self):
        session = MagicMock()
        mock_response = create_mock_response({}, status=500)

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        session.get.return_value = mock_cm

        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
                max_retries=1,
                backoff=0,
            )
        )
        host.session.vendor = "Dell"

        # Should not raise, just return early
        await get_system_info(session, host)

    @pytest.mark.asyncio
    async def test_get_system_info_no_systems(self):
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
            )
        )
        host.session.vendor = "Dell"

        # Mock the responses: first returns root, second returns None (no systems)
        responses = [
            {"RedfishVersion": "1.0.0"},  # Root response
            None,  # Systems response fails
        ]

        session = MagicMock()
        with patch(
            "exporter.api.fetch_with_retry",
            side_effect=responses,
        ):
            await get_system_info(session, host)
