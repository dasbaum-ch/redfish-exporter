# exporter/auth.py
import logging
from typing import Optional
import aiohttp
from exporter.redfish import RedfishHost


async def probe_vendor(
    session: aiohttp.ClientSession, host: RedfishHost
) -> Optional[str]:
    """
    Probe the vendor of a Redfish host by querying the root Redfish API endpoint.

    Args:
        session: Active aiohttp client session for HTTP requests.
        host: RedfishHost instance containing connection details.

    Returns:
        Optional[str]: The vendor name as a string if successful, otherwise None.
    """
    ssl_context = None if host.cfg.verify_ssl else False
    try:
        async with session.get(
            f"{host.fqdn}/redfish/v1/", ssl=ssl_context, timeout=10
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("Vendor", "")
    except Exception as e:
        logging.warning("Vendor probe failed for %s: %s", host.fqdn, e)
    return None


async def login_hpe(session: aiohttp.ClientSession, host: RedfishHost) -> bool:
    """
    Authenticate with an HPE Redfish API and store the session token in the host object.

    Args:
        session: Active aiohttp client session.
        host: RedfishHost instance to authenticate with.

    Returns:
        bool: True if login was successful, False otherwise.
    """
    ssl_context = None if host.cfg.verify_ssl else False
    login_url = f"{host.fqdn}/redfish/v1/SessionService/Sessions"
    payload = {"UserName": host.cfg.username, "Password": host.cfg.password}
    try:
        async with session.post(
            login_url, json=payload, ssl=ssl_context, timeout=10
        ) as resp:
            if resp.status == 201:
                host.session.token = resp.headers.get("X-Auth-Token")
                host.session.logout_url = resp.headers.get("Location")
                return True
    except Exception as e:
        logging.warning("Login failed for %s: %s", host.fqdn, e)
    return False


async def logout_host(session: aiohttp.ClientSession, host: RedfishHost) -> None:
    """
    Log out from a Redfish host session by deleting the session token.

    Args:
        session: Active aiohttp client session.
        host: RedfishHost instance with an active session.
    """
    if not host.session.token or not host.session.logout_url:
        return
    ssl_context = None if host.cfg.verify_ssl else False
    try:
        async with session.delete(
            host.session.logout_url,
            headers={"X-Auth-Token": host.session.token},
            ssl=ssl_context,
            timeout=5,
        ) as resp:
            if resp.status in (200, 204):
                logging.info("Logged out from %s", host.fqdn)
            else:
                logging.warning(
                    "Logout from %s failed with status %s", host.fqdn, resp.status
                )
    except Exception as e:
        logging.warning("Logout error for %s: %s", host.fqdn, e)
    finally:
        host.session.token = None
