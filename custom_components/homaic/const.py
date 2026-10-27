"""Constants for the Homaic integration."""

from typing import Final

DOMAIN: Final = "homaic"

ISSUER: Final = "https://app.homaic.io"
REGISTER_URL: Final = f"{ISSUER}/v1/register"
AUTHORIZE_URL: Final = f"{ISSUER}/v1/authorize"
TOKEN_URL: Final = f"{ISSUER}/v1/token"
BRING_IN_URL: Final = f"{ISSUER}/inventory/bring-in"
MCP_URL: Final = "https://mcp.homaic.io/v1/mcp"

# The name Homaic shows on its consent page and under Settings, Your AI.
CLIENT_NAME: Final = "Home Assistant"
TOOL: Final = "devices_offer"

# Homaic's own limits (devices_offer): more is refused there, so it is
# refused here first, never cut.
MAX_DEVICES: Final = 2000
MAX_BODY_BYTES: Final = 1024 * 1024

# The entity domains that name a device's kind. Homaic accepts these and no
# others (apps/mcp-server/lib/ha-kinds.js).
KIND_DOMAINS: Final = frozenset(
    {
        "lock",
        "climate",
        "camera",
        "media_player",
        "fan",
        "light",
        "cover",
        "vacuum",
        "switch",
        "binary_sensor",
        "sensor",
    }
)

CONF_OFFERED: Final = "offered"
SERVICE_SEND: Final = "send_devices"
