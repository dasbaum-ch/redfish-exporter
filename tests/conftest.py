# tests/conftest.py
import pytest
import subprocess
import os
import time
import requests


@pytest.fixture(scope="session")
def mock_server():
    compose_file = os.path.join(
        os.path.dirname(__file__), "mock_server", "compose.yaml"
    )
    # run docker compose
    subprocess.run(["docker", "compose", "-f", compose_file, "up", "-d"], check=True)

    # wait for the mock server
    max_attempts = 3
    for _ in range(max_attempts):
        try:
            response = requests.get("http://localhost:5000/redfish/v1", timeout=2)
            if response.status_code == 200:
                break
        except requests.RequestException:
            time.sleep(1)
    else:
        raise RuntimeError("Mock server not ready!")

    yield

    # stop and cleanup
    subprocess.run(["docker", "compose", "-f", compose_file, "down"], check=True)
