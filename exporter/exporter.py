import time
import logging
from dataclasses import dataclass, field
import asyncio
import aiohttp
import urllib3
from prometheus_client import (
    Gauge,
    start_http_server,
    Summary,
    Counter,
    Histogram,
    Info,
)


NO_DATA_ENTRY = "<no data>"


@dataclass
class RedfishResource:
    """Container for Redfish resource URLs."""

    chassis: str | None = None
    systems: str | None = None
    power: str | None = None
    session_service: str | None = None


@dataclass
class PowerMetrics:
    """Container for power metrics."""

    voltage: float | None = None
    watts: float | None = None
    amps: float | None = None
    serial: str | None = None


@dataclass
class RedfishSession:
    """Container for Redfish session data."""

    token: str | None = None
    logout_url: str | None = None
    vendor: str | None = None


@dataclass
class HostConfig:
    """Solve too many arguments"""

    fqdn: str
    username: str
    password: str
    chassis: list[str] | None = None
    group: str = "none"
    max_retries: int = 3  # 3 retires
    backoff: int = 2  # wait 2 seconds
    cool_down: int = 120  # seconds to wait after too many failures
    failures: int = 0
    next_retry_time: float = field(default=0.0, init=False)
    session: RedfishSession = field(default_factory=RedfishSession)

    def should_skip(self) -> bool:
        """Check if host is still in cool-down window"""
        return time.monotonic() < self.next_retry_time

    def mark_failure(self):
        """Increase failure counter and maybe trigger cool-down"""
        self.failures += 1
        if self.failures >= self.max_retries:
            self.next_retry_time = time.monotonic() + self.cool_down
            self.failures = 0  # reset after triggering cool-down

    def mark_success(self):
        """Reset failure counter after a successful request"""
        self.failures = 0
        self.next_retry_time = 0.0


# Disable certificate warnings
urllib3.disable_warnings()
# set log config
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

# Prometheus metrics
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
# set info metric
SYSTEM_INFO = Info(
    "redfish_system", "System information (model, serial, etc.)", ["host", "group"]
)


@REQUEST_TIME.time()
async def process_request(t):
    """Simulate request time"""
    await asyncio.sleep(t)


async def probe_vendor(session, host: HostConfig) -> str | None:
    """Probe the vendor of the Redfish host."""
    try:
        async with session.get(
            f"https://{host.fqdn}/redfish/v1/", ssl=False, timeout=10
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                vendor = data.get("Vendor", "")
                logging.debug("Detected vendor for %s: %s", host.fqdn, vendor)
                return vendor
            logging.warning(
                "Vendor probe failed on %s: HTTP %s", host.fqdn, resp.status
            )
    except Exception as e:
        logging.warning("Vendor probe failed for %s: %s", host.fqdn, e)
    return None


async def login_hpe(session, host: HostConfig) -> bool:
    """Login to HPE Redfish API and set session token."""
    login_url = f"https://{host.fqdn}/redfish/v1/SessionService/Sessions"
    payload = {"UserName": host.username, "Password": host.password}

    try:
        async with session.post(
            login_url, json=payload, ssl=False, timeout=10
        ) as login_resp:
            if login_resp.status == 201:
                host.session.token = login_resp.headers.get("X-Auth-Token")
                host.session.logout_url = login_resp.headers.get("Location")

                if not host.session.token or not host.session.logout_url:
                    raise RuntimeError("Invalid login response")

                logging.info("New session token obtained for %s", host.fqdn)
                return True
            logging.warning(
                "Login failed for %s: HTTP %s", host.fqdn, login_resp.status
            )
    except Exception as e:
        logging.warning("Login failed for %s: %s", host.fqdn, e)
    return False


async def fetch_with_retry(session, host: HostConfig, url: str) -> dict | None:
    """Fetch JSON from Redfish with retry/backoff."""
    if host.should_skip():
        logging.warning(
            "Skipping %s (in cool-down until %.1f)", host.fqdn, host.next_retry_time
        )
        UP_GAUGE.labels(host=host.fqdn, group=host.group).set(0)
        return None

    # Probe vendor if not already known
    if not host.session.vendor:
        host.session.vendor = await probe_vendor(session, host)

    is_hpe = host.session.vendor and host.session.vendor.strip().upper().startswith(
        "HPE"
    )

    for attempt in range(1, host.max_retries + 1):
        try:
            headers = {}

            if is_hpe:
                # Handle HPE session token
                if not host.session.token:
                    if not await login_hpe(session, host):
                        # Retry login next attempt
                        continue

                headers["X-Auth-Token"] = host.session.token

                async with session.get(
                    url, headers=headers, ssl=False, timeout=10
                ) as resp:
                    if resp.status == 200:
                        host.mark_success()
                        return await resp.json()
                    elif resp.status in (401, 403):
                        # Token expired or invalid, clear it and retry
                        logging.warning(
                            "Invalid token for %s, reauthenticating...", host.fqdn
                        )
                        host.session.token = None
                        continue
                    logging.warning(
                        "HTTP %s from %s (attempt %d)", resp.status, host.fqdn, attempt
                    )

            else:
                # Default: BasicAuth
                async with session.get(
                    url,
                    auth=aiohttp.BasicAuth(host.username, host.password),
                    ssl=False,
                    timeout=10,
                ) as resp:
                    if resp.status == 200:
                        host.mark_success()
                        return await resp.json()
                    logging.warning(
                        "HTTP %s from %s (attempt %d)", resp.status, host.fqdn, attempt
                    )

        except asyncio.TimeoutError:
            logging.warning("Timeout on %s (attempt %d)", host.fqdn, attempt)
        except aiohttp.ClientError as e:
            logging.warning(
                "Client error on %s (attempt %d): %s", host.fqdn, attempt, e
            )
        except Exception as e:
            logging.exception(
                "Unexpected error on %s (attempt %d): %s", host.fqdn, attempt, e
            )

        if attempt < host.max_retries:
            await asyncio.sleep(host.backoff * attempt)
        else:
            host.mark_failure()
            logging.error("All retries failed for %s", host.fqdn)

    return None


async def discover_redfish_resources(
    session, host: HostConfig
) -> RedfishResource | None:
    """Discover available Redfish resources and return relevant URLs"""
    root_url = f"https://{host.fqdn}/redfish/v1/"
    data = await fetch_with_retry(session, host, root_url)
    if not data:
        return {}

    # Create RedfishRessource object
    resources = RedfishResource(
        chassis=data.get("Chassis", {}).get("@odata.id"),
        systems=data.get("Systems", {}).get("@odata.id"),
        session_service=data.get("SessionService", {}).get("@odata.id"),
    )

    if not resources.chassis:
        logging.error("No valid Chassis URL found for host %s", host.fqdn)
        return None

    return resources


def get_power_resource_info(
    member_data: dict, host_fqdn: str, show_deprecated_warnings
) -> tuple[str | None, str | None]:
    """Get the URL and type of Power resource (PowerSubsystem or Power)."""
    # Try PowerSubsystem (new Redfish versions)
    power_url = member_data.get("PowerSubsystem", {}).get("@odata.id")
    if power_url:
        return f"https://{host_fqdn}{power_url}", "PowerSubsystem"

    # Try Power for older Redfish versions
    power_url = member_data.get("Power", {}).get("@odata.id")
    if power_url:
        if show_deprecated_warnings:
            logging.warning(
                "DEPRECATED: Host %s uses old Redfish API (Power instead of PowerSubsystem). "
                "Consider updating the firmware for full compatibility.",
                host_fqdn,
            )
        return f"https://{host_fqdn}{power_url}", "Power"

    # Nothing found -> Error
    logging.error("No Power or PowerSubsystem found for host %s", host_fqdn)
    return None, None


def process_power_supplies_url(
    power_data: dict, power_resource_type: str, host_fqdn: str
) -> str | None:
    """Get the URL for PowerSupplies based on the Power resource type."""
    if power_resource_type == "PowerSubsystem":
        # Bei PowerSubsystem: PowerSupplies ist ein separates Objekt
        power_supplies_url = power_data.get("PowerSupplies", {}).get("@odata.id")
        if power_supplies_url:
            return f"https://{host_fqdn}{power_supplies_url}"

    elif power_resource_type == "Power":
        # Bei Power: PowerSupplies ist direkt im Power-Objekt enthalten
        if "PowerSupplies" in power_data:
            return f"https://{host_fqdn}/redfish/v1/Chassis/1/Power"

    logging.error("No PowerSupplies found in Power resource for host %s", host_fqdn)
    return None


def process_power_supplies(
    power_data: dict,
    power_resource_type: str,
) -> list[dict] | None:
    """Get PowerSupplies data based on the Power resource type."""
    if power_resource_type == "PowerSubsystem":
        # PowerSubsystem: PowerSupplies is a ressource with Members
        power_supplies_url = power_data.get("PowerSupplies", {}).get("@odata.id")
        if not power_supplies_url:
            logging.error("No PowerSupplies URL found for PowerSubsystem")
            return None
        return None  # If none, then use the PowerSubsystem member url

    elif power_resource_type == "Power":
        # Power: PowerSupplies is an array!
        return power_data.get("PowerSupplies", [])

    logging.error("Unknown power resource type")
    return None


async def process_power_supply(
    session, host: HostConfig, psu_data: dict, power_resource_type: str
) -> PowerMetrics | None:
    """Extract metrics from PowerSupply"""
    serial = psu_data.get("SerialNumber")
    metrics = PowerMetrics(serial=serial)

    if power_resource_type == "PowerSubsystem":
        # New Redfish API: Metrics are an own "Metrics" ressource
        metrics_url = psu_data.get("Metrics", {}).get("@odata.id")
        if not metrics_url:
            logging.warning("No Metrics found for PowerSupply %s", psu_data.get("Id"))
            return None

        metrics_url = f"https://{host.fqdn}{metrics_url}"
        metrics_data = await fetch_with_retry(session, host, metrics_url)
        if not metrics_data:
            return None

        # Get metrics from Metrics ressource
        metrics.voltage = metrics_data.get("InputVoltage", {}).get("Reading")
        metrics.watts = metrics_data.get("InputPowerWatts", {}).get("Reading")
        metrics.amps = metrics_data.get("InputCurrentAmps", {}).get("Reading")

    elif power_resource_type == "Power":
        # Older Redfish API: Metrics are direct in PowerSupply as an array
        metrics.voltage = psu_data.get("LineInputVoltage")
        metrics.watts = psu_data.get("PowerInputWatts")
        if metrics.watts is None:
            metrics.watts = psu_data.get("LastPowerOutputWatts")
        metrics.amps = psu_data.get("InputCurrentAmps")
        if metrics.amps is None and metrics.voltage and metrics.watts:
            metrics.amps = round(metrics.watts / metrics.voltage, 2)

    else:
        logging.error(
            "Unknown power resource type for PowerSupply %s", psu_data.get("Id")
        )

        return None

    return metrics


def normalize_url(url: str) -> str:
    """Ensure URL does not end with a trailing slash."""
    # I needed this for realy old Redfish versions :S (<1.6.0)
    if url.endswith("/"):
        return url[:-1]  # Remove trailing slash
    return url


async def get_power_data(session, host: HostConfig, show_deprecated_warnings):
    """Query Redfish for power data and update Prometheus metrics"""
    if host.should_skip():
        logging.warning(
            "Skipping %s (in cool-down until %.1f)", host.fqdn, host.next_retry_time
        )
        UP_GAUGE.labels(host=host.fqdn, group=host.group).set(0)
        return

    # Start time measurement
    start = time.monotonic()

    # Get root ressources
    resources = await discover_redfish_resources(session, host)
    if not resources or not resources.chassis:
        logging.error("Could not discover any resources for %s", host.fqdn)
        host.mark_failure()
        UP_GAUGE.labels(host=host.fqdn, group=host.group).set(0)
        return

    host.mark_success()
    UP_GAUGE.labels(host=host.fqdn, group=host.group).set(1)

    chassis_url = f"https://{host.fqdn}{resources.chassis}"
    chassis_data = await fetch_with_retry(session, host, chassis_url)
    if not chassis_data:
        host.mark_failure()
        UP_GAUGE.labels(host=host.fqdn, group=host.group).set(0)
        return

    for chassis_member in chassis_data.get("Members", []):
        chassis_member_url = chassis_member.get("@odata.id")
        if not chassis_member_url:
            continue

        # Normalize URL... I needed this for realy old Redfish versions :S (<1.6.0)
        chassis_member_url = normalize_url(chassis_member_url)
        # Get chassis id from url ("/redfish/v1/Chassis/1" -> 1)
        chassis_member_id = chassis_member_url.split("/")[-1]
        # Check if the chassis id is in config (had problem with chassis "NVMe")
        if hasattr(host, "chassis") and host.chassis:
            if chassis_member_id not in host.chassis:
                continue

        member_url = f"https://{host.fqdn}{chassis_member_url}"
        member_data = await fetch_with_retry(session, host, member_url)
        if not member_data:
            continue

        # Get Power ressource (fallback to "Power")
        power_resource_url, power_resource_type = get_power_resource_info(
            member_data, host.fqdn, show_deprecated_warnings
        )
        if not power_resource_url:
            continue

        # Get Power Data
        power_data = await fetch_with_retry(session, host, power_resource_url)
        if not power_data:
            continue

        # Get PowerSupplies, depend on ressource type ("Power" or "PowerSubsystem")
        if power_resource_type == "PowerSubsystem":
            # Request PowerSupplies url (for PowerSubsystem)
            power_supplies_url = power_data.get("PowerSupplies", {}).get("@odata.id")
            if not power_supplies_url:
                logging.warning("No PowerSupplies found for %s", host.fqdn)
                continue

            power_supplies_url = f"https://{host.fqdn}{power_supplies_url}"
            power_supplies_data = await fetch_with_retry(
                session, host, power_supplies_url
            )
            if not power_supplies_data:
                continue

            # loop over Members for "PowerSubsystem"
            for psu_member in power_supplies_data.get("Members", []):
                psu_url = psu_member.get("@odata.id")
                if not psu_url:
                    continue

                psu_url = f"https://{host.fqdn}{psu_url}"
                psu_data = await fetch_with_retry(session, host, psu_url)
                if not psu_data:
                    continue

                # Process PowerSupplies object
                metrics = await process_power_supply(
                    session, host, psu_data, "PowerSubsystem"
                )
                if metrics:
                    update_prometheus_metrics(host, metrics)

        elif power_resource_type == "Power":
            # Loop over PowerSupplies for older Redfish versions
            for psu in power_data.get("PowerSupplies", []):
                # Process PowerSupplies object
                metrics = await process_power_supply(session, host, psu, "Power")
                if metrics:
                    update_prometheus_metrics(host, metrics)

        else:
            logging.error("Unknown power resource type for host %s", host.fqdn)
            continue

    # Measure request and process latency
    REQUEST_LATENCY.labels(host=host.fqdn).observe(time.monotonic() - start)


def update_prometheus_metrics(host: HostConfig, metrics: PowerMetrics):
    """Update Prometheus metrics with PowerMetrics data."""
    if metrics.voltage is not None and metrics.serial:
        VOLTAGE_GAUGE.labels(
            host=host.fqdn, psu_serial=metrics.serial, group=host.group
        ).set(metrics.voltage)
    if metrics.watts is not None and metrics.serial:
        WATTS_GAUGE.labels(
            host=host.fqdn, psu_serial=metrics.serial, group=host.group
        ).set(metrics.watts)
    if metrics.amps is not None and metrics.serial:
        AMPS_GAUGE.labels(
            host=host.fqdn, psu_serial=metrics.serial, group=host.group
        ).set(metrics.amps)


async def get_system_info(session, host: HostConfig):
    """Query Redfish for system data and update Prometheus metrics"""

    if host.should_skip():
        logging.warning(
            "Skipping %s (in cool-down until %.1f)",
            host.fqdn,
            host.next_retry_time,
        )

        return

    # get Redfish version

    root_data = await fetch_with_retry(
        session,
        host,
        f"https://{host.fqdn}/redfish/v1/",
    )

    if not root_data:
        host.mark_failure()

        return

    redfish_version = root_data.get("RedfishVersion")

    # get manufacturer, serial and model

    systems_data = await fetch_with_retry(
        session,
        host,
        f"https://{host.fqdn}/redfish/v1/Systems",
    )

    if not systems_data:
        host.mark_failure()

        return

    # track each system member with system data
    for system_member in systems_data.get("Members", []):
        system_url = system_member.get("@odata.id")

        if not system_url:
            continue

        system_data = await fetch_with_retry(
            session, host, f"https://{host.fqdn}{system_url}"
        )

        if not system_data:
            continue

        # This block has been sponsored by Aperture Science.
        #   We do what we must, because we can.
        SYSTEM_INFO.labels(host=host.fqdn, group=host.group).info(
            {
                "manufacturer": system_data.get("Manufacturer") or NO_DATA_ENTRY,
                "model": system_data.get("Model") or NO_DATA_ENTRY,
                "serial_number": system_data.get("SerialNumber") or NO_DATA_ENTRY,
                "redfish_version": redfish_version,
            }
        )


async def logout_host(session, host):
    """Clean logout for Redfish with session tokens"""

    if not host.session.token or not host.session.logout_url:
        return

    try:
        logout_url = host.session.logout_url

        async with session.delete(
            logout_url,
            headers={"X-Auth-Token": host.session.token},
            ssl=False,
            timeout=5,
        ) as resp:
            if resp.status in (200, 204):
                logging.info(f"Logged out from {host.fqdn}")
            else:
                logging.warning(f"Logout failed for {host.fqdn} (HTTP {resp.status})")

    except Exception as e:
        logging.warning("Error during logout for %s: %s", host.fqdn, e)

    finally:
        host.session.token = None

        host.session.logout_url = None


async def run_exporter(config, stop_event, show_deprecated_warnings):
    """Run exporter"""

    port = config.get("port", 8000)
    default_username = config.get("username")
    default_password = config.get("password")
    default_chassis = config.get("chassis", "1")
    default_group = config.get("group", "none")
    hosts = config["hosts"]
    interval = config.get("interval", 10)

    # Start Prometheus metrics server

    start_http_server(port)

    logging.info("Prometheus metrics server running on port %s", port)

    # create persistent HostConfig objects

    host_objs = []

    for host_entry in hosts:
        if isinstance(host_entry, dict):
            hc = HostConfig(
                fqdn=host_entry["fqdn"],
                username=host_entry.get("username", default_username),
                password=host_entry.get("password", default_password),
                chassis=host_entry.get("chassis", default_chassis),
                group=host_entry.get("group", default_group),
            )
        else:
            hc = HostConfig(
                fqdn=host_entry,
                username=default_username,
                password=default_password,
                chassis=default_chassis,
                group=default_group,
            )

        host_objs.append(hc)

    # Pool connections

    connector = aiohttp.TCPConnector(
        limit_per_host=5,
        limit=50,
        ttl_dns_cache=300,
    )

    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            while not stop_event.is_set():
                tasks = []

                for hc in host_objs:
                    tasks.append(
                        get_power_data(
                            session,
                            hc,
                            show_deprecated_warnings,
                        )
                    )

                    tasks.append(get_system_info(session, hc))

                await asyncio.gather(*tasks)

                await process_request(interval)
        finally:
            # Graceful shutdown: logout from Redfish sessions

            logging.info("Exporter stopping, logging out from Redfish sessions...")

            await asyncio.gather(
                *(logout_host(session, h) for h in host_objs if h.session.token)
            )

            logging.info("All sessions logged out.")

    logging.info("Exporter stopped cleanly.")
