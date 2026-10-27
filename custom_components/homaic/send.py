"""Send this Home Assistant's devices to Homaic as a list to look over."""

from __future__ import annotations

import asyncio
import json
import logging
from http import HTTPStatus
from typing import Any

from aiohttp import ClientError, ClientResponseError

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import OAuth2Session

from .const import BRING_IN_URL, DOMAIN, MAX_BODY_BYTES, MAX_DEVICES, MCP_URL, TOOL
from .payload import build_payload

_LOGGER = logging.getLogger(__name__)

NOTIFICATION_ID = f"{DOMAIN}_sent"
TIMEOUT_S = 60


class SendError(HomeAssistantError):
    """A send that did not go through, in words a person can act on."""

    def __init__(self, key: str, **placeholders: Any) -> None:
        super().__init__(
            translation_domain=DOMAIN,
            translation_key=key,
            translation_placeholders={k: str(v) for k, v in placeholders.items()} or None,
        )


def body_of(payload: dict[str, Any]) -> bytes:
    """The JSON-RPC call, refused here when Homaic would refuse it."""
    if len(payload["devices"]) > MAX_DEVICES:
        raise SendError("too_many", count=len(payload["devices"]), limit=MAX_DEVICES)
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": TOOL, "arguments": payload},
        },
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    if len(body) > MAX_BODY_BYTES:
        raise SendError("too_big")
    return body


async def async_send(hass: HomeAssistant, entry: ConfigEntry) -> int:
    """Send the devices; return how many Homaic kept. Raises SendError."""
    session: OAuth2Session = entry.runtime_data
    payload = build_payload(hass)
    if not payload["devices"]:
        raise SendError("no_devices")
    body = body_of(payload)

    try:
        await session.async_ensure_token_valid()
    except ClientResponseError as err:
        if HTTPStatus.BAD_REQUEST <= err.status < HTTPStatus.INTERNAL_SERVER_ERROR:
            entry.async_start_reauth(hass)
            raise SendError("signed_out") from err
        raise SendError("unreachable") from err
    except ClientError as err:
        raise SendError("unreachable") from err

    try:
        async with asyncio.timeout(TIMEOUT_S):
            resp = await async_get_clientsession(hass).post(
                MCP_URL,
                data=body,
                headers={
                    "Authorization": f"Bearer {session.token['access_token']}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            status = resp.status
            answer = await resp.json(content_type=None) if status < 300 else None
    except (ClientError, TimeoutError, ValueError) as err:
        raise SendError("unreachable") from err

    if status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
        entry.async_start_reauth(hass)
        raise SendError("signed_out")
    if status == HTTPStatus.TOO_MANY_REQUESTS:
        raise SendError("busy")
    if status == HTTPStatus.REQUEST_ENTITY_TOO_LARGE:
        raise SendError("too_big")
    if status >= 300 or not isinstance(answer, dict):
        raise SendError("unreachable")

    if "error" in answer:
        _LOGGER.warning("Homaic refused the call: %s", answer.get("error"))
        raise SendError("refused")
    result = answer.get("result")
    text = _text_of(result)
    if text is None:
        raise SendError("unreachable")
    if result.get("isError"):
        # Homaic's own sentence: what went wrong and what to do
        raise SendError("homaic_said", message=text)
    try:
        kept = json.loads(text)
        list_id = str(kept["list_id"])
        count = int(kept["devices"])
    except (ValueError, KeyError, TypeError) as err:
        raise SendError("unreachable") from err

    persistent_notification.async_create(
        hass,
        f"[{count} {'device' if count == 1 else 'devices'} to look over]"
        f"({BRING_IN_URL}?list={list_id})",
        title="Homaic",
        notification_id=NOTIFICATION_ID,
    )
    return count


def _text_of(result: Any) -> str | None:
    if not isinstance(result, dict):
        return None
    content = result.get("content")
    if not isinstance(content, list) or not content or not isinstance(content[0], dict):
        return None
    text = content[0].get("text")
    return text if isinstance(text, str) else None
