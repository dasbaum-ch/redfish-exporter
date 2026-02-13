# main.py
import logging
import asyncio
import aiohttp
from prometheus_client import start_http_server
from exporter.config import HostConfig
from exporter.redfish import RedfishHost
from exporter.api import get_power_data, get_system_info, logout_host

async def process_request(t):
    """Simulate request time"""
    await asyncio.sleep(t)

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
            logging.info(
                "Exporter stopping, logging out from all active Redfish sessions..."
            )
            logout_tasks = [
                logout_host(session, h)
                for h in host_objs
                if h.session.token is not None
            ]
            if logout_tasks:
                await asyncio.gather(*logout_tasks)
                logging.info(f"Successfully processed {len(logout_tasks)} logouts.")
            else:
                logging.info("No active sessions to log out.")
