"""The daily renewal: a quiet house stays signed in."""

from __future__ import annotations

import time
from datetime import timedelta

import pytest
from aiohttp import ClientError

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.homaic import RENEW
from custom_components.homaic.const import DOMAIN, MCP_URL, TOKEN_URL

from .conftest import REFRESH, jwt_for, USER

NEW_REFRESH = "refresh-sentinel-renewed"


def token_calls(aioclient_mock) -> list:
    return [c for c in aioclient_mock.mock_calls if str(c[1]) == TOKEN_URL]


async def a_day_passes(hass: HomeAssistant, config_entry, days: int = 1) -> None:
    """The access token from setup has long run out; a day goes by with nothing sent."""
    token = {**config_entry.data["token"], "expires_at": time.time() - 10}
    hass.config_entries.async_update_entry(config_entry, data={**config_entry.data, "token": token})
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(days=days, seconds=1))
    await hass.async_block_till_done()


async def set_up(hass: HomeAssistant, entry) -> None:
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_renews_once_a_day(hass: HomeAssistant, config_entry, aioclient_mock, no_first_send) -> None:
    assert RENEW == timedelta(days=1)
    aioclient_mock.post(TOKEN_URL, json={"access_token": jwt_for(USER, "renewed"), "refresh_token": NEW_REFRESH, "token_type": "Bearer", "expires_in": 3600})
    await set_up(hass, config_entry)
    assert token_calls(aioclient_mock) == []
    await a_day_passes(hass, config_entry)
    calls = token_calls(aioclient_mock)
    assert len(calls) == 1
    assert calls[0][2]["grant_type"] == "refresh_token"
    assert calls[0][2]["refresh_token"] == REFRESH
    assert config_entry.data["token"]["refresh_token"] == NEW_REFRESH
    assert not [c for c in aioclient_mock.mock_calls if str(c[1]) == MCP_URL]


async def test_not_before_a_day(hass: HomeAssistant, config_entry, aioclient_mock, no_first_send) -> None:
    aioclient_mock.post(TOKEN_URL, json={"access_token": jwt_for(USER, "renewed"), "refresh_token": NEW_REFRESH, "token_type": "Bearer", "expires_in": 3600})
    await set_up(hass, config_entry)
    token = {**config_entry.data["token"], "expires_at": time.time() - 10}
    hass.config_entries.async_update_entry(config_entry, data={**config_entry.data, "token": token})
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=23))
    await hass.async_block_till_done()
    assert token_calls(aioclient_mock) == []


async def test_refused_asks_to_sign_in_again(hass: HomeAssistant, config_entry, aioclient_mock, no_first_send) -> None:
    aioclient_mock.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})
    await set_up(hass, config_entry)
    await a_day_passes(hass, config_entry)
    assert len(token_calls(aioclient_mock)) == 1
    assert [f["context"]["source"] for f in hass.config_entries.flow.async_progress_by_handler(DOMAIN)] == ["reauth"]


@pytest.mark.parametrize("answer", [{"status": 503, "text": "down"}, {"exc": ClientError("no route")}], ids=["down", "no-network"])
async def test_unreachable_waits_for_the_next_day(hass: HomeAssistant, config_entry, aioclient_mock, no_first_send, caplog, answer) -> None:
    aioclient_mock.post(TOKEN_URL, **answer)
    await set_up(hass, config_entry)
    await a_day_passes(hass, config_entry)
    assert len(token_calls(aioclient_mock)) == 1
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN) == []
    assert config_entry.state is ConfigEntryState.LOADED
    assert "Homaic did not renew the sign-in" in caplog.text
    assert "Traceback" not in caplog.text


async def test_unload_stops_renewing(hass: HomeAssistant, config_entry, aioclient_mock, no_first_send) -> None:
    aioclient_mock.post(TOKEN_URL, json={"access_token": jwt_for(USER, "renewed"), "refresh_token": NEW_REFRESH, "token_type": "Bearer", "expires_in": 3600})
    await set_up(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await a_day_passes(hass, config_entry)
    assert token_calls(aioclient_mock) == []
