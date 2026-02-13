# api.py
import time
import asyncio
import aiohttp
import logging
from typing import Optional, Dict, Any
from exporter.config import PowerMetrics, NO_DATA_ENTRY
from exporter.redfish import RedfishHost
from exporter.metrics import update_prometheus_metrics, REQUEST_LATENCY, UP_GAUGE, SYSTEM_INFO
from exporter.auth import probe_vendor, login_hpe

async def fetch_with_retry(
    session: aiohttp.ClientSession,
    host: RedfishHost,
    url: str
) -> Optional[Dict[str, Any]]:
    """Fetch JSON data from a Redfish API endpoint with retry and backoff logic.

    Args:
        session: Active aiohttp client session.
        host: RedfishHost instance for connection details.
        url: Full URL to fetch data from.

    Returns:
        Optional[Dict[str, Any]]: Parsed JSON response as a dictionary, or None if all retries fail.
    """
    if host.health.check_and_log_skip(host.fqdn):
        UP_GAUGE.labels(host=host.fqdn, group=host.group).set(0)
        return None

    if not host.session.vendor:
        host.session.vendor = await probe_vendor(session, host)

    ssl_context = None if host.cfg.verify_ssl else False

    for attempt in range(1, host.cfg.max_retries + 1):
        try:
            headers = {}
            auth = None

            if host.session.is_hpe:
                if not host.session.token and not await login_hpe(session, host):
                    continue
                headers["X-Auth-Token"] = host.session.token
            else:
                auth = aiohttp.BasicAuth(host.cfg.username, host.cfg.password)

            async with session.get(
                url, headers=headers, auth=auth, ssl=ssl_context, timeout=10
            ) as resp:
                if resp.status == 200:
                    host.health.mark_success()
                    return await resp.json()
                if resp.status in (401, 403) and host.session.is_hpe:
                    host.session.token = None
                    continue
                logging.warning(
                    "HTTP %s from %s (attempt %d)", resp.status, host.fqdn, attempt
                )

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
    """Normalize a URL by removing trailing slashes.

    Args:
        url: URL to normalize.

    Returns:
        str: Normalized URL without trailing slash.
    """
    return url[:-1] if url.endswith("/") else url

async def process_power_supply(
    session: aiohttp.ClientSession,
    host: RedfishHost,
    psu_data: Dict[str, Any],
    resource_type: str
) -> Optional[PowerMetrics]:
    """
    Process power supply data and extract metrics like voltage, watts, and amps.

    Args:
        session: Active aiohttp client session.
        host: RedfishHost instance.
        psu_data: Raw power supply data as a dictionary.
        resource_type: Type of power resource (e.g., "PowerSubsystem").

    Returns:
        PowerMetrics object with extracted values, or None if processing fails.
    """
    serial = psu_data.get("SerialNumber")
    metrics = PowerMetrics(serial=serial)

    if resource_type == "PowerSubsystem":
        metrics_url = psu_data.get("Metrics", {}).get("@odata.id")
        if metrics_url:
            data = await fetch_with_retry(session, host, f"{host.fqdn}{metrics_url}")
            if data:
                metrics.voltage = data.get("InputVoltage", {}).get("Reading")
                metrics.watts = data.get("InputPowerWatts", {}).get("Reading")
                metrics.amps = data.get("InputCurrentAmps", {}).get("Reading")
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
    session: aiohttp.ClientSession,
    host: RedfishHost,
    show_deprecated_warnings: bool
) -> None:
    """
    Fetch and process power data from a Redfish host.

    Args:
        session: Active aiohttp client session.
        host: RedfishHost instance to query.
        show_deprecated_warnings: If True, log warnings for deprecated APIs.
    """
    start = time.monotonic()
    root = await fetch_with_retry(session, host, f"{host.fqdn}/redfish/v1/")
    if not root:
        return

    UP_GAUGE.labels(host=host.fqdn, group=host.group).set(1)
    chassis_url = f"{host.fqdn}{root.get('Chassis', {}).get('@odata.id')}"
    chassis_collection = await fetch_with_retry(session, host, chassis_url)

    if not chassis_collection:
        return

    for member in chassis_collection.get("Members", []):
        m_url = normalize_url(member.get("@odata.id", ""))
        m_id = m_url.split("/")[-1]

        if host.cfg.chassis and m_id not in host.cfg.chassis:
            continue

        m_data = await fetch_with_retry(session, host, f"{host.fqdn}{m_url}")
        if not m_data:
            continue

        p_url = m_data.get("PowerSubsystem", {}).get("@odata.id")
        p_type = "PowerSubsystem"
        if not p_url:
            p_url = m_data.get("Power", {}).get("@odata.id")
            p_type = "Power"
            if p_url and show_deprecated_warnings:
                logging.warning("DEPRECATED: %s uses old Power API", host.fqdn)

        if not p_url:
            continue
        p_data = await fetch_with_retry(session, host, f"{host.fqdn}{p_url}")
        if not p_data:
            continue

        if p_type == "PowerSubsystem":
            psus_url = p_data.get("PowerSupplies", {}).get("@odata.id")
            if psus_url:
                psus_coll = await fetch_with_retry(
                    session, host, f"{host.fqdn}{psus_url}"
                )
                for psu_mem in psus_coll.get("Members", []):
                    psu_d = await fetch_with_retry(
                        session, host, f"{host.fqdn}{psu_mem.get('@odata.id')}"
                    )
                    if psu_d:
                        metrics = await process_power_supply(
                            session, host, psu_d, p_type
                        )
                        update_prometheus_metrics(host, metrics)
        else:
            for psu in p_data.get("PowerSupplies", []):
                metrics = await process_power_supply(session, host, psu, p_type)
                update_prometheus_metrics(host, metrics)

    REQUEST_LATENCY.labels(host=host.fqdn).observe(time.monotonic() - start)

async def get_system_info(session: aiohttp.ClientSession, host: RedfishHost) -> None:
    """
    Fetch and update system information metrics for a Redfish host.

    Args:
        session: Active aiohttp client session.
        host: RedfishHost instance to query.
    """
    root = await fetch_with_retry(session, host, f"{host.fqdn}/redfish/v1/")
    if not root:
        return

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
                    "redfish_version": root.get("RedfishVersion", "unknown"),
                }
            )
