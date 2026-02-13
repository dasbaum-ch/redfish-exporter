# exporter/auth.py
import logging
from typing import Optional
import aiohttp
from exporter.redfish import RedfishHost
from exporter.utils import get_aiohttp_request_kwargs


async def probe_vendor(
    session: aiohttp.ClientSession, host: RedfishHost
) -> Optional[str]:
    """Probe the vendor of a Redfish host."""
    kwargs = get_aiohttp_request_kwargs(verify_ssl=host.cfg.verify_ssl)
    try:
        async with session.get(f"{host.fqdn}/redfish/v1/", **kwargs) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("Vendor", "")
    except Exception as e:
        logging.warning("Vendor probe failed for %s: %s", host.fqdn, e)
    return None


async def login_hpe(session: aiohttp.ClientSession, host: RedfishHost) -> bool:
    """Login to HPE Redfish API."""
    kwargs = get_aiohttp_request_kwargs(verify_ssl=host.cfg.verify_ssl)
    login_url = f"{host.fqdn}/redfish/v1/SessionService/Sessions"
    payload = {"UserName": host.cfg.username, "Password": host.cfg.password}
    try:
        async with session.post(login_url, json=payload, **kwargs) as resp:
            if resp.status == 201:
                host.session.token = resp.headers.get("X-Auth-Token")
                host.session.logout_url = resp.headers.get("Location")
                return True
    except Exception as e:
        logging.warning("Login failed for %s: %s", host.fqdn, e)
    return False


async def logout_host(session: aiohttp.ClientSession, host: RedfishHost) -> None:
    """Log out from a Redfish host session."""
    if not host.session.token or not host.session.logout_url:
        return
    kwargs = get_aiohttp_request_kwargs(
        verify_ssl=host.cfg.verify_ssl, timeout_seconds=10
    )
    try:
        async with session.delete(
            host.session.logout_url,
            headers={"X-Auth-Token": host.session.token},
            **kwargs,
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
