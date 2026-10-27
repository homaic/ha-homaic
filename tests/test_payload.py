"""Only the fields Homaic reads leave Home Assistant."""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
)
from homeassistant.helpers.entity import EntityCategory
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homaic.payload import build_payload

MAC = "aa:bb:cc:dd:ee:ff"
IDENT = "hue-bridge-identifier-0042"
CONFIG_URL = "http://192.168.1.50/setup"
SECRET_TITLE = "owner@example.com hub"


async def house(hass: HomeAssistant) -> dict[str, str]:
    hue = MockConfigEntry(domain="hue", title=SECRET_TITLE)
    hue.add_to_hass(hass)
    unused = MockConfigEntry(domain="unused_thing", title="not referenced")
    unused.add_to_hass(hass)

    ground = fr.async_get(hass).async_create("Ground floor", level=0)
    kitchen = ar.async_get(hass).async_create("Kitchen", floor_id=ground.floor_id)
    ar.async_get(hass).async_create("Shed")

    devs = dr.async_get(hass)
    lamp = devs.async_get_or_create(
        config_entry_id=hue.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, MAC)},
        identifiers={("hue", IDENT)},
        configuration_url=CONFIG_URL,
        name="Hood light",
        manufacturer="Signify",
        model="Hue LCT015",
        model_id="LCT015",
        serial_number="SN-1",
        sw_version="1.2",
        hw_version="B",
        suggested_area="Kitchen",
    )
    devs.async_update_device(lamp.id, area_id=kitchen.id, name_by_user="Hood")
    lock = devs.async_get_or_create(config_entry_id=hue.entry_id, identifiers={("hue", "lock-1")}, name="Front lock")

    ents = er.async_get(hass)
    ents.async_get_or_create("light", "hue", "l1", device_id=lamp.id, original_name="Hood light secret name")
    ents.async_get_or_create("sensor", "hue", "s1", device_id=lamp.id, entity_category=EntityCategory.DIAGNOSTIC)
    ents.async_get_or_create("update", "hue", "u1", device_id=lamp.id)
    ents.async_get_or_create("lock", "hue", "k1", device_id=lock.id, disabled_by=er.RegistryEntryDisabler.USER)
    hidden = ents.async_get_or_create("binary_sensor", "hue", "b1", device_id=lock.id)
    ents.async_update_entity(hidden.entity_id, hidden_by=er.RegistryEntryHider.USER)
    ents.async_get_or_create("switch", "hue", "orphan")
    return {"lamp": lamp.id, "lock": lock.id, "hue": hue.entry_id, "kitchen": kitchen.id, "ground": ground.floor_id}


async def test_only_what_homaic_reads(hass: HomeAssistant) -> None:
    ids = await house(hass)
    p = build_payload(hass)
    wire = json.dumps(p)
    for never in (MAC, IDENT, CONFIG_URL, SECRET_TITLE, "light.hood_light", "secret name", "unused_thing"):
        assert never not in wire, never

    assert set(p) == {"ha_version", "devices", "areas", "floors", "entries", "kinds"}
    lamp = next(d for d in p["devices"] if d["id"] == ids["lamp"])
    assert lamp == {
        "id": ids["lamp"],
        "name": "Hood light",
        "name_by_user": "Hood",
        "manufacturer": "Signify",
        "model": "Hue LCT015",
        "model_id": "LCT015",
        "serial_number": "SN-1",
        "sw_version": "1.2",
        "hw_version": "B",
        "area_id": ids["kitchen"],
        "via_device_id": None,
        "entry_type": None,
        "disabled_by": None,
        "primary_config_entry": ids["hue"],
        "config_entries": [ids["hue"]],
    }
    assert p["entries"] == [{"entry_id": ids["hue"], "domain": "hue"}]
    assert {"area_id": ids["kitchen"], "name": "Kitchen", "floor_id": ids["ground"]} in p["areas"]
    assert p["floors"] == [{"floor_id": ids["ground"], "name": "Ground floor", "level": 0}]


async def test_kinds(hass: HomeAssistant) -> None:
    ids = await house(hass)
    kinds = build_payload(hass)["kinds"]
    # the lamp: its light; never the diagnostic sensor, never update (not a kind)
    # the lock: its hidden binary sensor; never its disabled lock
    # the orphan switch has no device: nothing
    assert kinds == {ids["lamp"]: ["light"], ids["lock"]: ["binary_sensor"]}


async def test_a_disabled_device_is_still_offered(hass: HomeAssistant) -> None:
    ids = await house(hass)
    dr.async_get(hass).async_update_device(ids["lock"], disabled_by=dr.DeviceEntryDisabler.USER)
    lock = next(d for d in build_payload(hass)["devices"] if d["id"] == ids["lock"])
    assert lock["disabled_by"] == "user"


async def test_empty_house(hass: HomeAssistant) -> None:
    p = build_payload(hass)
    assert p["devices"] == [] and p["kinds"] == {} and p["entries"] == []
