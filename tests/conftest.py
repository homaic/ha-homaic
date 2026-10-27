"""Shared fixtures for the Homaic integration's tests."""

from __future__ import annotations

import base64
import json
import time
from unittest.mock import patch

import pytest

from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_component

from custom_components.homaic.const import CONF_OFFERED, DOMAIN

USER = "8b6f2a10-0000-4000-8000-000000000001"
CLIENT_ID = "dcr.eyJuIjoiSG9tZSBBc3Npc3RhbnQifQ.sig"
CLIENT_SECRET = "s3cret-client-value"
ACCESS = "access-sentinel"
REFRESH = "refresh-sentinel-value"


def jwt_for(sub: str, marker: str = ACCESS) -> str:
    """A token shaped like Homaic's: only its `sub` is read here."""
    claims = base64.urlsafe_b64encode(json.dumps({"sub": sub, "typ": "access", "m": marker}).encode())
    return f"eyJhbGciOiJIUzI1NiJ9.{claims.decode().rstrip('=')}.c2ln"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def my_is_set_up(hass):
    """`my` needs the frontend build; marked set up, it still gives the my redirect."""
    mock_component(hass, "my")


@pytest.fixture
def entry_data() -> dict:
    return {
        "auth_implementation": DOMAIN,
        "token": {
            "access_token": jwt_for(USER),
            "refresh_token": REFRESH,
            "token_type": "Bearer",
            "expires_in": 3600,
            "expires_at": time.time() + 3600,
        },
        CONF_CLIENT_ID: CLIENT_ID,
        CONF_CLIENT_SECRET: CLIENT_SECRET,
        CONF_OFFERED: True,
    }


@pytest.fixture
def config_entry(hass, entry_data) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=USER, data=entry_data, title="Homaic")
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def no_first_send():
    with patch("custom_components.homaic._first_send") as first:
        yield first
