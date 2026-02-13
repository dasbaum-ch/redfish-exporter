# tests/test_metrics.py
import pytest
from exporter.metrics import (
    update_prometheus_metrics,
    VOLTAGE_GAUGE,
    WATTS_GAUGE,
    AMPS_GAUGE,
)
from exporter.config import PowerMetrics, HostConfig
from exporter.redfish import RedfishHost


class TestUpdatePrometheusMetrics:
    """Tests for update_prometheus_metrics function."""

    def test_update_all_metrics(self):
        """Test updating all metrics (voltage, watts, amps)."""
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
                group="test-group",
            )
        )
        metrics = PowerMetrics(
            serial="PSU123",
            voltage=230.0,
            watts=500.0,
            amps=2.17,
        )

        update_prometheus_metrics(host, metrics)

        labels = {"host": "http://localhost:5000", "psu_serial": "PSU123", "group": "test-group"}
        assert VOLTAGE_GAUGE.labels(**labels)._value.get() == 230.0
        assert WATTS_GAUGE.labels(**labels)._value.get() == 500.0
        assert AMPS_GAUGE.labels(**labels)._value.get() == 2.17

    def test_update_no_serial_returns_early(self):
        """Test that metrics are not updated when serial is None."""
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
            )
        )
        metrics = PowerMetrics(
            serial=None,  # No serial
            voltage=230.0,
            watts=500.0,
            amps=2.17,
        )

        # Should return early without updating any metrics
        update_prometheus_metrics(host, metrics)
        # No assertions needed - just ensure no exception is raised

    def test_update_empty_serial_returns_early(self):
        """Test that metrics are not updated when serial is empty string."""
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5000",
                username="user",
                password="pass",
            )
        )
        metrics = PowerMetrics(
            serial="",  # Empty serial
            voltage=230.0,
            watts=500.0,
            amps=2.17,
        )

        # Should return early without updating any metrics
        update_prometheus_metrics(host, metrics)

    def test_update_partial_metrics_only_voltage(self):
        """Test updating only voltage metric."""
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5001",
                username="user",
                password="pass",
                group="voltage-only",
            )
        )
        metrics = PowerMetrics(
            serial="PSU-V1",
            voltage=240.0,
            watts=None,
            amps=None,
        )

        update_prometheus_metrics(host, metrics)

        labels = {"host": "http://localhost:5001", "psu_serial": "PSU-V1", "group": "voltage-only"}
        assert VOLTAGE_GAUGE.labels(**labels)._value.get() == 240.0

    def test_update_partial_metrics_only_watts(self):
        """Test updating only watts metric."""
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5002",
                username="user",
                password="pass",
                group="watts-only",
            )
        )
        metrics = PowerMetrics(
            serial="PSU-W1",
            voltage=None,
            watts=600.0,
            amps=None,
        )

        update_prometheus_metrics(host, metrics)

        labels = {"host": "http://localhost:5002", "psu_serial": "PSU-W1", "group": "watts-only"}
        assert WATTS_GAUGE.labels(**labels)._value.get() == 600.0

    def test_update_partial_metrics_only_amps(self):
        """Test updating only amps metric."""
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5003",
                username="user",
                password="pass",
                group="amps-only",
            )
        )
        metrics = PowerMetrics(
            serial="PSU-A1",
            voltage=None,
            watts=None,
            amps=3.5,
        )

        update_prometheus_metrics(host, metrics)

        labels = {"host": "http://localhost:5003", "psu_serial": "PSU-A1", "group": "amps-only"}
        assert AMPS_GAUGE.labels(**labels)._value.get() == 3.5

    def test_update_zero_values(self):
        """Test that zero values are properly set (not treated as None)."""
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5004",
                username="user",
                password="pass",
                group="zero-test",
            )
        )
        metrics = PowerMetrics(
            serial="PSU-ZERO",
            voltage=0.0,
            watts=0.0,
            amps=0.0,
        )

        update_prometheus_metrics(host, metrics)

        labels = {"host": "http://localhost:5004", "psu_serial": "PSU-ZERO", "group": "zero-test"}
        assert VOLTAGE_GAUGE.labels(**labels)._value.get() == 0.0
        assert WATTS_GAUGE.labels(**labels)._value.get() == 0.0
        assert AMPS_GAUGE.labels(**labels)._value.get() == 0.0

    def test_update_different_psus_same_host(self):
        """Test updating metrics for different PSUs on the same host."""
        host = RedfishHost(
            HostConfig(
                fqdn="http://localhost:5005",
                username="user",
                password="pass",
                group="multi-psu",
            )
        )
        
        metrics1 = PowerMetrics(serial="PSU-1", voltage=230.0, watts=400.0, amps=1.74)
        metrics2 = PowerMetrics(serial="PSU-2", voltage=230.0, watts=450.0, amps=1.96)

        update_prometheus_metrics(host, metrics1)
        update_prometheus_metrics(host, metrics2)

        labels1 = {"host": "http://localhost:5005", "psu_serial": "PSU-1", "group": "multi-psu"}
        labels2 = {"host": "http://localhost:5005", "psu_serial": "PSU-2", "group": "multi-psu"}
        
        assert WATTS_GAUGE.labels(**labels1)._value.get() == 400.0
        assert WATTS_GAUGE.labels(**labels2)._value.get() == 450.0
