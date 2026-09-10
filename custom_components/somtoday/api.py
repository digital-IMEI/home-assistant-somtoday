"""Small asynchronous client for the unofficial Somtoday API."""

from __future__ import annotations

import base64
from datetime import date
import hashlib
import secrets
import time
from typing import Any
from urllib.parse import urlencode

from aiohttp import ClientError, ClientResponseError, ClientSession

from .const import (
    AUTHORIZE_URL,
    CLIENT_ID,
    ORGANIZATIONS_URL,
    REDIRECT_URI,
    TOKEN_URL,
)


class SomtodayApiError(Exception):
    """Base Somtoday client exception."""


class SomtodayAuthenticationError(SomtodayApiError):
    """Raised when authentication or token refresh fails."""


def generate_pkce() -> tuple[str, str]:
    """Return a PKCE verifier and S256 challenge."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def build_authorize_url(
    tenant_uuid: str,
    challenge: str,
    state: str,
) -> str:
    """Build the Somtoday SSO authorization URL."""
    params = {
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "tenant_uuid": tenant_uuid,
        "state": state,
        "session": "no_session",
        "scope": "openid",
        "client_id": CLIENT_ID,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


class SomtodayClient:
    """Async Somtoday client using Home Assistant's shared HTTP session."""

    def __init__(self, session: ClientSession, token: dict[str, Any] | None = None) -> None:
        self._session = session
        self.token = token or {}

    async def organizations(self) -> list[dict[str, Any]]:
        """Fetch all Somtoday organizations."""
        try:
            response = await self._session.get(ORGANIZATIONS_URL)
            response.raise_for_status()
            payload = await response.json(content_type=None)
        except (ClientError, TimeoutError, ValueError) as err:
            raise SomtodayApiError("Could not fetch Somtoday organizations") from err

        if isinstance(payload, list) and payload:
            payload = payload[0]
        organizations = payload.get("instellingen", []) if isinstance(payload, dict) else []
        return [item for item in organizations if isinstance(item, dict)]

    async def exchange_code(self, code: str, verifier: str) -> dict[str, Any]:
        """Exchange an SSO authorization code for tokens."""
        data = {
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
            "code": code,
            "scope": "openid",
            "client_id": CLIENT_ID,
        }
        self.token = await self._token_request(data)
        return self.token

    async def refresh(self) -> dict[str, Any]:
        """Refresh the access token."""
        refresh_token = self.token.get("refresh_token")
        if not refresh_token:
            raise SomtodayAuthenticationError("No refresh token available")
        self.token = await self._token_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "openid",
                "client_id": CLIENT_ID,
            }
        )
        return self.token

    async def _token_request(self, data: dict[str, str]) -> dict[str, Any]:
        try:
            response = await self._session.post(TOKEN_URL, data=data)
            response.raise_for_status()
            token = await response.json(content_type=None)
        except (ClientError, TimeoutError, ValueError) as err:
            raise SomtodayAuthenticationError("Somtoday rejected the login") from err
        if not isinstance(token, dict) or not token.get("access_token"):
            raise SomtodayAuthenticationError("Somtoday returned no access token")
        token["expires_at"] = int(time.time()) + int(token.get("expires_in", 3600))
        return token

    async def ensure_token(self) -> None:
        """Refresh shortly before expiry."""
        if int(self.token.get("expires_at", 0)) <= int(time.time()) + 60:
            await self.refresh()

    async def students(self) -> list[dict[str, Any]]:
        """Return students visible to the account."""
        payload = await self._get("/rest/v1/leerlingen")
        return payload.get("items", [])

    async def appointments(self, start: date, end: date) -> list[dict[str, Any]]:
        """Return schedule appointments in the requested date range."""
        payload = await self._get(
            "/rest/v1/afspraken",
            params=[
                ("sort", "asc-beginDatumTijd"),
                ("additional", "vak"),
                ("additional", "docentAfkortingen"),
                ("additional", "leerlingen"),
                ("begindatum", start.isoformat()),
                ("einddatum", end.isoformat()),
            ],
        )
        return payload.get("items", [])

    async def _get(
        self, path: str, params: list[tuple[str, str]] | None = None
    ) -> dict[str, Any]:
        await self.ensure_token()
        api_url = str(self.token.get("somtoday_api_url", "https://api.somtoday.nl"))
        headers = {
            "Authorization": f"Bearer {self.token['access_token']}",
            "Accept": "application/json",
        }
        try:
            response = await self._session.get(
                f"{api_url.rstrip('/')}{path}", params=params, headers=headers
            )
            response.raise_for_status()
            payload = await response.json(content_type=None)
        except ClientResponseError as err:
            if err.status in (401, 403):
                raise SomtodayAuthenticationError("Somtoday authorization expired") from err
            raise SomtodayApiError(f"Somtoday API returned HTTP {err.status}") from err
        except (ClientError, TimeoutError, ValueError) as err:
            raise SomtodayApiError("Invalid response from Somtoday") from err
        if not isinstance(payload, dict):
            raise SomtodayApiError("Unexpected Somtoday response")
        return payload
