"""Diagnostics: counts and settings, never a token, a secret or a device."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.core import HomeAssistant

from .const import CONF_OFFERED
from .payload import build_payload


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    payload = build_payload(hass)
    token = entry.data.get("token") or {}
    return {
        "signed_in": bool(token.get("access_token")),
        "token_expires_at": token.get("expires_at"),
        "has_client": bool(entry.data.get(CONF_CLIENT_ID) and entry.data.get(CONF_CLIENT_SECRET)),
        "offered": bool(entry.data.get(CONF_OFFERED)),
        "would_send": {
            "devices": len(payload["devices"]),
            "areas": len(payload["areas"]),
            "floors": len(payload["floors"]),
            "entries": len(payload["entries"]),
            "kinds": len(payload["kinds"]),
        },
    }
