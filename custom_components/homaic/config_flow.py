"""Sign in with Homaic."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Mapping
from typing import Any

from aiohttp import ClientError

from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlowResult
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CLIENT_NAME, CONF_OFFERED, DOMAIN, REGISTER_URL
from .oauth import implementation

REGISTER_TIMEOUT_S = 10


def user_of(access_token: str) -> str | None:
    """The Homaic user an access token speaks for (its `sub`), unverified.

    Homaic verifies the token; this only tells two accounts apart."""
    try:
        part = access_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (IndexError, ValueError):
        return None
    sub = claims.get("sub") if isinstance(claims, dict) else None
    return sub if isinstance(sub, str) and sub else None


class OAuth2FlowHandler(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN):
    """Each sign-in registers its own client with Homaic, then signs in."""

    DOMAIN = DOMAIN

    @property
    def logger(self) -> logging.Logger:
        return logging.getLogger(__name__)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        redirect_uri = config_entry_oauth2_flow.async_get_redirect_uri(self.hass)
        try:
            async with asyncio.timeout(REGISTER_TIMEOUT_S):
                resp = await async_get_clientsession(self.hass).post(
                    REGISTER_URL,
                    json={
                        "client_name": CLIENT_NAME,
                        "redirect_uris": [redirect_uri],
                        "grant_types": ["authorization_code", "refresh_token"],
                    },
                )
                if resp.status >= 300:
                    self.logger.warning("Homaic refused the client (%s)", resp.status)
                    return self.async_abort(reason="cannot_register")
                client = await resp.json(content_type=None)
        except (ClientError, TimeoutError, ValueError):
            return self.async_abort(reason="cannot_connect")
        client_id = client.get("client_id") if isinstance(client, dict) else None
        client_secret = client.get("client_secret") if isinstance(client, dict) else None
        if not isinstance(client_id, str) or not isinstance(client_secret, str):
            return self.async_abort(reason="cannot_register")
        self.async_register_implementation(self.hass, implementation(self.hass, client_id, client_secret))
        return await super().async_step_user(user_input)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        user = user_of(data["token"].get("access_token", ""))
        if user is None:
            return self.async_abort(reason="oauth_error")
        await self.async_set_unique_id(user)
        creds = {
            CONF_CLIENT_ID: self.flow_impl.client_id,
            CONF_CLIENT_SECRET: self.flow_impl.client_secret,
        }
        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data_updates={**data, **creds}
            )
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="Homaic", data={**data, **creds, CONF_OFFERED: False})
