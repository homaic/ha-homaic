"""What Home Assistant sends Homaic: only the fields Homaic reads.

Homaic keeps these as the list's file and reads them with the same code that
reads a pasted-token read. A field Homaic does not read never leaves Home
Assistant: no connections (MAC addresses), no identifiers, no configuration
URLs, no entity ids or names, no config entry titles.
"""

from __future__ import annotations

from typing import Any

from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
)

from .const import KIND_DOMAINS


def _value(v: Any) -> Any:
    """An enum as its string value; anything else as is."""
    return getattr(v, "value", v)


def _device(d: dr.DeviceEntry) -> dict[str, Any]:
    return {
        "id": d.id,
        "name": d.name,
        "name_by_user": d.name_by_user,
        "manufacturer": d.manufacturer,
        "model": d.model,
        "model_id": d.model_id,
        "serial_number": d.serial_number,
        "sw_version": d.sw_version,
        "hw_version": d.hw_version,
        "area_id": d.area_id,
        "via_device_id": d.via_device_id,
        "entry_type": _value(d.entry_type),
        "disabled_by": _value(d.disabled_by),
        "primary_config_entry": d.primary_config_entry,
        "config_entries": sorted(d.config_entries),
    }


def build_payload(hass: HomeAssistant) -> dict[str, Any]:
    """The devices_offer arguments for this Home Assistant."""
    devices = sorted(dr.async_get(hass).devices.values(), key=lambda d: d.id)
    offered = {d.id for d in devices}

    used_entries: set[str] = set()
    for d in devices:
        used_entries.update(d.config_entries)
    entries = [
        {"entry_id": e.entry_id, "domain": e.domain}
        for e in hass.config_entries.async_entries()
        if e.entry_id in used_entries
    ]

    # A device's kind: the domains of its primary entities, as Home
    # Assistant's own list_for_display gives them (an enabled entity, no
    # entity category). A hidden entity still counts.
    kinds: dict[str, set[str]] = {}
    for e in er.async_get(hass).entities.values():
        if e.disabled_by is not None or e.entity_category is not None:
            continue
        if e.device_id not in offered or e.domain not in KIND_DOMAINS:
            continue
        kinds.setdefault(e.device_id, set()).add(e.domain)

    return {
        "ha_version": HA_VERSION,
        "devices": [_device(d) for d in devices],
        "areas": [
            {"area_id": a.id, "name": a.name, "floor_id": a.floor_id}
            for a in ar.async_get(hass).async_list_areas()
        ],
        "floors": [
            {"floor_id": f.floor_id, "name": f.name, "level": f.level}
            for f in fr.async_get(hass).async_list_floors()
        ],
        "entries": entries,
        "kinds": {k: sorted(v) for k, v in sorted(kinds.items())},
    }
