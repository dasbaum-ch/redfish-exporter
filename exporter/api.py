# api.py
import time
import logging
from typing import Optional, Dict, Any
import asyncio
import aiohttp
from exporter.config import PowerMetrics, NO_DATA_ENTRY
from exporter.redfish import RedfishHost
from exporter.metrics import (
    REQUEST_LATENCY,
    UP_GAUGE,
    SYSTEM_INFO,
)
from exporter.auth import probe_vendor, login_hpe
from exporter.utils import get_aiohttp_request_kwargs, safe_get, safe_update_metrics


async def fetch_with_retry(
    session: aiohttp.ClientSession, host: RedfishHost, url: str
) -> Optional[dict]:
    """Fetch JSON from Redfish with retry/backoff."""
    if host.health.check_and_log_skip(host.fqdn):
        UP_GAUGE.labels(host=host.fqdn, group=host.group).set(0)
        return None

    if not host.session.vendor:
        host.session.vendor = await probe_vendor(session, host)

    auth = None
    headers: Dict[str, str] = {}
    if host.session.is_hpe:
        if not host.session.token and not await login_hpe(session, host):
            return None
    else:
        auth = aiohttp.BasicAuth(host.cfg.username, host.cfg.password)

    token = host.session.token
    if token:
        headers["X-Auth-Token"] = token

    kwargs = get_aiohttp_request_kwargs(
        verify_ssl=host.cfg.verify_ssl,
        headers=headers,
        auth=auth,
    )

    for attempt in range(1, host.cfg.max_retries + 1):
        try:
            async with session.get(url, **kwargs) as resp:
                if resp.status >= 400:
                    if resp.status in (401, 403):
                        if host.session.is_hpe:
                            host.session.token = None
                    return None
                return await resp.json()

        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
            logging.warning(
                "Request error on %s (attempt %d): %s", host.fqdn, attempt, e
            )

        if attempt < host.cfg.max_retries:
            await asyncio.sleep(host.cfg.backoff * attempt)
        else:
            host.health.mark_failure()
    return None


def normalize_url(url: str) -> str:
    """Normalize a URL by removing trailing slashes."""
    return url[:-1] if url.endswith("/") else url


async def process_power_supply(
    session: aiohttp.ClientSession,
    host: RedfishHost,
    psu_data: Dict[str, Any],
    resource_type: str,
) -> Optional[PowerMetrics]:
    """Process power supply data."""
    serial = psu_data.get("SerialNumber")
    metrics = PowerMetrics(serial=serial)

    if resource_type == "PowerSubsystem":
        metrics_ref = psu_data.get("Metrics")
        if metrics_ref and "@odata.id" in metrics_ref:
            metrics_url = metrics_ref["@odata.id"]
            data = await fetch_with_retry(session, host, f"{host.fqdn}{metrics_url}")
            if data:
                metrics.voltage = safe_get(data, "InputVoltage", "Reading")
                metrics.watts = safe_get(data, "InputPowerWatts", "Reading")
                metrics.amps = safe_get(data, "InputCurrentAmps", "Reading")
    else:
        metrics.voltage = psu_data.get("LineInputVoltage")
        metrics.watts = psu_data.get("PowerInputWatts") or psu_data.get(
            "LastPowerOutputWatts"
        )
        metrics.amps = psu_data.get("InputCurrentAmps")
        if metrics.amps is None and metrics.voltage and metrics.watts:
            metrics.amps = round(metrics.watts / metrics.voltage, 2)
    return metrics


async def get_power_data(
    session: aiohttp.ClientSession, host: RedfishHost, deprecated: bool
) -> None:
    """
    Fetch and process power data from a Redfish host.
    """
    start = time.monotonic()
    root = await fetch_with_retry(session, host, f"{host.fqdn}/redfish/v1/")
    if root is None:
        return

    UP_GAUGE.labels(host=host.fqdn, group=host.group).set(1)

    chassis_id_path = root.get("Chassis", {}).get("@odata.id")
    if not chassis_id_path:
        return

    chassis_url = f"{host.fqdn}{chassis_id_path}"
    chassis_collection = await fetch_with_retry(session, host, chassis_url)

    if chassis_collection is None:
        return

    for member in chassis_collection.get("Members", []):
        m_url = normalize_url(member.get("@odata.id", ""))
        if not m_url:
            continue

        m_id = m_url.split("/")[-1]

        if host.cfg.chassis and m_id not in host.cfg.chassis:
            continue

        m_data = await fetch_with_retry(session, host, f"{host.fqdn}{m_url}")
        if m_data is None:
            continue

        p_url = m_data.get("PowerSubsystem", {}).get("@odata.id")
        p_type = "PowerSubsystem"
        if not p_url:
            p_url = m_data.get("Power", {}).get("@odata.id")
            p_type = "Power"
            if p_url and deprecated:
                logging.warning("DEPRECATED: %s uses old Power API", host.fqdn)

        if not p_url:
            continue

        p_data = await fetch_with_retry(session, host, f"{host.fqdn}{p_url}")
        if p_data is None:
            continue

        if p_type == "PowerSubsystem":
            psus_url = safe_get(p_data, "PowerSupplies", "@odata.id")
            if not psus_url:
                continue
            psus_coll = await fetch_with_retry(session, host, f"{host.fqdn}{psus_url}")
            if psus_coll is None:
                continue

            for psu_mem in psus_coll.get("Members", []):
                psu_d = await fetch_with_retry(
                    session, host, f"{host.fqdn}{psu_mem.get('@odata.id')}"
                )
                if psu_d is not None:
                    metrics = await process_power_supply(session, host, psu_d, p_type)
                    safe_update_metrics(host, metrics)
        else:
            for psu in p_data.get("PowerSupplies", []):
                metrics = await process_power_supply(session, host, psu, p_type)
                safe_update_metrics(host, metrics)

    REQUEST_LATENCY.labels(host=host.fqdn).observe(time.monotonic() - start)


async def get_system_info(session: aiohttp.ClientSession, host: RedfishHost) -> None:
    """
    Fetch and update system information metrics for a Redfish host.
    """
    root = await fetch_with_retry(session, host, f"{host.fqdn}/redfish/v1/")
    if root is None:
        return
    rf_version = str(root.get("RedfishVersion", "unknown"))

    systems = await fetch_with_retry(session, host, f"{host.fqdn}/redfish/v1/Systems")
    if not systems:
        return

    for member in systems.get("Members", []):
        s_data = await fetch_with_retry(
            session, host, f"{host.fqdn}{member.get('@odata.id')}"
        )
        if s_data:
            SYSTEM_INFO.labels(host=host.fqdn, group=host.group).info(
                {
                    "manufacturer": s_data.get("Manufacturer") or NO_DATA_ENTRY,
                    "model": s_data.get("Model") or NO_DATA_ENTRY,
                    "serial_number": s_data.get("SerialNumber") or NO_DATA_ENTRY,
                    "redfish_version": rf_version,
                }
            )
