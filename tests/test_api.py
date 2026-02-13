# tests/test_api.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import aiohttp
from exporter.api import (
    fetch_with_retry,
    normalize_url,
    process_power_supply,
    get_power_data,
    get_system_info,
)
from exporter.redfish import RedfishHost
from exporter.config import HostConfig, NO_DATA_ENTRY


class TestNormalizeUrl:
    """Tests for normalize_url function."""

    def test_url_with_trailing_slash(self):
        """Test URL with trailing slash is normalized."""
        assert normalize_url("http://example.com/api/") == "http://example.com/api"

    def test_url_without_trailing_slash(self):
        """Test URL without trailing slash is unchanged."""
        assert normalize_url("http://example.com/api") == "http://example.com/api"

    def test_root_url_with_trailing_slash(self):
        """Test root URL with trailing slash."""
        assert normalize_url("http://example.com/") == "http://example.com"

    def test_empty_string(self):
        """Test empty string."""
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
    """Tests for fetch_with_retry function."""

    @pytest.mark.asyncio
    async def test_fetch_success_non_hpe(self):
        """Test successful fetch for non-HPE host."""
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
        """Test fetch returns None when host is in cooldown."""
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
        """Test fetch with HPE authentication token."""
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
        """Test fetch retries on HTTP 500 error."""
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
        """Test that 401 response clears HPE token."""
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

    @pytest.mark.asyncio
    async def test_fetch_probes_vendor_when_none(self):
        """Test that vendor is probed when not set."""
        session = create_mock_session({"key": "value"})
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
            )
        )
        # Vendor is None, so probe_vendor should be called
        assert host.session.vendor is None

        with patch("exporter.api.probe_vendor", new_callable=AsyncMock) as mock_probe:
            mock_probe.return_value = "Dell"
            result = await fetch_with_retry(
                session, host, "http://localhost:5000/redfish/v1"
            )
            mock_probe.assert_called_once()
            assert host.session.vendor == "Dell"
            assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_fetch_hpe_login_failure_returns_none(self):
        """Test that HPE login failure returns None."""
        session = create_mock_session({})
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
            )
        )
        host.session.vendor = "HPE"
        host.session.token = None

        with patch("exporter.api.login_hpe", new_callable=AsyncMock) as mock_login:
            mock_login.return_value = False  # Login fails
            result = await fetch_with_retry(
                session, host, "http://localhost:5000/redfish/v1"
            )
            mock_login.assert_called_once()
            assert result is None

    @pytest.mark.asyncio
    async def test_fetch_timeout_error_retry(self):
        """Test fetch retries on TimeoutError."""
        session = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError())
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
    async def test_fetch_client_error_retry(self):
        """Test fetch retries on ClientError."""
        session = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(
            side_effect=aiohttp.ClientError("Connection failed")
        )
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


class TestProcessPowerSupply:
    """Tests for process_power_supply function."""

    @pytest.mark.asyncio
    async def test_process_legacy_power_api(self):
        """Test processing PSU data from legacy Power API."""
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
        """Test that amps is calculated when not provided."""
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
        """Test processing PSU data from PowerSubsystem API."""
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
        """Test that LastPowerOutputWatts is used as fallback."""
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
    """Tests for get_power_data function."""

    @pytest.mark.asyncio
    async def test_get_power_data_no_root(self):
        """Test get_power_data returns early when root fetch fails."""
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
        """Test get_power_data returns early when no Chassis path."""
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

    @pytest.mark.asyncio
    async def test_get_power_data_full_flow_power_subsystem(self):
        """Test full power data collection with PowerSubsystem API."""
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
                chassis=["1"],
            )
        )
        host.session.vendor = "Dell"

        # Define mock responses for each fetch call
        responses = [
            # Root response
            {"Chassis": {"@odata.id": "/redfish/v1/Chassis"}},
            # Chassis collection
            {"Members": [{"@odata.id": "/redfish/v1/Chassis/1"}]},
            # Chassis member data
            {"PowerSubsystem": {"@odata.id": "/redfish/v1/Chassis/1/PowerSubsystem"}},
            # PowerSubsystem data
            {"PowerSupplies": {"@odata.id": "/redfish/v1/Chassis/1/PowerSubsystem/PowerSupplies"}},
            # PowerSupplies collection
            {"Members": [{"@odata.id": "/redfish/v1/Chassis/1/PowerSubsystem/PowerSupplies/1"}]},
            # Individual PSU data
            {"SerialNumber": "PSU001", "Metrics": {"@odata.id": "/redfish/v1/Chassis/1/PowerSubsystem/PowerSupplies/1/Metrics"}},
            # PSU Metrics
            {
                "InputVoltage": {"Reading": 230},
                "InputPowerWatts": {"Reading": 500},
                "InputCurrentAmps": {"Reading": 2.17},
            },
        ]

        session = MagicMock()
        with patch(
            "exporter.api.fetch_with_retry",
            new_callable=AsyncMock,
            side_effect=responses,
        ):
            with patch("exporter.api.safe_update_metrics") as mock_update:
                await get_power_data(session, host, False)
                mock_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_power_data_full_flow_legacy_power(self):
        """Test full power data collection with legacy Power API."""
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
                chassis=["1"],
            )
        )
        host.session.vendor = "Dell"

        # Define mock responses for legacy Power API path
        responses = [
            # Root response
            {"Chassis": {"@odata.id": "/redfish/v1/Chassis"}},
            # Chassis collection
            {"Members": [{"@odata.id": "/redfish/v1/Chassis/1"}]},
            # Chassis member data (legacy Power API)
            {"Power": {"@odata.id": "/redfish/v1/Chassis/1/Power"}},
            # Power data with PSUs
            {
                "PowerSupplies": [
                    {
                        "SerialNumber": "PSU001",
                        "LineInputVoltage": 230,
                        "PowerInputWatts": 500,
                    }
                ]
            },
        ]

        session = MagicMock()
        with patch(
            "exporter.api.fetch_with_retry",
            new_callable=AsyncMock,
            side_effect=responses,
        ):
            with patch("exporter.api.safe_update_metrics") as mock_update:
                await get_power_data(session, host, show_deprecated_warnings=True)
                mock_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_power_data_skips_non_matching_chassis(self):
        """Test that non-matching chassis IDs are skipped."""
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
                chassis=["2"],  # Only chassis 2
            )
        )
        host.session.vendor = "Dell"

        responses = [
            # Root response
            {"Chassis": {"@odata.id": "/redfish/v1/Chassis"}},
            # Chassis collection with chassis 1 (which should be skipped)
            {"Members": [{"@odata.id": "/redfish/v1/Chassis/1"}]},
        ]

        session = MagicMock()
        with patch(
            "exporter.api.fetch_with_retry",
            new_callable=AsyncMock,
            side_effect=responses,
        ):
            with patch("exporter.api.safe_update_metrics") as mock_update:
                await get_power_data(session, host, False)
                # Should not update metrics because chassis 1 is not in allowed list
                mock_update.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_power_data_empty_member_url(self):
        """Test that empty member URLs are skipped."""
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
                chassis=["1"],
            )
        )
        host.session.vendor = "Dell"

        responses = [
            # Root response
            {"Chassis": {"@odata.id": "/redfish/v1/Chassis"}},
            # Chassis collection with empty URL
            {"Members": [{"@odata.id": ""}]},
        ]

        session = MagicMock()
        with patch(
            "exporter.api.fetch_with_retry",
            new_callable=AsyncMock,
            side_effect=responses,
        ):
            await get_power_data(session, host, False)

    @pytest.mark.asyncio
    async def test_get_power_data_chassis_collection_none(self):
        """Test handling when chassis collection fetch returns None."""
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
            )
        )
        host.session.vendor = "Dell"

        responses = [
            # Root response
            {"Chassis": {"@odata.id": "/redfish/v1/Chassis"}},
            # Chassis collection fetch fails
            None,
        ]

        session = MagicMock()
        with patch(
            "exporter.api.fetch_with_retry",
            new_callable=AsyncMock,
            side_effect=responses,
        ):
            await get_power_data(session, host, False)

    @pytest.mark.asyncio
    async def test_get_power_data_no_power_endpoint(self):
        """Test handling when chassis has no power endpoint."""
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
                chassis=["1"],
            )
        )
        host.session.vendor = "Dell"

        responses = [
            # Root response
            {"Chassis": {"@odata.id": "/redfish/v1/Chassis"}},
            # Chassis collection
            {"Members": [{"@odata.id": "/redfish/v1/Chassis/1"}]},
            # Chassis member data with no Power or PowerSubsystem
            {"Name": "Chassis 1"},
        ]

        session = MagicMock()
        with patch(
            "exporter.api.fetch_with_retry",
            new_callable=AsyncMock,
            side_effect=responses,
        ):
            await get_power_data(session, host, False)

    @pytest.mark.asyncio
    async def test_get_power_data_power_subsystem_no_psu_url(self):
        """Test handling when PowerSubsystem has no PowerSupplies URL."""
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
                chassis=["1"],
            )
        )
        host.session.vendor = "Dell"

        responses = [
            # Root response
            {"Chassis": {"@odata.id": "/redfish/v1/Chassis"}},
            # Chassis collection
            {"Members": [{"@odata.id": "/redfish/v1/Chassis/1"}]},
            # Chassis member data
            {"PowerSubsystem": {"@odata.id": "/redfish/v1/Chassis/1/PowerSubsystem"}},
            # PowerSubsystem data without PowerSupplies
            {"Status": {"State": "Enabled"}},
        ]

        session = MagicMock()
        with patch(
            "exporter.api.fetch_with_retry",
            new_callable=AsyncMock,
            side_effect=responses,
        ):
            await get_power_data(session, host, False)

    @pytest.mark.asyncio
    async def test_get_power_data_member_data_none(self):
        """Test handling when chassis member data fetch returns None."""
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
                chassis=["1"],
            )
        )
        host.session.vendor = "Dell"

        responses = [
            # Root response
            {"Chassis": {"@odata.id": "/redfish/v1/Chassis"}},
            # Chassis collection
            {"Members": [{"@odata.id": "/redfish/v1/Chassis/1"}]},
            # Chassis member data fetch fails
            None,
        ]

        session = MagicMock()
        with patch(
            "exporter.api.fetch_with_retry",
            new_callable=AsyncMock,
            side_effect=responses,
        ):
            await get_power_data(session, host, False)

    @pytest.mark.asyncio
    async def test_get_power_data_power_data_none(self):
        """Test handling when power data fetch returns None."""
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
                chassis=["1"],
            )
        )
        host.session.vendor = "Dell"

        responses = [
            # Root response
            {"Chassis": {"@odata.id": "/redfish/v1/Chassis"}},
            # Chassis collection
            {"Members": [{"@odata.id": "/redfish/v1/Chassis/1"}]},
            # Chassis member data
            {"PowerSubsystem": {"@odata.id": "/redfish/v1/Chassis/1/PowerSubsystem"}},
            # PowerSubsystem fetch fails
            None,
        ]

        session = MagicMock()
        with patch(
            "exporter.api.fetch_with_retry",
            new_callable=AsyncMock,
            side_effect=responses,
        ):
            await get_power_data(session, host, False)

    @pytest.mark.asyncio
    async def test_get_power_data_psu_collection_none(self):
        """Test handling when PSU collection fetch returns None."""
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
                chassis=["1"],
            )
        )
        host.session.vendor = "Dell"

        responses = [
            # Root response
            {"Chassis": {"@odata.id": "/redfish/v1/Chassis"}},
            # Chassis collection
            {"Members": [{"@odata.id": "/redfish/v1/Chassis/1"}]},
            # Chassis member data
            {"PowerSubsystem": {"@odata.id": "/redfish/v1/Chassis/1/PowerSubsystem"}},
            # PowerSubsystem data
            {"PowerSupplies": {"@odata.id": "/redfish/v1/Chassis/1/PowerSubsystem/PowerSupplies"}},
            # PowerSupplies collection fetch fails
            None,
        ]

        session = MagicMock()
        with patch(
            "exporter.api.fetch_with_retry",
            new_callable=AsyncMock,
            side_effect=responses,
        ):
            await get_power_data(session, host, False)


class TestGetSystemInfo:
    """Tests for get_system_info function."""

    @pytest.mark.asyncio
    async def test_get_system_info_no_root(self):
        """Test get_system_info returns early when root fetch fails."""
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
        """Test get_system_info returns early when no systems."""
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

    @pytest.mark.asyncio
    async def test_get_system_info_full_flow(self):
        """Test full system info collection flow."""
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
            )
        )
        host.session.vendor = "Dell"

        responses = [
            # Root response
            {"RedfishVersion": "1.8.0"},
            # Systems collection
            {"Members": [{"@odata.id": "/redfish/v1/Systems/1"}]},
            # System data
            {
                "Manufacturer": "Dell Inc.",
                "Model": "PowerEdge R750",
                "SerialNumber": "ABC123",
            },
        ]

        session = MagicMock()
        with patch(
            "exporter.api.fetch_with_retry",
            new_callable=AsyncMock,
            side_effect=responses,
        ):
            with patch("exporter.api.SYSTEM_INFO") as mock_system_info:
                mock_gauge = MagicMock()
                mock_system_info.labels.return_value = mock_gauge
                await get_system_info(session, host)
                mock_system_info.labels.assert_called_once_with(
                    host="http://localhost:5000", group="none"
                )
                mock_gauge.info.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_system_info_with_missing_fields(self):
        """Test system info collection with missing optional fields."""
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
            )
        )
        host.session.vendor = "Dell"

        responses = [
            # Root response
            {"RedfishVersion": "1.8.0"},
            # Systems collection
            {"Members": [{"@odata.id": "/redfish/v1/Systems/1"}]},
            # System data with missing Manufacturer/Model/SerialNumber
            # but contains other data so it's truthy
            {"Name": "System 1"},
        ]

        session = MagicMock()
        with patch(
            "exporter.api.fetch_with_retry",
            new_callable=AsyncMock,
            side_effect=responses,
        ):
            with patch("exporter.api.SYSTEM_INFO") as mock_system_info:
                mock_gauge = MagicMock()
                mock_system_info.labels.return_value = mock_gauge
                await get_system_info(session, host)
                # Should use NO_DATA_ENTRY for missing fields
                call_args = mock_gauge.info.call_args[0][0]
                assert call_args["manufacturer"] == NO_DATA_ENTRY
                assert call_args["model"] == NO_DATA_ENTRY
                assert call_args["serial_number"] == NO_DATA_ENTRY
