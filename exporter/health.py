# health.py
import time
import logging
from exporter.config import HostConfig

class HostHealth:
    """Manage host health."""

    def __init__(self, config: HostConfig):
        self._config = config
        self.failures = 0
        self.next_retry_time = 0.0

    @property
    def should_skip(self) -> bool:
        """Check if host is still in cool-down window"""
        return time.monotonic() < self.next_retry_time

    def check_and_log_skip(self, fqdn: str) -> bool:
        """Checks if host should be skipped and logs the remaining time if so."""
        if self.should_skip:
            remaining = max(0, self.next_retry_time - time.monotonic())
            logging.warning(
                "Skipping %s (in cool-down for %.0f seconds)", fqdn, remaining
            )
            return True
        return False

    def mark_failure(self):
        """Increase failure counter and maybe trigger cool-down"""
        self.failures += 1
        if self.failures >= self._config.max_retries:
            self.next_retry_time = time.monotonic() + self._config.cool_down
            self.failures = 0

    def mark_success(self):
        """Reset failure counter after a successful request"""
        self.failures = 0
        self.next_retry_time = 0.0
