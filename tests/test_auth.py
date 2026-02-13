# tests/test_auth.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from exporter.auth import probe_vendor, login_hpe, logout_host
from exporter.redfish import RedfishHost
from exporter.config import HostConfig


def create_mock_response(data, status=200, headers=None):
    """Create a mock aiohttp response."""
    mock_response = MagicMock()
    mock_response.status = status
    mock_response.json = AsyncMock(return_value=data)
    mock_response.headers = headers or {}
    return mock_response


def create_mock_session(response_data, status=200, headers=None):
    """Create a mock aiohttp session with proper async context manager."""
    session = MagicMock()
    mock_response = create_mock_response(response_data, status, headers)

    # Create async context manager using MagicMock
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    session.get.return_value = mock_cm
    session.post.return_value = mock_cm
    session.delete.return_value = mock_cm
    return session


class TestProbeVendor:
    """Tests for probe_vendor function."""

    @pytest.mark.asyncio
    async def test_probe_vendor_success_hpe(self):
        """Test successful vendor probe returns HPE."""
        session = create_mock_session({"Vendor": "HPE"})
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
            )
        )

        result = await probe_vendor(session, host)
        assert result == "HPE"

    @pytest.mark.asyncio
    async def test_probe_vendor_success_dell(self):
        """Test successful vendor probe returns Dell."""
        session = create_mock_session({"Vendor": "Dell"})
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
            )
        )

        result = await probe_vendor(session, host)
        assert result == "Dell"

    @pytest.mark.asyncio
    async def test_probe_vendor_no_vendor_field(self):
        """Test vendor probe when Vendor field is missing."""
        session = create_mock_session({"RedfishVersion": "1.0.0"})
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
            )
        )

        result = await probe_vendor(session, host)
        assert result == ""

    @pytest.mark.asyncio
    async def test_probe_vendor_http_error(self):
        """Test vendor probe returns None on HTTP error."""
        session = create_mock_session({}, status=500)
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
            )
        )

        result = await probe_vendor(session, host)
        assert result is None

    @pytest.mark.asyncio
    async def test_probe_vendor_exception(self):
        """Test vendor probe returns None on exception."""
        session = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=Exception("Connection error"))
        session.get.return_value = mock_cm
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
            )
        )

        result = await probe_vendor(session, host)
        assert result is None


class TestLoginHpe:
    """Tests for login_hpe function."""

    @pytest.mark.asyncio
    async def test_login_hpe_success(self):
        """Test successful HPE login."""
        session = create_mock_session(
            {},
            status=201,
            headers={"X-Auth-Token": "abc123", "Location": "/logout/path"},
        )
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="admin",
                password="secret",
            )
        )

        result = await login_hpe(session, host)
        assert result is True
        assert host.session.token == "abc123"
        assert host.session.logout_url == "/logout/path"

    @pytest.mark.asyncio
    async def test_login_hpe_failure_wrong_status(self):
        """Test HPE login failure with wrong status code."""
        session = create_mock_session({}, status=401)
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="admin",
                password="wrong",
            )
        )

        result = await login_hpe(session, host)
        assert result is False
        assert host.session.token is None

    @pytest.mark.asyncio
    async def test_login_hpe_exception(self):
        """Test HPE login returns False on exception."""
        session = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=Exception("Connection error"))
        session.post.return_value = mock_cm

        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="admin",
                password="secret",
            )
        )

        result = await login_hpe(session, host)
        assert result is False


class TestLogoutHost:
    """Tests for logout_host function."""

    @pytest.mark.asyncio
    async def test_logout_host_success_200(self):
        """Test successful logout with 200 status."""
        session = create_mock_session({}, status=200)
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="admin",
                password="secret",
            )
        )
        host.session.token = "test-token"
        host.session.logout_url = "http://localhost:5000/logout"

        await logout_host(session, host)
        assert host.session.token is None

    @pytest.mark.asyncio
    async def test_logout_host_success_204(self):
        """Test successful logout with 204 status."""
        session = create_mock_session({}, status=204)
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="admin",
                password="secret",
            )
        )
        host.session.token = "test-token"
        host.session.logout_url = "http://localhost:5000/logout"

        await logout_host(session, host)
        assert host.session.token is None

    @pytest.mark.asyncio
    async def test_logout_host_no_token(self):
        """Test logout does nothing without token."""
        session = create_mock_session({}, status=200)
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="admin",
                password="secret",
            )
        )
        host.session.token = None
        host.session.logout_url = "http://localhost:5000/logout"

        await logout_host(session, host)
        # Session delete should not be called
        session.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_logout_host_no_logout_url(self):
        """Test logout does nothing without logout URL."""
        session = create_mock_session({}, status=200)
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="admin",
                password="secret",
            )
        )
        host.session.token = "test-token"
        host.session.logout_url = None

        await logout_host(session, host)
        # Session delete should not be called
        session.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_logout_host_failure_clears_token(self):
        """Test that token is cleared even on logout failure."""
        session = create_mock_session({}, status=500)
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="admin",
                password="secret",
            )
        )
        host.session.token = "test-token"
        host.session.logout_url = "http://localhost:5000/logout"

        await logout_host(session, host)
        assert host.session.token is None

    @pytest.mark.asyncio
    async def test_logout_host_exception_clears_token(self):
        """Test that token is cleared even on exception."""
        session = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=Exception("Network error"))
        session.delete.return_value = mock_cm

        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="admin",
                password="secret",
            )
        )
        host.session.token = "test-token"
        host.session.logout_url = "http://localhost:5000/logout"

        await logout_host(session, host)
        assert host.session.token is None
