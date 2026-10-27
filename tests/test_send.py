"""Sending: the call Homaic gets, and every answer it can give."""

from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homaic.const import BRING_IN_URL, CONF_OFFERED, DOMAIN, MCP_URL, TOKEN_URL
from custom_components.homaic.diagnostics import async_get_config_entry_diagnostics
from custom_components.homaic.send import SendError, async_send

from .conftest import CLIENT_SECRET, REFRESH

LIST_ID = "5f0c3a43-0000-4000-8000-00000000abcd"


def kept(n: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps({"list_id": LIST_ID, "devices": n})}]}}


def refused(text: str) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": text}], "isError": True}}


def a_device(hass: HomeAssistant, n: int = 1) -> None:
    hub = MockConfigEntry(domain="hue")
    hub.add_to_hass(hass)
    for i in range(n):
        dr.async_get(hass).async_get_or_create(config_entry_id=hub.entry_id, identifiers={("hue", f"d{i}")}, name=f"Lamp {i}")


async def set_up(hass: HomeAssistant, entry) -> None:
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_send(hass: HomeAssistant, config_entry, aioclient_mock, no_first_send) -> None:
    a_device(hass)
    await set_up(hass, config_entry)
    aioclient_mock.post(MCP_URL, json=kept(1))
    assert await async_send(hass, config_entry) == 1

    _, url, body, headers = aioclient_mock.mock_calls[-1]
    assert str(url) == MCP_URL
    assert headers["Authorization"] == f"Bearer {config_entry.data['token']['access_token']}"
    call = json.loads(body)
    assert call["method"] == "tools/call"
    assert call["params"]["name"] == "devices_offer"
    assert [d["name"] for d in call["params"]["arguments"]["devices"]] == ["Lamp 0"]
    # nothing but the bearer: the client secret and refresh token stay home
    assert CLIENT_SECRET not in body.decode() and REFRESH not in body.decode()

    shown = persistent_notification._async_get_or_create_notifications(hass)
    msg = shown["homaic_sent"]["message"]
    assert msg == f"[1 device to look over]({BRING_IN_URL}?list={LIST_ID})"
    assert "—" not in msg


@pytest.mark.parametrize(
    ("answer", "key"),
    [
        ({"json": refused("Homaic could not tell which house. Mark one as your primary house, then send again.")}, "homaic_said"),
        ({"status": 429, "json": {}}, "busy"),
        ({"status": 413, "text": "too large"}, "too_big"),
        ({"status": 500, "text": "oops"}, "unreachable"),
        ({"json": {"jsonrpc": "2.0", "id": 1, "error": {"code": -32001, "message": "insufficient_scope"}}}, "refused"),
        ({"json": {"jsonrpc": "2.0", "id": 1, "result": {"content": []}}}, "unreachable"),
        ({"json": {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"text": "not json"}]}}}, "unreachable"),
        ({"text": "<html>"}, "unreachable"),
        ({"exc": TimeoutError()}, "unreachable"),
    ],
)
async def test_send_answers(hass: HomeAssistant, config_entry, aioclient_mock, no_first_send, answer, key) -> None:
    a_device(hass)
    await set_up(hass, config_entry)
    aioclient_mock.post(MCP_URL, **answer)
    with pytest.raises(SendError) as err:
        await async_send(hass, config_entry)
    assert err.value.translation_key == key
    if key == "homaic_said":
        assert err.value.translation_placeholders == {"message": answer["json"]["result"]["content"][0]["text"]}


async def test_signed_out_starts_reauth(hass: HomeAssistant, config_entry, aioclient_mock, no_first_send) -> None:
    a_device(hass)
    await set_up(hass, config_entry)
    aioclient_mock.post(MCP_URL, status=401, json={})
    with pytest.raises(SendError) as err:
        await async_send(hass, config_entry)
    assert err.value.translation_key == "signed_out"
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_refresh_refused_starts_reauth(hass: HomeAssistant, config_entry, aioclient_mock, no_first_send) -> None:
    a_device(hass)
    await set_up(hass, config_entry)
    token = {**config_entry.data["token"], "expires_at": time.time() - 10}
    hass.config_entries.async_update_entry(config_entry, data={**config_entry.data, "token": token})
    aioclient_mock.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})
    with pytest.raises(SendError) as err:
        await async_send(hass, config_entry)
    assert err.value.translation_key == "signed_out"
    assert not [c for c in aioclient_mock.mock_calls if str(c[1]) == MCP_URL]
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN)


async def test_too_many_is_refused_before_sending(hass: HomeAssistant, config_entry, aioclient_mock, no_first_send) -> None:
    a_device(hass, 3)
    await set_up(hass, config_entry)
    with patch("custom_components.homaic.send.MAX_DEVICES", 2), pytest.raises(SendError) as err:
        await async_send(hass, config_entry)
    assert err.value.translation_key == "too_many"
    assert err.value.translation_placeholders == {"count": "3", "limit": "2"}
    assert aioclient_mock.call_count == 0


async def test_too_big_is_refused_before_sending(hass: HomeAssistant, config_entry, aioclient_mock, no_first_send) -> None:
    a_device(hass, 3)
    await set_up(hass, config_entry)
    with patch("custom_components.homaic.send.MAX_BODY_BYTES", 200), pytest.raises(SendError) as err:
        await async_send(hass, config_entry)
    assert err.value.translation_key == "too_big"
    assert aioclient_mock.call_count == 0


async def test_no_devices(hass: HomeAssistant, config_entry, aioclient_mock, no_first_send) -> None:
    await set_up(hass, config_entry)
    with pytest.raises(SendError) as err:
        await async_send(hass, config_entry)
    assert err.value.translation_key == "no_devices"
    assert aioclient_mock.call_count == 0


async def test_button_and_action_send(hass: HomeAssistant, config_entry, aioclient_mock, no_first_send) -> None:
    a_device(hass)
    await set_up(hass, config_entry)
    aioclient_mock.post(MCP_URL, json=kept(1))
    button = er.async_get(hass).async_get_entity_id("button", DOMAIN, f"{config_entry.entry_id}_send_devices")
    assert button == "button.send_devices_to_homaic"
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    await hass.services.async_call(DOMAIN, "send_devices", {}, blocking=True)
    assert len([c for c in aioclient_mock.mock_calls if str(c[1]) == MCP_URL]) == 2
    # the button has no device, so Homaic is never among what it sends
    assert dr.async_get(hass).devices.get_devices_for_config_entry_id(config_entry.entry_id) == []


async def test_first_send_once(hass: HomeAssistant, config_entry, aioclient_mock) -> None:
    hass.config_entries.async_update_entry(config_entry, data={**config_entry.data, CONF_OFFERED: False})
    a_device(hass)
    aioclient_mock.post(MCP_URL, json=kept(1))
    await set_up(hass, config_entry)
    assert config_entry.data[CONF_OFFERED] is True
    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert len([c for c in aioclient_mock.mock_calls if str(c[1]) == MCP_URL]) == 1


async def test_first_send_unreachable_tries_at_next_start(hass: HomeAssistant, config_entry, aioclient_mock) -> None:
    hass.config_entries.async_update_entry(config_entry, data={**config_entry.data, CONF_OFFERED: False})
    a_device(hass)
    aioclient_mock.post(MCP_URL, exc=TimeoutError())
    await set_up(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.data[CONF_OFFERED] is False


async def test_first_send_refused_is_shown_once(hass: HomeAssistant, config_entry, aioclient_mock) -> None:
    hass.config_entries.async_update_entry(config_entry, data={**config_entry.data, CONF_OFFERED: False})
    a_device(hass)
    aioclient_mock.post(MCP_URL, json=refused("That is 10 sends today. Send again tomorrow."))
    await set_up(hass, config_entry)
    assert config_entry.data[CONF_OFFERED] is True
    shown = persistent_notification._async_get_or_create_notifications(hass)
    assert shown["homaic_sent"]["message"] == "That is 10 sends today. Send again tomorrow."


@pytest.mark.parametrize("status", [400, 401])
async def test_setup_refresh_refused_asks_for_sign_in(hass: HomeAssistant, config_entry, aioclient_mock, status) -> None:
    token = {**config_entry.data["token"], "expires_at": time.time() - 10}
    hass.config_entries.async_update_entry(config_entry, data={**config_entry.data, "token": token})
    aioclient_mock.post(TOKEN_URL, status=status, json={"error": "invalid_grant"})
    await set_up(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN)


async def test_setup_homaic_down_retries(hass: HomeAssistant, config_entry, aioclient_mock) -> None:
    token = {**config_entry.data["token"], "expires_at": time.time() - 10}
    hass.config_entries.async_update_entry(config_entry, data={**config_entry.data, "token": token})
    aioclient_mock.post(TOKEN_URL, status=503, text="down")
    await set_up(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_diagnostics_carry_no_secret(hass: HomeAssistant, config_entry, no_first_send) -> None:
    a_device(hass, 2)
    await set_up(hass, config_entry)
    diag = await async_get_config_entry_diagnostics(hass, config_entry)
    wire = json.dumps(diag)
    for secret in (config_entry.data["token"]["access_token"], REFRESH, CLIENT_SECRET, config_entry.data["client_id"], "Lamp 0"):
        assert secret not in wire
    assert diag["would_send"]["devices"] == 2
    assert diag["signed_in"] is True and diag["has_client"] is True
