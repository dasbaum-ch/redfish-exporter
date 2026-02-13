# tests/test_health.py
import pytest
import time
from unittest.mock import patch
from exporter.health import HostHealth
from exporter.config import HostConfig


class TestHostHealth:
    """Tests for HostHealth class."""

    @pytest.fixture
    def config(self):
        """Create a default HostConfig for testing."""
        return HostConfig(
            fqdn="https://server.example.com",
            username="admin",
            password="secret",
            max_retries=3,
            cool_down=120,
        )

    def test_init_default_state(self, config):
        """Test HostHealth initializes with default state."""
        health = HostHealth(config)
        assert health.failures == 0
        assert health.next_retry_time == 0.0

    def test_should_skip_returns_false_initially(self, config):
        """Test should_skip returns False when not in cool-down."""
        health = HostHealth(config)
        assert health.should_skip is False

    def test_should_skip_returns_true_during_cooldown(self, config):
        """Test should_skip returns True during cool-down period."""
        health = HostHealth(config)
        # Set next_retry_time to the future
        health.next_retry_time = time.monotonic() + 100
        assert health.should_skip is True

    def test_should_skip_returns_false_after_cooldown(self, config):
        """Test should_skip returns False after cool-down expires."""
        health = HostHealth(config)
        # Set next_retry_time to the past
        health.next_retry_time = time.monotonic() - 10
        assert health.should_skip is False

    def test_mark_failure_increments_count(self, config):
        """Test mark_failure increments failure counter."""
        health = HostHealth(config)
        health.mark_failure()
        assert health.failures == 1

        health.mark_failure()
        assert health.failures == 2

    def test_mark_failure_triggers_cooldown_at_max_retries(self, config):
        """Test mark_failure triggers cool-down when max_retries is reached."""
        health = HostHealth(config)
        # max_retries is 3

        with patch("time.monotonic", return_value=1000.0):
            health.mark_failure()  # 1
            health.mark_failure()  # 2
            health.mark_failure()  # 3 - triggers cool-down

        assert health.failures == 0  # Reset after triggering cool-down
        assert health.next_retry_time == 1000.0 + 120  # cool_down is 120

    def test_mark_failure_no_cooldown_before_max_retries(self, config):
        """Test mark_failure does not trigger cool-down before max_retries."""
        health = HostHealth(config)

        health.mark_failure()
        health.mark_failure()  # Still under max_retries=3

        assert health.failures == 2
        assert health.next_retry_time == 0.0

    def test_mark_success_resets_failures(self, config):
        """Test mark_success resets failure counter."""
        health = HostHealth(config)
        health.failures = 2
        health.mark_success()
        assert health.failures == 0

    def test_mark_success_resets_next_retry_time(self, config):
        """Test mark_success resets next_retry_time."""
        health = HostHealth(config)
        health.next_retry_time = 1000.0
        health.mark_success()
        assert health.next_retry_time == 0.0

    def test_check_and_log_skip_returns_false_when_not_skipping(self, config):
        """Test check_and_log_skip returns False when not in cool-down."""
        health = HostHealth(config)
        result = health.check_and_log_skip("https://server.example.com")
        assert result is False

    def test_check_and_log_skip_returns_true_during_cooldown(self, config):
        """Test check_and_log_skip returns True during cool-down."""
        health = HostHealth(config)
        health.next_retry_time = time.monotonic() + 100
        result = health.check_and_log_skip("https://server.example.com")
        assert result is True

    def test_check_and_log_skip_logs_warning(self, config, caplog):
        """Test check_and_log_skip logs warning with remaining time."""
        import logging

        health = HostHealth(config)
        health.next_retry_time = time.monotonic() + 50

        with caplog.at_level(logging.WARNING):
            health.check_and_log_skip("https://server.example.com")

        assert "Skipping https://server.example.com" in caplog.text
        assert "in cool-down" in caplog.text

    def test_custom_max_retries(self):
        """Test health with custom max_retries configuration."""
        config = HostConfig(
            fqdn="https://server.example.com",
            username="admin",
            password="secret",
            max_retries=5,
            cool_down=120,
        )
        health = HostHealth(config)

        # Should not trigger cool-down until 5 failures
        for i in range(4):
            health.mark_failure()
            assert health.failures == i + 1
            assert health.next_retry_time == 0.0

        # 5th failure should trigger cool-down
        health.mark_failure()
        assert health.failures == 0
        assert health.next_retry_time > 0

    def test_custom_cooldown_duration(self):
        """Test health with custom cool_down configuration."""
        config = HostConfig(
            fqdn="https://server.example.com",
            username="admin",
            password="secret",
            max_retries=1,  # Trigger immediately
            cool_down=300,
        )
        health = HostHealth(config)

        with patch("time.monotonic", return_value=500.0):
            health.mark_failure()

        assert health.next_retry_time == 800.0  # 500 + 300

    def test_full_failure_recovery_cycle(self, config):
        """Test complete failure-cooldown-recovery cycle."""
        health = HostHealth(config)

        # Accumulate failures
        with patch("time.monotonic", return_value=1000.0):
            health.mark_failure()
            health.mark_failure()
            health.mark_failure()

        # Now in cool-down
        assert health.should_skip is False or health.next_retry_time > 0

        # Success resets everything
        health.mark_success()
        assert health.failures == 0
        assert health.next_retry_time == 0.0
        assert health.should_skip is False
