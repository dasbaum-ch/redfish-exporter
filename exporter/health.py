# health.py
import time
import logging
from exporter.config import HostConfig


class HostHealth:
    """
    Manage the health state of a Redfish host, including failure tracking and cool-down logic.

    Attributes:
        _config: Host configuration.
        failures: Number of consecutive failures.
        next_retry_time: Timestamp for the next allowed retry.
    """

    def __init__(self, config: HostConfig) -> None:
        """Initialize HostHealth with the given configuration.

        Args:
            config: Host configuration with retry and cool-down settings.
        """
        self._config = config
        self.failures = 0
        self.next_retry_time = 0.0

    @property
    def should_skip(self) -> bool:
        """Check if the host is still in the cool-down window.

        Returns:
            bool: True if the host should be skipped, False otherwise.
        """
        return time.monotonic() < self.next_retry_time

    def check_and_log_skip(self, fqdn: str) -> bool:
        """Check if the host should be skipped and log the remaining cool-down time.

        Args:
            fqdn: Fully Qualified Domain Name of the host.

        Returns:
            bool: True if the host should be skipped, False otherwise.
        """
        if self.should_skip:
            remaining = max(0, self.next_retry_time - time.monotonic())
            logging.warning(
                "Skipping %s (in cool-down for %.0f seconds)", fqdn, remaining
            )
            return True
        return False

    def mark_failure(self) -> None:
        """Increase the failure counter and trigger cool-down if max retries are reached."""
        self.failures += 1
        if self.failures >= self._config.max_retries:
            self.next_retry_time = time.monotonic() + self._config.cool_down
            self.failures = 0

    def mark_success(self) -> None:
        """Reset the failure counter after a successful request."""
        self.failures = 0
        self.next_retry_time = 0.0
