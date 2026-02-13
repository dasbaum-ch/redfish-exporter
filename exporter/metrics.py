# metrics.py
from prometheus_client import (
    Gauge,
    Summary,
    Counter,
    Histogram,
    Info,
)
from exporter.config import PowerMetrics

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

def update_prometheus_metrics(host, metrics: PowerMetrics) -> None:
    """
    Update Prometheus metrics with the given power metrics for a host.

    Args:
        host: RedfishHost instance.
        metrics: PowerMetrics instance with voltage, watts, and amps.
    """
    if not metrics.serial:
        return
    labels = {"host": host.fqdn, "psu_serial": metrics.serial, "group": host.group}
    if metrics.voltage is not None:
        VOLTAGE_GAUGE.labels(**labels).set(metrics.voltage)
    if metrics.watts is not None:
        WATTS_GAUGE.labels(**labels).set(metrics.watts)
    if metrics.amps is not None:
        AMPS_GAUGE.labels(**labels).set(metrics.amps)
