"""Runtime configuration for the warehouse service."""
from dataclasses import dataclass

DEFAULT_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class ServiceConfig:
    """Connection settings shared by every warehouse worker."""

    host: str
    port: int
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    def endpoint(self) -> str:
        """Return the base URL the workers should call."""
        return "http://{0}:{1}".format(self.host, self.port)


def load_config(env):
    """Build a ServiceConfig from an environment mapping."""
    host = env.get("WAREHOUSE_HOST", "localhost")
    port = int(env.get("WAREHOUSE_PORT", "8080"))
    timeout = int(env.get("WAREHOUSE_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS)))
    return ServiceConfig(host=host, port=port, timeout_seconds=timeout)
