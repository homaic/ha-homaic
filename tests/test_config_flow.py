"""Sign in with Homaic: register a client, then the code flow with PKCE."""

from __future__ import annotations

from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest

from homeassistant import config_entries
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.setup import async_setup_component

from custom_components.homaic.config_flow import user_of
from custom_components.homaic.const import AUTHORIZE_URL, CONF_OFFERED, DOMAIN, REGISTER_URL, TOKEN_URL

from .conftest import CLIENT_ID, CLIENT_SECRET, USER, jwt_for

MY_REDIRECT = "https://my.home-assistant.io/redirect/oauth"


@pytest.fixture(autouse=True)
async def callback_view(hass: HomeAssistant) -> None:
    """`auth` serves the callback (in a real install `my` brings it, via the frontend)."""
    assert await async_setup_component(hass, "auth", {})


def register_ok(aioclient_mock, client_id=CLIENT_ID, secret=CLIENT_SECRET):
    aioclient_mock.post(
        REGISTER_URL,
        json={
            "client_id": client_id,
            "client_secret": secret,
            "token_endpoint_auth_method": "client_secret_post",
        },
    )


async def sign_in(hass, hass_client_no_auth, aioclient_mock, result, sub=USER):
    """Follow the external step: Homaic answers the callback, then the token."""
    url = urlparse(result["url"])
    query = parse_qs(url.query)
    state = config_entry_oauth2_flow._encode_jwt(
        hass, {"flow_id": result["flow_id"], "redirect_uri": query["redirect_uri"][0]}
    )
    client = await hass_client_no_auth()
    resp = await client.get(f"/auth/external/callback?code=the-code&state={state}")
    assert resp.status == 200
    aioclient_mock.post(
        TOKEN_URL,
        json={
            "access_token": jwt_for(sub),
            "refresh_token": "new-refresh",
            "token_type": "Bearer",
            "expires_in": 3600,
        },
    )
    with patch("custom_components.homaic.async_setup_entry", return_value=True):
        return await hass.config_entries.flow.async_configure(result["flow_id"])


@pytest.mark.usefixtures("current_request_with_host")
async def test_sign_in(hass: HomeAssistant, hass_client_no_auth, aioclient_mock) -> None:
    register_ok(aioclient_mock)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.EXTERNAL_STEP

    # the client was registered for Home Assistant's own redirect, both grants
    method, url, body, _ = aioclient_mock.mock_calls[0]
    assert (method, str(url)) == ("POST", REGISTER_URL)
    assert body == {
        "client_name": "Home Assistant",
        "redirect_uris": [MY_REDIRECT],
        "grant_types": ["authorization_code", "refresh_token"],
    }

    authorize = urlparse(result["url"])
    query = parse_qs(authorize.query)
    assert f"{authorize.scheme}://{authorize.netloc}{authorize.path}" == AUTHORIZE_URL
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == [MY_REDIRECT]
    assert query["code_challenge_method"] == ["S256"]
    assert len(query["code_challenge"][0]) == 43
    assert "client_secret" not in query

    result = await sign_in(hass, hass_client_no_auth, aioclient_mock, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Homaic"
    assert result["result"].unique_id == USER
    data = result["data"]
    assert data[CONF_CLIENT_ID] == CLIENT_ID
    assert data[CONF_CLIENT_SECRET] == CLIENT_SECRET
    assert data[CONF_OFFERED] is False
    assert data["token"]["refresh_token"] == "new-refresh"

    # the token request carried the secret (client_secret_post) and the verifier
    token_call = aioclient_mock.mock_calls[-1]
    assert str(token_call[1]) == TOKEN_URL
    assert token_call[2]["client_secret"] == CLIENT_SECRET
    assert token_call[2]["client_id"] == CLIENT_ID
    assert len(token_call[2]["code_verifier"]) == 128


@pytest.mark.usefixtures("current_request_with_host")
@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        ({"status": 400, "json": {"error": "invalid_redirect_uri"}}, "cannot_register"),
        ({"json": {"client_id": CLIENT_ID}}, "cannot_register"),
        ({"json": ["not", "a", "client"]}, "cannot_register"),
        ({"exc": TimeoutError()}, "cannot_connect"),
    ],
)
async def test_register_refused(hass: HomeAssistant, aioclient_mock, answer, reason) -> None:
    aioclient_mock.post(REGISTER_URL, **answer)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason


@pytest.mark.usefixtures("current_request_with_host")
async def test_one_entry_only(hass: HomeAssistant, config_entry, aioclient_mock) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
    assert aioclient_mock.call_count == 0


@pytest.mark.usefixtures("current_request_with_host")
async def test_reauth_same_account(hass: HomeAssistant, config_entry, hass_client_no_auth, aioclient_mock) -> None:
    register_ok(aioclient_mock, client_id="dcr.second.sig", secret="second-secret")
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.EXTERNAL_STEP
    result = await sign_in(hass, hass_client_no_auth, aioclient_mock, result)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_CLIENT_ID] == "dcr.second.sig"
    assert config_entry.data[CONF_CLIENT_SECRET] == "second-secret"
    assert config_entry.data["token"]["refresh_token"] == "new-refresh"
    # a reauth never sends again on its own
    assert config_entry.data[CONF_OFFERED] is True


@pytest.mark.usefixtures("current_request_with_host")
async def test_reauth_other_account(hass: HomeAssistant, config_entry, hass_client_no_auth, aioclient_mock) -> None:
    register_ok(aioclient_mock, client_id="dcr.second.sig", secret="second-secret")
    result = await config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await sign_in(hass, hass_client_no_auth, aioclient_mock, result, sub="someone-else")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert config_entry.data[CONF_CLIENT_ID] == CLIENT_ID
    assert config_entry.data[CONF_CLIENT_SECRET] == CLIENT_SECRET


@pytest.mark.usefixtures("current_request_with_host")
async def test_token_without_a_user(hass: HomeAssistant, hass_client_no_auth, aioclient_mock) -> None:
    register_ok(aioclient_mock)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await sign_in(hass, hass_client_no_auth, aioclient_mock, result, sub="")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "oauth_error"
    assert not hass.config_entries.async_entries(DOMAIN)


def test_user_of() -> None:
    assert user_of(jwt_for(USER)) == USER
    assert user_of(jwt_for("")) is None
    assert user_of("no-dots") is None
    assert user_of("a.!!!.c") is None
    assert user_of("a.WzFd.c") is None  # a JSON list, not claims
