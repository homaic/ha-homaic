"""The one control: Send devices to Homaic."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .send import async_send


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([SendButton(entry)])


class SendButton(ButtonEntity):
    """No device of its own, so Homaic never offers itself back to Homaic."""

    _attr_has_entity_name = True
    _attr_translation_key = "send_devices"
    _attr_icon = "mdi:home-import-outline"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_send_devices"

    async def async_press(self) -> None:
        await async_send(self.hass, self._entry)
