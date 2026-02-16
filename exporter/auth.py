# exporter/auth.py
import logging
import asyncio
from typing import Optional
import aiohttp
from exporter.redfish import RedfishHost
from exporter.utils import get_aiohttp_request_kwargs
from exporter.metrics import (
    UP_GAUGE,
)

async def probe_vendor(
    session: aiohttp.ClientSession, host: RedfishHost
) -> Optional[str]:
    """Probe the vendor of a Redfish host."""
    if host.health.check_and_log_skip(host.fqdn):
        UP_GAUGE.labels(host=host.fqdn, group=host.group).set(0)
        return None

    kwargs = get_aiohttp_request_kwargs(verify_ssl=host.cfg.verify_ssl)
    max_retries = host.cfg.max_retries
    backoff = host.cfg.backoff

    for attempt in range(1, max_retries + 1):
        try:
            async with session.get(f"{host.fqdn}/redfish/v1/", **kwargs) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    vendor = data.get("Vendor", "")
                    if vendor:
                        host.session.vendor = vendor
                    host.health.mark_success()
                    return vendor
                else:
                    logging.warning(
                        "Request to %s failed with status %d (attempt %d).",
                        host.fqdn, resp.status, attempt
                    )
                    resp.raise_for_status()
        except aiohttp.ClientConnectorError as e:
            logging.warning("Connection error for %s (attempt %d): %s", host.fqdn, attempt, e)
        except asyncio.TimeoutError as e:
            logging.warning("Timeout error for %s (attempt %d): %s", host.fqdn, attempt, e)
        except aiohttp.ClientResponseError as e:
            logging.warning("HTTP error for %s (attempt %d): %s", host.fqdn, attempt, e)
        except asyncio.CancelledError:
            logging.warning("Request to %s was cancelled (attempt %d).", host.fqdn, attempt)
            raise
        except Exception as e:
            logging.warning("Unexpected error for %s (attempt %d): %s", host.fqdn, attempt, e)

        if attempt < max_retries:
            await asyncio.sleep(backoff ** attempt)

    host.health.mark_failure()
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
        verify_ssl=host.cfg.verify_ssl,
        timeout_seconds=10,
        headers={"X-Auth-Token": host.session.token},
    )
    try:
        async with session.delete(
            host.session.logout_url,
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
