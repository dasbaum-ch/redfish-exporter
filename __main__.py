"""Main entry point for the Redfish Prometheus Exporter."""

import argparse
import signal
import logging
import asyncio
import yaml
from exporter import run_exporter


async def main() -> None:
    """Assemble configuration and run the exporter."""
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Redfish Prometheus Exporter.")

    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config file.",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Override port from config file.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        help="Override interval from config file.",
    )
    parser.add_argument(
        "--show-deprecated",
        action="store_true",
        help="Enable deprecated warnings in log.",
    )

    args = parser.parse_args()

    show_deprecated_warnings = args.show_deprecated

    if show_deprecated_warnings:
        logging.warning("Deprecated warnings are enabled.")

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
    def signal_handler() -> None:
        logging.info("SIGINT or SIGTERM received, shutting down gracefully...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    await run_exporter(config, stop_event, show_deprecated_warnings)


if __name__ == "__main__":
    asyncio.run(main())
