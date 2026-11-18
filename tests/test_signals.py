"""Signals: which readings Homaic hears about, what it is told, and when."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.homaic.const import DOMAIN, MCP_URL
from custom_components.homaic.signals import reading_of

OK = {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps({"kept": 1})}]}}
BATTERY = {"device_class": "battery", "unit_of_measurement": "%"}


def a_device(hass: HomeAssistant, name: str = "Hallway smoke alarm") -> str:
    hub = MockConfigEntry(domain="zha")
    hub.add_to_hass(hass)
    return dr.async_get(hass).async_get_or_create(config_entry_id=hub.entry_id, identifiers={("zha", name)}, name=name).id


def an_entity(hass: HomeAssistant, device_id: str | None, domain: str, uid: str, **kw) -> str:
    return er.async_get(hass).async_get_or_create(domain, "zha", uid, device_id=device_id, **kw).entity_id


def sent(aioclient_mock) -> list[list[dict]]:
    """The signals in each signal_offer call, in order."""
    out = []
    for _, url, body, _ in aioclient_mock.mock_calls:
        if str(url) != MCP_URL:
            continue
        call = json.loads(body)
        if call["params"]["name"] == "signal_offer":
            out.append(call["params"]["arguments"]["signals"])
    return out


async def settle(hass: HomeAssistant, after: timedelta = timedelta(seconds=11)) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + after)
    await hass.async_block_till_done()


async def set_up(hass: HomeAssistant, entry) -> None:
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("domain", "attrs", "state", "kw", "want"),
    [
        ("sensor", BATTERY, "9", {}, ("battery", True, 9)),
        ("sensor", BATTERY, "15", {}, ("battery", True, 15)),
        ("sensor", BATTERY, "30", {}, None),
        ("sensor", BATTERY, "98", {}, ("battery", False, 98)),
        ("sensor", BATTERY, "unavailable", {}, None),
        ("sensor", {"device_class": "battery", "unit_of_measurement": "V"}, "2.1", {}, None),
        ("sensor", {"unit_of_measurement": "%"}, "8", {"translation_key": "filter_life"}, ("filter", True, 8)),
        ("sensor", {"unit_of_measurement": "%"}, "8", {"translation_key": "humidity"}, None),
        ("binary_sensor", {"device_class": "battery"}, "on", {}, ("battery", True, None)),
        ("binary_sensor", {"device_class": "moisture"}, "on", {}, ("water", True, None)),
        ("binary_sensor", {"device_class": "moisture"}, "off", {}, ("water", False, None)),
        ("binary_sensor", {"device_class": "problem"}, "on", {"translation_key": "replace_filter"}, ("filter", True, None)),
        # never a job: the alarm and Home Assistant own these
        ("binary_sensor", {"device_class": "smoke"}, "on", {}, None),
        ("binary_sensor", {"device_class": "carbon_monoxide"}, "on", {}, None),
        ("binary_sensor", {"device_class": "gas"}, "on", {}, None),
        ("binary_sensor", {"device_class": "safety"}, "on", {}, None),
        ("binary_sensor", {"device_class": "door"}, "on", {}, None),
        ("binary_sensor", {"device_class": "motion"}, "on", {}, None),
        ("binary_sensor", {"device_class": "smoke"}, "on", {"translation_key": "filter_smoke"}, None),
        ("lock", {}, "unlocked", {}, None),
    ],
)
async def test_reading_of(hass: HomeAssistant, domain, attrs, state, kw, want) -> None:
    dev = a_device(hass)
    eid = an_entity(hass, dev, domain, "x", **kw)
    hass.states.async_set(eid, state, attrs)
    assert reading_of(er.async_get(hass).async_get(eid), hass.states.get(eid)) == want


async def test_no_device_or_disabled_is_not_watched(hass: HomeAssistant) -> None:
    loose = an_entity(hass, None, "sensor", "loose")
    hass.states.async_set(loose, "5", BATTERY)
    assert reading_of(er.async_get(hass).async_get(loose), hass.states.get(loose)) is None
    off = an_entity(hass, a_device(hass), "sensor", "off", disabled_by=er.RegistryEntryDisabler.USER)
    hass.states.async_set(off, "5", BATTERY)
    assert reading_of(er.async_get(hass).async_get(off), hass.states.get(off)) is None


async def test_battery_low_then_back(hass: HomeAssistant, config_entry, aioclient_mock, no_first_send) -> None:
    dev = a_device(hass)
    # a battery sensor is often a diagnostic entity: it still counts
    eid = an_entity(hass, dev, "sensor", "batt", entity_category=EntityCategory.DIAGNOSTIC, original_name="Hallway smoke alarm Battery")
    hass.states.async_set(eid, "60", BATTERY)
    aioclient_mock.post(MCP_URL, json=OK)
    await set_up(hass, config_entry)
    await settle(hass)
    assert sent(aioclient_mock) == []  # fine, and Homaic was never told otherwise

    hass.states.async_set(eid, "9", BATTERY)
    await settle(hass)
    (first,) = sent(aioclient_mock)
    assert first == [{"device_id": dev, "kind": "battery", "level": 9, "at": hass.states.get(eid).last_changed.isoformat(), "cleared": False}]

    # only the device's number, the kind, the level and when
    body = aioclient_mock.mock_calls[-1][2].decode()
    for never in (eid, "Hallway smoke alarm", "zha", config_entry.data["token"]["refresh_token"]):
        assert never not in body

    hass.states.async_set(eid, "7", BATTERY)
    await settle(hass)
    assert sent(aioclient_mock)[-1][0]["level"] == 7

    # between the lines: nothing
    hass.states.async_set(eid, "40", BATTERY)
    await settle(hass)
    assert len(sent(aioclient_mock)) == 2

    hass.states.async_set(eid, "100", BATTERY)
    await settle(hass)
    assert sent(aioclient_mock)[-1] == [{"device_id": dev, "kind": "battery", "level": 100, "at": hass.states.get(eid).last_changed.isoformat(), "cleared": True}]

    # back and told: a later change says nothing
    hass.states.async_set(eid, "99", BATTERY)
    await settle(hass)
    assert len(sent(aioclient_mock)) == 3


async def test_water_found_then_dry(hass: HomeAssistant, config_entry, aioclient_mock, no_first_send) -> None:
    dev = a_device(hass, "Water heater leak sensor")
    eid = an_entity(hass, dev, "binary_sensor", "leak")
    hass.states.async_set(eid, "off", {"device_class": "moisture"})
    aioclient_mock.post(MCP_URL, json=OK)
    await set_up(hass, config_entry)
    hass.states.async_set(eid, "on", {"device_class": "moisture"})
    await settle(hass)
    hass.states.async_set(eid, "off", {"device_class": "moisture"})
    await settle(hass)
    assert [[(s["kind"], s["level"], s["cleared"]) for s in call] for call in sent(aioclient_mock)] == [
        [("water", None, False)],
        [("water", None, True)],
    ]


async def test_smoke_is_never_sent(hass: HomeAssistant, config_entry, aioclient_mock, no_first_send) -> None:
    dev = a_device(hass)
    eid = an_entity(hass, dev, "binary_sensor", "smoke")
    aioclient_mock.post(MCP_URL, json=OK)
    await set_up(hass, config_entry)
    hass.states.async_set(eid, "on", {"device_class": "smoke"})
    await settle(hass)
    assert aioclient_mock.call_count == 0


async def test_a_burst_goes_as_one_call(hass: HomeAssistant, config_entry, aioclient_mock, no_first_send) -> None:
    devs = [a_device(hass, f"Sensor {i}") for i in range(3)]
    eids = [an_entity(hass, d, "sensor", f"b{i}") for i, d in enumerate(devs)]
    aioclient_mock.post(MCP_URL, json=OK)
    await set_up(hass, config_entry)
    for eid in eids:
        hass.states.async_set(eid, "5", BATTERY)
    await settle(hass)
    (call,) = sent(aioclient_mock)
    assert sorted(s["device_id"] for s in call) == sorted(devs)


async def test_lowest_entity_speaks_for_the_device(hass: HomeAssistant, config_entry, aioclient_mock, no_first_send) -> None:
    dev = a_device(hass, "Front lock")
    a = an_entity(hass, dev, "sensor", "b1")
    b = an_entity(hass, dev, "sensor", "b2")
    aioclient_mock.post(MCP_URL, json=OK)
    await set_up(hass, config_entry)
    hass.states.async_set(a, "12", BATTERY)
    hass.states.async_set(b, "80", BATTERY)
    await settle(hass)
    assert [(s["level"], s["cleared"]) for s in sent(aioclient_mock)[-1]] == [(12, False)]
    # one back is not the device back
    hass.states.async_set(a, "95", BATTERY)
    hass.states.async_set(b, "4", BATTERY)
    await settle(hass)
    assert [(s["level"], s["cleared"]) for s in sent(aioclient_mock)[-1]] == [(4, False)]


async def test_a_failed_send_is_tried_again(hass: HomeAssistant, config_entry, aioclient_mock, no_first_send) -> None:
    dev = a_device(hass)
    eid = an_entity(hass, dev, "sensor", "batt")
    aioclient_mock.post(MCP_URL, status=500, text="down")
    await set_up(hass, config_entry)
    hass.states.async_set(eid, "9", BATTERY)
    await settle(hass)
    assert len(sent(aioclient_mock)) == 1

    aioclient_mock.clear_requests()
    aioclient_mock.post(MCP_URL, json=OK)
    await settle(hass, timedelta(hours=1, seconds=11))
    await settle(hass, timedelta(hours=1, seconds=22))
    assert [s["level"] for s in sent(aioclient_mock)[-1]] == [9]
    # heard: the next hour sends nothing
    n = len(sent(aioclient_mock))
    await settle(hass, timedelta(hours=2, seconds=33))
    await settle(hass, timedelta(hours=2, seconds=44))
    assert len(sent(aioclient_mock)) == n


async def test_what_was_told_survives_a_restart(hass: HomeAssistant, config_entry, aioclient_mock, no_first_send) -> None:
    dev = a_device(hass)
    eid = an_entity(hass, dev, "sensor", "batt")
    aioclient_mock.post(MCP_URL, json=OK)
    await set_up(hass, config_entry)
    hass.states.async_set(eid, "9", BATTERY)
    await settle(hass)
    assert len(sent(aioclient_mock)) == 1
    await settle(hass, timedelta(seconds=30))  # the store's save

    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    await settle(hass, timedelta(seconds=60))
    assert len(sent(aioclient_mock)) == 1


async def test_signed_out_asks_for_sign_in(hass: HomeAssistant, config_entry, aioclient_mock, no_first_send) -> None:
    dev = a_device(hass)
    eid = an_entity(hass, dev, "sensor", "batt")
    aioclient_mock.post(MCP_URL, status=401, json={})
    await set_up(hass, config_entry)
    hass.states.async_set(eid, "9", BATTERY)
    await settle(hass)
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN)


async def test_unload_stops_watching(hass: HomeAssistant, config_entry, aioclient_mock, no_first_send) -> None:
    dev = a_device(hass)
    eid = an_entity(hass, dev, "sensor", "batt")
    aioclient_mock.post(MCP_URL, json=OK)
    await set_up(hass, config_entry)
    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    hass.states.async_set(eid, "9", BATTERY)
    await settle(hass)
    assert aioclient_mock.call_count == 0
