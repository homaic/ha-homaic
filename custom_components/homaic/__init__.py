"""Homaic: send this Home Assistant's devices to a Homaic house."""

from __future__ import annotations

import logging
from http import HTTPStatus

from aiohttp import ClientError, ClientResponseError

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.config_entry_oauth2_flow import OAuth2Session, async_register_implementation
from homeassistant.helpers.typing import ConfigType

from .const import CONF_OFFERED, DOMAIN, SERVICE_SEND
from .oauth import implementation
from .send import NOTIFICATION_ID, SendError, async_send

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BUTTON]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type HomaicConfigEntry = ConfigEntry[OAuth2Session]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def send(call: ServiceCall) -> None:
        entries = hass.config_entries.async_loaded_entries(DOMAIN)
        if not entries:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")
        await async_send(hass, entries[0])

    hass.services.async_register(DOMAIN, SERVICE_SEND, send)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HomaicConfigEntry) -> bool:
    impl = implementation(hass, entry.data[CONF_CLIENT_ID], entry.data[CONF_CLIENT_SECRET])
    async_register_implementation(hass, DOMAIN, impl)
    session = OAuth2Session(hass, entry, impl)
    try:
        await session.async_ensure_token_valid()
    except ClientResponseError as err:
        if HTTPStatus.BAD_REQUEST <= err.status < HTTPStatus.INTERNAL_SERVER_ERROR:
            raise ConfigEntryAuthFailed from err
        raise ConfigEntryNotReady from err
    except ClientError as err:
        raise ConfigEntryNotReady from err
    entry.runtime_data = session
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not entry.data.get(CONF_OFFERED):
        # The first send happens on its own, once; after that, the button.
        entry.async_create_background_task(hass, _first_send(hass, entry), f"{DOMAIN} first send")
    return True


async def _first_send(hass: HomeAssistant, entry: HomaicConfigEntry) -> None:
    try:
        await async_send(hass, entry)
    except SendError as err:
        _LOGGER.warning("The first send to Homaic did not go through: %s", err)
        if err.translation_key in ("unreachable", "signed_out"):
            return  # tried again at the next start
        persistent_notification.async_create(hass, str(err), title="Homaic", notification_id=NOTIFICATION_ID)
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_OFFERED: True})


async def async_unload_entry(hass: HomeAssistant, entry: HomaicConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
