# tests/test_api.py
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from exporter.api import (
    fetch_with_retry,
    normalize_url,
    process_power_supply,
    get_power_data,
    get_system_info,
)
from exporter.redfish import RedfishHost
from exporter.config import HostConfig


def make_host(vendor="Dell", **kwargs):
    defaults = {
        "fqdn": "http://localhost:5000",
        "username": "user",
        "password": "pass",
    }
    host = RedfishHost(HostConfig(**{**defaults, **kwargs}))
    host.session.vendor = vendor
    return host


def create_routed_mock_session(url_map, default_status=200):
    session = MagicMock()

    def mock_get(url, **kwargs):
        url_str = str(url)

        # Sort path by lenght desc
        sorted_paths = sorted(url_map.keys(), key=len, reverse=True)

        found_data = None
        for path in sorted_paths:
            if path in url_str:
                found_data = url_map[path]
                break

        mock_cm = MagicMock()

        if isinstance(found_data, Exception):
            mock_cm.__aenter__ = AsyncMock(side_effect=found_data)
        else:
            mock_response = MagicMock()
            if found_data is not None:
                if isinstance(found_data, tuple):
                    status, json_data = found_data
                else:
                    status, json_data = default_status, found_data
            else:
                status, json_data = 404, {}

            mock_response.status = status
            mock_response.json = AsyncMock(return_value=json_data)
            mock_response.headers = {"X-Auth-Token": "test-token"}

            mock_cm.__aenter__ = AsyncMock(return_value=mock_response)

        mock_cm.__aexit__ = AsyncMock(return_value=None)
        return mock_cm

    session.get = MagicMock(side_effect=mock_get)
    session.post = MagicMock(side_effect=mock_get)
    return session


def create_mock_session(response_data, status=200):
    if response_data is None:
        return create_routed_mock_session({"": (status, {})})
    return create_routed_mock_session({"": (status, response_data)})


class TestNormalizeUrl:
    def test_url_with_trailing_slash(self):
        assert (
            normalize_url("http://127.0.0.1:5000/redfish/v1/Chassis/")
            == "http://127.0.0.1:5000/redfish/v1/Chassis"
        )

    def test_url_without_trailing_slash(self):
        assert (
            normalize_url("http://127.0.0.1:5000/redfish/v1")
            == "http://127.0.0.1:5000/redfish/v1"
        )

    def test_root_url_with_trailing_slash(self):
        assert normalize_url("http://127.0.0.1:5000/") == "http://127.0.0.1:5000"

    def test_empty_string(self):
        assert normalize_url("") == ""


class TestFetchWithRetry:
    @pytest.mark.asyncio
    async def test_fetch_success_non_hpe(self):
        session = create_mock_session({"key": "value"})
        host = make_host()
        result = await fetch_with_retry(
            session, host, "http://localhost:5000/redfish/v1/"
        )
        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_fetch_http_error_retry(self):
        # /redfish/v1/ must be OK, but the target URL should fail.
        url_map = {
            "/redfish/v1/": {"Vendor": "Dell"},
            "http://localhost:5000/redfish/v1/fail": (500, {}),
        }
        session = create_routed_mock_session(url_map)
        host = make_host(max_retries=2, backoff=0)

        result = await fetch_with_retry(
            session, host, "http://localhost:5000/redfish/v1/fail"
        )
        assert result is None


class TestProcessPowerSupply:
    @pytest.mark.asyncio
    async def test_process_power_supply_legacy_success(self):
        session = create_mock_session({})
        psu_data = {
            "SerialNumber": "PSU123",
            "LineInputVoltage": 230,
            "PowerInputWatts": 500,
            "InputCurrentAmps": 2.17,
        }
        result = await process_power_supply(session, make_host(), psu_data, "Power")
        assert result.serial == "PSU123"
        assert result.voltage == 230
        assert result.watts == 500
        assert result.amps == 2.17

    @pytest.mark.asyncio
    async def test_process_power_supply_modern_success(self):
        url_map = {
            "/Metrics": {
                "InputVoltage": {"Reading": 230},
                "InputPowerWatts": {"Reading": 600},
                "InputCurrentAmps": {"Reading": 2.6},
            }
        }
        session = create_routed_mock_session(url_map)
        psu_data = {
            "SerialNumber": "PSU999",
            "Metrics": {"@odata.id": "/redfish/v1/Chassis/1/PSU/1/Metrics"},
        }
        result = await process_power_supply(
            session, make_host(), psu_data, "PowerSubsystem"
        )
        assert result.serial == "PSU999"
        assert result.voltage == 230
        assert result.watts == 600
        assert result.amps == 2.6

    @pytest.mark.asyncio
    async def test_process_power_supply_empty(self):
        session = create_mock_session({})
        result = await process_power_supply(session, make_host(), {}, "Power")
        assert result.serial is None
        assert result.voltage is None
        assert result.watts is None
        assert result.amps is None

    @pytest.mark.asyncio
    async def test_process_power_supply_subsystem_no_metrics(self):
        session = create_mock_session({})
        host = make_host(vendor="", chassis="Chassis-1")
        psu_data = {"SerialNumber": "PSU456", "Metrics": None}
        result = await process_power_supply(session, host, psu_data, "PowerSubsystem")
        assert result.serial == "PSU456"
        assert result.voltage is None
        assert result.watts is None
        assert result.amps is None


class TestGetPowerData:
    @pytest.mark.asyncio
    async def test_get_power_data_no_root(self):
        session = create_mock_session(None, status=404)
        await get_power_data(session, make_host(), False)

    @pytest.mark.asyncio
    async def test_get_power_data_no_chassis(self):
        session = create_mock_session({"Chassis": {"@odata.id": None}})
        await get_power_data(session, make_host(), False)

    @pytest.mark.asyncio
    async def test_get_power_data_chassis_no_members(self):
        url_map = {
            "/redfish/v1/": {"Chassis": {"@odata.id": "/redfish/v1/Chassis"}},
            "/redfish/v1/Chassis": {"Members": []},
        }
        session = create_routed_mock_session(url_map)
        await get_power_data(session, make_host(), False)

    @pytest.mark.asyncio
    async def test_get_power_data_full_flow_modern(self):
        # Test PowerSubsystem
        url_map = {
            "/redfish/v1/": {"Chassis": {"@odata.id": "/redfish/v1/Chassis"}},
            "/redfish/v1/Chassis": {
                "Members": [{"@odata.id": "/redfish/v1/Chassis/1"}]
            },
            "/redfish/v1/Chassis/1": {
                "PowerSubsystem": {"@odata.id": "/redfish/v1/Chassis/1/PowerSubsystem"}
            },
            "/redfish/v1/Chassis/1/PowerSubsystem": {
                "PowerSupplies": {
                    "@odata.id": "/redfish/v1/Chassis/1/PowerSubsystem/PSUs"
                }
            },
            "/redfish/v1/Chassis/1/PowerSubsystem/PSUs": {
                "Members": [{"@odata.id": "/redfish/v1/PSU/1"}]
            },
            "/redfish/v1/PSU/1": {
                "SerialNumber": "FULL-FLOW-SN",
                "Metrics": {"@odata.id": "/redfish/v1/PSU/1/Metrics"},
            },
            "/redfish/v1/PSU/1/Metrics": {
                "InputVoltage": {"Reading": 230},
                "InputPowerWatts": {"Reading": 450},
            },
        }
        session = create_routed_mock_session(url_map)
        await get_power_data(session, make_host(), False)


class TestGetSystemInfo:
    @pytest.mark.asyncio
    async def test_get_system_info_success(self):
        url_map = {
            "/redfish/v1/": {"RedfishVersion": "1.0.0"},
            "/redfish/v1/Systems": {
                "Members": [{"@odata.id": "/redfish/v1/Systems/1"}]
            },
            "/redfish/v1/Systems/1": {
                "Manufacturer": "Manufacturer Name",
                "Model": "Model Name",
                "SerialNumber": "2M220100SL",
            },
        }
        session = create_routed_mock_session(url_map)
        await get_system_info(session, make_host())

    @pytest.mark.asyncio
    async def test_get_system_info_no_systems(self):
        url_map = {
            "/redfish/v1/": {"RedfishVersion": "1.0.0"},
            "/redfish/v1/Systems": {"Members": []},
        }
        session = create_routed_mock_session(url_map)
        await get_system_info(session, make_host())


class TestResilience:
    @pytest.mark.asyncio
    async def test_hpe_relogin_after_401(self):
        """
        Simulate expired token.
        After HTTP 401, token has to be deleted at host-object.
        """
        host = make_host(vendor="HPE")
        host.session.token = "expired-token"

        url_map = {"/redfish/v1/": (401, {"error": "session expired"})}
        session = create_routed_mock_session(url_map)

        result = await fetch_with_retry(session, host, f"{host.fqdn}/redfish/v1/")

        assert result is None
        assert host.session.token is None

    @pytest.mark.asyncio
    async def test_host_health_cooldown_after_timeout(self):
        """
        Test HostHealth system: After too many attempts, hosts goes to
        cool-down state.
        """
        host = make_host(max_retries=2, cool_down=60)

        url_map = {"/redfish/v1/": asyncio.TimeoutError("Connection timed out")}
        session = create_routed_mock_session(url_map)

        await fetch_with_retry(session, host, f"{host.fqdn}/redfish/v1/")
        assert host.health.failures == 1
        assert host.health.should_skip is False

        await fetch_with_retry(session, host, f"{host.fqdn}/redfish/v1/")

        assert host.health.should_skip is True

        result = await fetch_with_retry(session, host, f"{host.fqdn}/redfish/v1/")
        assert result is None
