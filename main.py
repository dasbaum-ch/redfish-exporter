"""Simple Redfish exporter to collect Power data from bare matel server"""

import argparse
import signal
import time
import logging
from dataclasses import dataclass, field
import asyncio
import aiohttp
import urllib3
import yaml
from prometheus_client import (
    Gauge,
    start_http_server,
    Summary,
    Counter,
    Histogram,
    Info,
)


@dataclass
class HostConfig:
    """Solve too many arguments"""

    fqdn: str
    username: str
    password: str
    chassis: list[str] | None = None
    max_retries: int = 1
    backoff: int = 2
    cool_down: int = 120  # seconds to wait after too many failures
    failures: int = 0
    next_retry_time: float = field(default=0.0, init=False)

    # New attributes for Redfish stuff
    vendor: str | None = None
    session_token: str | None = None
    session_logout: str | None = (
        None  # SessionLocation like /redfish/v1/SessionService/Sessions/marco.lucarelli%40abacus.ch00000000xxx/
    )

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
up_gauge = Gauge("redfish_up", "Host up/down", ["host"])
error_counter = Counter(
    "redfish_errors_total", "Total Redfish errors", ["host", "error"]
)
voltage_gauge = Gauge(
    "redfish_psu_line_input_voltage_volts",
    "Line Input Voltage per PSU",
    ["host", "psu_serial"],
)
watts_gauge = Gauge(
    "redfish_psu_power_input_watts", "Power Input Watts per PSU", ["host", "psu_serial"]
)
amps_gauge = Gauge(
    "redfish_psu_input_amps", "Current draw in Amps per PSU", ["host", "psu_serial"]
)
# set info metric
system_info = Info(
    "redfish_system_info", "System information (model, serial, etc.)", ["host"]
)


@REQUEST_TIME.time()
async def process_request(t):
    """Simulate request time"""
    await asyncio.sleep(t)


async def fetch_with_retry(session, host: HostConfig, url: str) -> dict | None:
    """Fetch JSON from Redfish with retry/backoff"""
    if host.should_skip():
        logging.warning(
            "Skipping %s (in cool-down until %.1f)", host.fqdn, host.next_retry_time
        )
        up_gauge.labels(host=host.fqdn).set(0)
        return None

    if not host.vendor:
        try:
            async with session.get(
                f"https://{host.fqdn}/redfish/v1/", ssl=False, timeout=10
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    host.vendor = data.get("Vendor", "")
                    logging.debug("Detected vendor for %s: %s", host.fqdn, host.vendor)
                else:
                    logging.warning(
                        "Vendor probe failed on %s: HTTP %s", host.fqdn, resp.status
                    )
        except Exception as e:
            logging.warning("Vendor probe failed for %s: %s", host.fqdn, e)

    is_hpe = host.vendor and host.vendor.strip().upper().startswith("HPE")

    for attempt in range(1, host.max_retries + 1):
        try:
            headers = {}

            if is_hpe:
                # Try to reuse existing session token
                if host.session_token:
                    headers["X-Auth-Token"] = host.session_token
                    logging.debug("Reusing cached session token for %s", host.fqdn)
                else:
                    # Need to login and store new session token
                    # HPE Redfish login
                    login_url = (
                        f"https://{host.fqdn}/redfish/v1/SessionService/Sessions"
                    )
                    payload = {"UserName": host.username, "Password": host.password}
                    async with session.post(
                        login_url, json=payload, ssl=False, timeout=10
                    ) as login_resp:
                        if login_resp.status == 201:
                            host.session_token = login_resp.headers.get(
                                "X-Auth-Token"
                            )  # as response in header
                            if not host.session_token:
                                raise RuntimeError("No X-Auth-Token in login response")
                            host.session_logout = login_resp.headers.get(
                                "Location"
                            )  # as response in header
                            if not host.session_logout:
                                raise RuntimeError("No Location in login response")
                            headers["X-Auth-Token"] = host.session_token
                            logging.info("New session token obtained for %s", host.fqdn)
                        else:
                            logging.warning(
                                "Login failed for %s: HTTP %s",
                                host.fqdn,
                                login_resp.status,
                            )
                            continue  # retry login next attempt

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
                        host.session_token = None
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


async def discover_redfish_resources(session, host: HostConfig) -> dict:
    """Discover available Redfish resources and return relevant URLs"""
    root_url = f"https://{host.fqdn}/redfish/v1/"
    data = await fetch_with_retry(session, host, root_url)
    if not data:
        return {}

    # Extrahiere Links aus der Root-Antwort
    links = {
        "Chassis": data.get("Chassis", {}).get("@odata.id"),
        "Systems": data.get("Systems", {}).get("@odata.id"),
        "SessionService": data.get("SessionService", {}).get("@odata.id"),
    }
    if not links["Chassis"]:
        logging.error("No valid Chassis URL found for host %s", host.fqdn)
        return {}
    return links


def get_power_resource_info(
    member_data: dict, host_fqdn: str
) -> tuple[str | None, str | None]:
    """Get the URL and type of Power resource (PowerSubsystem or Power)."""
    # Try PowerSubsystem (new Redfish versions)
    power_url = member_data.get("PowerSubsystem", {}).get("@odata.id")
    if power_url:
        return f"https://{host_fqdn}{power_url}", "PowerSubsystem"

    # Try Power for older Redfish versions
    power_url = member_data.get("Power", {}).get("@odata.id")
    if power_url:
        logging.warning(
            "DEPRECATED: Host %s uses old Redfish API (Power instead of PowerSubsystem). "
            "Consider updating the firmware for full compatibility.",
            host_fqdn,
        )
        return f"https://{host_fqdn}{power_url}", "Power"

    # Nothing found -> Error
    logging.error("No Power or PowerSubsystem found for host %s", host_fqdn)
    return None, None


def get_power_supplies_url(
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


def get_power_supplies(
    power_data: dict, power_resource_type: str, host_fqdn: str
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
):
    """Extract metrics from PowerSupply"""
    serial = psu_data.get("SerialNumber")

    if power_resource_type == "PowerSubsystem":
        # Newer Redfish API: Metrics are an own "Metrics" ressource
        metrics_url = psu_data.get("Metrics", {}).get("@odata.id")
        if not metrics_url:
            logging.warning("No Metrics found for PowerSupply %s", psu_data.get("Id"))
            return

        metrics_url = f"https://{host.fqdn}{metrics_url}"
        metrics_data = await fetch_with_retry(session, host, metrics_url)
        if not metrics_data:
            return

        # Get metrics from Metrics ressource
        line_input_v = metrics_data.get("InputVoltage", {}).get("Reading")
        watts_input = metrics_data.get("InputPowerWatts", {}).get("Reading")
        amps_input = metrics_data.get("InputCurrentAmps", {}).get("Reading")

    elif power_resource_type == "Power":
        # Older Redfish API: Metrics are direct in PowerSupply as an array
        line_input_v = psu_data.get("LineInputVoltage")
        watts_input = psu_data.get("PowerInputWatts")
        if watts_input is None:
            watts_input = psu_data.get("LastPowerOutputWatts")
        amps_input = psu_data.get("InputCurrentAmps")
        if amps_input is None:
            if line_input_v and watts_input:
                amps_input = round(watts_input / line_input_v, 2)

    else:
        logging.error(
            "Unknown power resource type for PowerSupply %s", psu_data.get("Id")
        )
        return

    if amps_input is None and line_input_v and watts_input:
        amps_input = round(watts_input / line_input_v, 2)

    # Update Prometheus metrics
    if line_input_v is not None:
        voltage_gauge.labels(host=host.fqdn, psu_serial=serial).set(line_input_v)
    if watts_input is not None:
        watts_gauge.labels(host=host.fqdn, psu_serial=serial).set(watts_input)
    if amps_input is not None:
        amps_gauge.labels(host=host.fqdn, psu_serial=serial).set(amps_input)

def normalize_url(url: str) -> str:
    """Ensure URL does not end with a trailing slash."""
    # I needed this for realy old Redfish versions :S (<1.6.0)
    if url.endswith('/'):
        return url[:-1]  # Remove trailing slash
    return url

async def get_power_data(session, host: HostConfig):
    """Query Redfish for power data and update Prometheus metrics"""
    if host.should_skip():
        logging.warning(
            "Skipping %s (in cool-down until %.1f)", host.fqdn, host.next_retry_time
        )
        up_gauge.labels(host=host.fqdn).set(0)
        return

    # Start time measurement
    start = time.monotonic()
    # Root ressource abfragen
    resources = await discover_redfish_resources(session, host)
    if not resources:
        logging.error("Could not discover any resources for %s", host.fqdn)
        host.mark_failure()
        up_gauge.labels(host=host.fqdn).set(0)
        return
    
    chassis_url = resources.get("Chassis")
    if not chassis_url:
        logging.error("No valid Chassis URL found for %s", host.fqdn)
        host.mark_failure()
        up_gauge.labels(host=host.fqdn).set(0)
        return

    # Mark host as up
    host.mark_success()
    up_gauge.labels(host=host.fqdn).set(1)

    # Get chassis ressource
    chassis_url = f"https://{host.fqdn}{chassis_url}"
    chassis_data = await fetch_with_retry(session, host, chassis_url)
    if not chassis_data:
        host.mark_failure()
        up_gauge.labels(host=host.fqdn).set(0)
        return

    # loop over each member in chassis ressource
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
            member_data, host.fqdn
        )
        if not power_resource_url:
            continue

        # Get Power Data
        power_data = await fetch_with_retry(session, host, power_resource_url)
        if not power_data:
            continue

        # Get PowerSupplies, depend on ressource type ("Power" or "PowerSubsystem")
        if power_resource_type == "PowerSubsystem":
            # PowerSupplies-URL abfragen (für PowerSubsystem)
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
                await process_power_supply(session, host, psu_data, "PowerSubsystem")

        elif power_resource_type == "Power":
            # Loop over PowerSupplies for older Redfish versions
            for psu in power_data.get("PowerSupplies", []):
                # Process PowerSupplies object
                await process_power_supply(session, host, psu, "Power")

        else:
            logging.error("Unknown power resource type for host %s", host.fqdn)
            continue

    # Measure request and process latency
    REQUEST_LATENCY.labels(host=host.fqdn).observe(time.monotonic() - start)


async def get_system_info(session, host: HostConfig):
    """Query Redfish for system data and update Prometheus metrics"""
    if host.should_skip():
        logging.warning(
            "Skipping %s (in cool-down until %.1f)", host.fqdn, host.next_retry_time
        )
        return

    # Get Redfish Version
    root_url = f"https://{host.fqdn}/redfish/v1/"
    root_data = await fetch_with_retry(session, host, root_url)
    if not root_data:
        host.mark_failure()
        return

    redfish_version = root_data.get("RedfishVersion")
    # Get Manufacturer, Serial and Model
    systems_url = f"https://{host.fqdn}/redfish/v1/Systems/"
    systems_data = await fetch_with_retry(session, host, systems_url)
    if not systems_data:
        host.mark_failure()
        return

    # loop for each system members
    for system_member in systems_data.get("Members", []):
        system_url = system_member.get("@odata.id")
        if not system_url:
            continue

        system_data = await fetch_with_retry(
            session, host, f"https://{host.fqdn}{system_url}"
        )
        if not system_data:
            continue

        manufacturer = system_data.get("Manufacturer")
        model = system_data.get("Model")
        serial_number = system_data.get("SerialNumber")

        # Hier könnte ihre Werbung stehen
        system_info.labels(host=host.fqdn).info(
            {
                "manufacturer": manufacturer,
                "model": model,
                "serial_number": serial_number,
                "redfish_version": redfish_version,
            }
        )


async def logout_host(session, host):
    """Clean logout for Redfish with session tokens"""
    if not host.session_token:
        return
    if not host.session_logout:
        return
    try:
        logout_url = f"{host.session_logout}"  # the full URL is here!
        async with session.delete(
            logout_url,
            headers={"X-Auth-Token": host.session_token},
            ssl=False,
            timeout=5,
        ) as resp:
            if resp.status in (200, 204):
                logging.info("Logged out from %s", host.fqdn)
            else:
                logging.warning(
                    "Logout failed for %s (HTTP %s)", host.fqdn, resp.status
                )
    except Exception as e:
        logging.warning("Error during logout for %s: %s", host.fqdn, e)
    finally:
        host.session_token = None


async def run_exporter(config, stop_event):
    """Main loop"""
    port = config.get("port", 8000)
    default_username = config.get("username")
    default_password = config.get("password")
    default_chassis = config.get("chassis")
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
            )
        else:
            hc = HostConfig(
                fqdn=host_entry, username=default_username, password=default_password
            )
        host_objs.append(hc)

    # Connection pooling with aiohttp
    connector = aiohttp.TCPConnector(limit_per_host=5, limit=50, ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=connector) as session:
        try:
            while not stop_event.is_set():
                tasks = []
                for hc in host_objs:
                    tasks.append(get_power_data(session, hc))
                    tasks.append(get_system_info(session, hc))
                await asyncio.gather(*tasks)
                await process_request(interval)
        finally:
            # Graceful shutdown: logout from Redfish sessions
            logging.info("Exporter stopping, logging out from Redfish sessions...")
            await asyncio.gather(
                *(logout_host(session, h) for h in host_objs if h.session_token)
            )
            logging.info("All sessions logged out.")
    logging.info("Exporter stopped cleanly.")


async def main():
    """Modern asyncio entry point"""
    parser = argparse.ArgumentParser(description="Redfish Prometheus Exporter")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--port", type=int, help="Override port from config file")
    parser.add_argument(
        "--interval", type=int, help="Override interval from config file"
    )
    args = parser.parse_args()

    # Load YAML config
    with open(args.config, "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    # Override port if argument is provided
    if args.port is not None:
        config["port"] = args.port
    if args.interval is not None:
        config["interval"] = args.interval

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    # Handle SIGINT (Ctrl+C) and SIGTERM
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    await run_exporter(config, stop_event)


if __name__ == "__main__":
    asyncio.run(main())
