# tests/test_api.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from exporter.api import fetch_with_retry
from exporter.redfish import RedfishHost
from exporter.config import HostConfig


@pytest.mark.asyncio
async def test_fetch_with_retry_success():
    session = AsyncMock()
    host = RedfishHost(
        HostConfig(fqdn="http://localhost:5000", username="user", password="pass")
    )
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json.return_value = {"key": "value"}
    session.get.return_value.__aenter__.return_value = mock_response

    result = await fetch_with_retry(session, host, "http://localhost:5000redfish/v1")
    assert result == {"key": "value"}
