import time
import logging
from dataclasses import dataclass, field
import asyncio
import aiohttp
from prometheus_client import (
    Gauge,
    start_http_server,
    Summary,
    Counter,
    Histogram,
    Info,
)

NO_DATA_ENTRY = "<no data>"


@dataclass(frozen=True)
class HostConfig:
    """Static host config"""

    fqdn: str
    username: str
    password: str
    verify_ssl: bool = True
    chassis: list[str] = field(default_factory=lambda: ["1"])
    group: str = "none"
    max_retries: int = 3
    backoff: int = 2
    cool_down: int = 120


class HostHealth:
    """Manage host health."""

    def __init__(self, config: HostConfig):
        self._config = config
        self.failures = 0
        self.next_retry_time = 0.0

    @property
    def should_skip(self) -> bool:
        return time.monotonic() < self.next_retry_time

    def check_and_log_skip(self, fqdn: str) -> bool:
        if self.should_skip:
            remaining = max(0, self.next_retry_time - time.monotonic())
            logging.warning(
                "Skipping %s (in cool-down for %.0f seconds)", fqdn, remaining
            )
            return True
        return False

    def mark_failure(self):
        self.failures += 1
        if self.failures >= self._config.max_retries:
            self.next_retry_time = time.monotonic() + self._config.cool_down
            self.failures = 0

    def mark_success(self):
        self.failures = 0
        self.next_retry_time = 0.0


@dataclass
class RedfishSessionState:
    """Save state for login, logout, sessions and vendor."""

    token: str | None = None
    logout_url: str | None = None
    vendor: str | None = None

    @property
    def is_hpe(self) -> bool:
        return bool(self.vendor and self.vendor.strip().upper().startswith("HPE"))


class RedfishHost:
    """Main config class for exporter."""

    def __init__(self, config: HostConfig):
        self.cfg = config
        self.health = HostHealth(config)
        self.session = RedfishSessionState()

    @property
    def fqdn(self) -> str:
        return self.cfg.fqdn

    @property
    def group(self) -> str:
        return self.cfg.group


@dataclass
class PowerMetrics:
    """Container for Power metrics."""

    voltage: float | None = None
    watts: float | None = None
    amps: float | None = None
    serial: str | None = None


# --- Logging ---

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

REQUEST_TIME = Summary("request_processing_seconds", "Time spent processing request")
REQUEST_LATENCY = Histogram(
    "redfish_request_latency_seconds", "Time for Redfish request", ["host"]
)
UP_GAUGE = Gauge("redfish_up", "Host up/down", ["host", "group"])
ERROR_COUNTER = Counter(
    "redfish_errors_total", "Total Redfish errors", ["host", "error"]
)
VOLTAGE_GAUGE = Gauge(
    "redfish_psu_input_voltage",
    "Line Input Voltage per PSU",
    ["host", "psu_serial", "group"],
)
WATTS_GAUGE = Gauge(
    "redfish_psu_input_watts",
    "Power Input Watts per PSU",
    ["host", "psu_serial", "group"],
)
AMPS_GAUGE = Gauge(
    "redfish_psu_input_amps",
    "Current draw in Amps per PSU",
    ["host", "psu_serial", "group"],
)
SYSTEM_INFO = Info("redfish_system", "System information", ["host", "group"])

# --- Helper ---


@REQUEST_TIME.time()
async def process_request(t):
    await asyncio.sleep(t)


async def probe_vendor(session, host: RedfishHost) -> str | None:
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


async def login_hpe(session, host: RedfishHost) -> bool:
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


async def fetch_with_retry(session, host: RedfishHost, url: str) -> dict | None:
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
    return url[:-1] if url.endswith("/") else url


async def process_power_supply(
    session, host: RedfishHost, psu_data: dict, resource_type: str
) -> PowerMetrics | None:
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


def update_prometheus_metrics(host: RedfishHost, metrics: PowerMetrics):
    if not metrics.serial:
        return
    labels = {"host": host.fqdn, "psu_serial": metrics.serial, "group": host.group}
    if metrics.voltage is not None:
        VOLTAGE_GAUGE.labels(**labels).set(metrics.voltage)
    if metrics.watts is not None:
        WATTS_GAUGE.labels(**labels).set(metrics.watts)
    if metrics.amps is not None:
        AMPS_GAUGE.labels(**labels).set(metrics.amps)


async def get_power_data(session, host: RedfishHost, show_deprecated_warnings: bool):
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

        # Check which Power ressource is available
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


async def get_system_info(session, host: RedfishHost):
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


async def logout_host(session, host: RedfishHost):
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
    except Exception as e:
        logging.warning("Logout error for %s: %s", host.fqdn, e)
    finally:
        host.session.token = None


async def run_exporter(config, stop_event, show_deprecated_warnings):
    port = config.get("port", 8000)
    interval = config.get("interval", 10)
    start_http_server(port)
    logging.info("Metrics server on http://localhost:%s", port)

    host_objs = []
    for entry in config["hosts"]:
        is_dict = isinstance(entry, dict)
        raw_fqdn = entry["fqdn"] if is_dict else entry

        cfg = HostConfig(
            fqdn=raw_fqdn.rstrip("/"),
            username=entry.get("username", config.get("username"))
            if is_dict
            else config.get("username"),
            password=entry.get("password", config.get("password"))
            if is_dict
            else config.get("password"),
            verify_ssl=entry.get("verify_ssl", config.get("verify_ssl", True))
            if is_dict
            else config.get("verify_ssl", True),
            chassis=entry.get("chassis", config.get("chassis", ["1"]))
            if is_dict
            else config.get("chassis", ["1"]),
            group=entry.get("group", config.get("group", "none"))
            if is_dict
            else config.get("group", "none"),
        )
        host_objs.append(RedfishHost(cfg))

    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit=50)
    ) as session:
        try:
            while not stop_event.is_set():
                tasks = []
                for h in host_objs:
                    tasks.append(get_power_data(session, h, show_deprecated_warnings))
                    tasks.append(get_system_info(session, h))
                await asyncio.gather(*tasks)
                await process_request(interval)
        finally:
            await asyncio.gather(*(logout_host(session, h) for h in host_objs))
