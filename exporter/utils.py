# exporter/utils.py
from aiohttp import ClientTimeout
from typing import Optional, Any, Dict, Union
from exporter.redfish import RedfishHost
from exporter.config import PowerMetrics


def get_aiohttp_request_kwargs(
    verify_ssl: bool,
    timeout_seconds: int = 10,
    headers: Optional[Dict[str, str]] = None,
    auth: Optional[Any] = None,
) -> Dict[str, Any]:
    """Build common kwargs for aiohttp requests."""
    return {
        "ssl": verify_ssl,
        "timeout": ClientTimeout(total=timeout_seconds),
        "headers": headers or {},
        "auth": auth,
    }


def safe_get(data: Optional[Dict[str, Any]], *keys: str, default: Any = None) -> Any:
    """Traverse nested dict keys, returning default if any key is missing."""
    if data is None:
        return default
    for key in keys:
        if isinstance(data, dict) and key in data:
            data = data[key]
        else:
            return default
    return data


def validate_host_config(
    config: Union[Dict[str, Any], str], global_config: Dict[str, Any]
) -> Dict[str, Any]:
    """Merge host config with global defaults; raises ValueError if required fields missing."""
    if isinstance(config, str):
        config = {"fqdn": config}

    # Defaults for optional fields
    validated_config = {
        "fqdn": config.get("fqdn"),
        "username": config.get("username", global_config.get("username")),
        "password": config.get("password", global_config.get("password")),
        "verify_ssl": config.get("verify_ssl", global_config.get("verify_ssl", True)),
        "chassis": config.get("chassis", global_config.get("chassis", ["1"])),
        "group": config.get("group", global_config.get("group", "none")),
        "max_retries": config.get("max_retries", global_config.get("max_retries", 3)),
        "backoff": config.get("backoff", global_config.get("backoff", 2)),
        "cool_down": config.get("cool_down", global_config.get("cool_down", 120)),
    }

    if not validated_config.get("fqdn"):
        raise ValueError("Missing required field in config: fqdn")
    if not validated_config.get("username"):
        raise ValueError("Missing required field in config: username")
    if not validated_config.get("password"):
        raise ValueError("Missing required field in config: password")

    return validated_config


def safe_update_metrics(host: RedfishHost, metrics: Optional[PowerMetrics]) -> None:
    """Update Prometheus metrics if metrics is not None."""
    if metrics is not None:
        from exporter.metrics import update_prometheus_metrics

        update_prometheus_metrics(host, metrics)
