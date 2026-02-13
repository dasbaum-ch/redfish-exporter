# tests/test_api.py
import pytest
from unittest.mock import AsyncMock, patch  # patch hinzugefügt!
from exporter.api import fetch_with_retry
from exporter.redfish import RedfishHost
from exporter.config import HostConfig


@pytest.mark.asyncio
async def test_fetch_with_retry_success(mock_server):
    session = AsyncMock()

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"key": "value"})

    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_response
    mock_cm.__aexit__.return_value = None
    session.get.return_value = mock_cm

    host = RedfishHost(
        HostConfig(fqdn="http://localhost:5000", username="user", password="pass")
    )

    with patch(
        "exporter.api.probe_vendor", new_callable=AsyncMock
    ) as mock_probe_vendor:
        with patch("exporter.api.login_hpe", new_callable=AsyncMock) as mock_login_hpe:
            mock_probe_vendor.return_value = "Generic"
            mock_login_hpe.return_value = True

            result = await fetch_with_retry(
                session, host, "http://localhost:5000/redfish/v1"
            )

            assert result == {"key": "value"}
            session.get.assert_called_once()
            mock_probe_vendor.assert_called_once()
            mock_login_hpe.assert_called_once()
