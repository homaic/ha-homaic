"""Homaic's OAuth: authorization code with PKCE and a client secret."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.config_entry_oauth2_flow import LocalOAuth2ImplementationWithPkce

from .const import AUTHORIZE_URL, DOMAIN, TOKEN_URL


class HomaicImplementation(LocalOAuth2ImplementationWithPkce):
    """The one way in: Sign in with Homaic."""

    @property
    def name(self) -> str:
        return "Homaic"


def implementation(hass: HomeAssistant, client_id: str, client_secret: str) -> HomaicImplementation:
    return HomaicImplementation(
        hass, DOMAIN, client_id, AUTHORIZE_URL, TOKEN_URL, client_secret=client_secret
    )
