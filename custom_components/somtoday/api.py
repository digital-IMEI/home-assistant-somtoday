"""Small asynchronous client for the unofficial Somtoday API."""

from __future__ import annotations

import base64
import asyncio
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


class SomtodayAssignmentsError(SomtodayApiError):
    """An incomplete assignment snapshot with privacy-safe failure details."""

    def __init__(self, failures: list[dict[str, Any]]) -> None:
        super().__init__("Assignment sources unavailable")
        self.failures = failures


def assignment_failure(source: str, error: BaseException) -> dict[str, Any]:
    """Classify exceptions without exposing messages, URLs or response bodies."""
    result = {"source": source, "category": "invalid_response"}
    current = error
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ClientResponseError):
            return {"source": source, "category": "http_error", "http_status": current.status}
        if isinstance(current, TimeoutError):
            result["category"] = "timeout"
        elif isinstance(current, ClientError):
            result["category"] = "connection_error"
        elif isinstance(current, SomtodayAuthenticationError):
            result["category"] = "authentication_error"
        current = current.__cause__
    return result


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
        except ClientResponseError as err:
            if err.status in (400, 401, 403):
                raise SomtodayAuthenticationError("Somtoday rejected the login") from err
            raise SomtodayApiError("Somtoday token service unavailable") from err
        except (ClientError, TimeoutError, ValueError) as err:
            raise SomtodayApiError("Somtoday token service unavailable") from err
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
        return await self._get_all("/rest/v1/leerlingen")

    async def holidays(self, student_id: str) -> list[dict[str, Any]]:
        """Fetch published holidays; an inaccessible endpoint is not an empty list."""
        from urllib.parse import quote
        return await self._get_all("/rest/v1/vakanties/leerling/" + quote(student_id, safe=""))

    async def assessments(
        self, student_id: str, start: date
    ) -> list[dict[str, Any]]:
        """Fetch test and homework assignments from all three assignment scopes."""
        common = [
            ("begintNaOfOp", start.isoformat()),
            ("geenDifferentiatieOfGedifferentieerdVoorLeerling", student_id),
            ("additional", "swigemaaktVinkjes"),
            ("additional", "huiswerkgemaakt"),
            ("additional", "lesgroep"),
        ]
        sources = (
            ("appointment", "/rest/v1/studiewijzeritemafspraaktoekenningen"),
            ("day", "/rest/v1/studiewijzeritemdagtoekenningen"),
            ("week", "/rest/v1/studiewijzeritemweektoekenningen"),
        )
        await self.ensure_token()
        pages = await asyncio.gather(
            *(self._get_all(path, params=common) for _, path in sources),
            return_exceptions=True,
        )
        failures = []
        for (kind, _), page in zip(sources, pages, strict=True):
            if isinstance(page, SomtodayApiError):
                failures.append(assignment_failure(kind, page))
            elif isinstance(page, BaseException):
                raise page
        if failures:
            # Never pass partial snapshots to synchronizers: missing items could
            # otherwise be mistaken for deleted homework or tests.
            raise SomtodayAssignmentsError(failures)
        result = []
        for (kind, _), items in zip(sources, pages, strict=True):
            for item in items:
                result.append({**item, "_somtoday_assignment_kind": kind})
        return result

    async def set_homework_done(self, student_id: str, assignment_id: str, made: bool) -> None:
        """Update only the selected pupil's completion flag; never submit work."""
        if not str(student_id).isdecimal() or not str(assignment_id).isdecimal():
            raise SomtodayApiError("Unsupported homework identifiers")
        await self.ensure_token()
        api_url = str(self.token.get("somtoday_api_url", "https://api.somtoday.nl")).rstrip("/")
        body = {
            "leerling": {"links": [{"id": int(student_id), "rel": "self",
                                  "href": f"{api_url}/rest/v1/leerlingen/{student_id}"}]},
            "swiToekenningId": int(assignment_id), "gemaakt": bool(made),
        }
        try:
            async with asyncio.timeout(30):
                response = await self._session.put(
                    f"{api_url}/rest/v1/swigemaakt/cou", json=body,
                    headers={"Authorization": f"Bearer {self.token['access_token']}",
                             "Accept": "application/json"},
                )
                response.raise_for_status()
                response.release()
        except (ClientError, TimeoutError) as err:
            raise SomtodayApiError("Homework completion write failed; check account permission") from err

    async def appointments(self, start: date, end: date) -> list[dict[str, Any]]:
        """Return schedule appointments in the requested date range."""
        return await self._get_all(
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

    async def _get_all(self, path, params=None):
        """Never expose a partial snapshot to calendar reconciliation."""
        result = []
        seen = set()
        for offset in range(0, 10000, 100):
            payload = await self._get(path, params, offset)
            items = payload.get("items")
            if not isinstance(items, list) or any(not isinstance(i, dict) for i in items):
                raise SomtodayApiError("Invalid list response")
            for item in items:
                identifier = str((item.get("links") or [{}])[0].get("id", ""))
                if identifier and identifier in seen:
                    raise SomtodayApiError("Repeated page; refusing incomplete snapshot")
                seen.add(identifier)
            result.extend(items)
            if payload.get("_has_more") is False or ("_has_more" not in payload and len(items) < 100):
                return result
        raise SomtodayApiError("Pagination limit reached; refusing incomplete snapshot")

    async def _get(
        self, path: str, params: list[tuple[str, str]] | None = None, offset: int = 0
    ) -> dict[str, Any]:
        await self.ensure_token()
        api_url = str(self.token.get("somtoday_api_url", "https://api.somtoday.nl"))
        headers = {
            "Authorization": f"Bearer {self.token['access_token']}",
            "Accept": "application/json",
            "Range": f"items={offset}-{offset + 99}",
        }
        try:
            response = await self._session.get(
                f"{api_url.rstrip('/')}{path}", params=params, headers=headers
            )
            response.raise_for_status()
            payload = await response.json(content_type=None)
            content_range = response.headers.get("Content-Range", "")
            if isinstance(payload, dict) and content_range:
                try:
                    page, total = content_range.removeprefix("items ").removeprefix("items=").split("/")
                    if (offset == 0 and total == "0" and payload.get("items") == []
                            and page in {"*", "0-0", "0--1"}):
                        payload["_has_more"] = False
                        return payload
                    first, last = map(int, page.split("-"))
                    if first != offset or last - first + 1 != len(payload.get("items", [])):
                        raise ValueError("Unexpected page range")
                    if total != "*":
                        payload["_has_more"] = last + 1 < int(total)
                        if payload["_has_more"] and len(payload["items"]) != 100:
                            raise ValueError("Server truncated requested page")
                except ValueError as err:
                    raise SomtodayApiError("Invalid pagination; refusing partial snapshot") from err
        except ClientResponseError as err:
            if err.status in (401, 403):
                raise SomtodayAuthenticationError("Somtoday authorization expired") from err
            raise SomtodayApiError(f"Somtoday API returned HTTP {err.status}") from err
        except (ClientError, TimeoutError, ValueError) as err:
            raise SomtodayApiError("Invalid response from Somtoday") from err
        if not isinstance(payload, dict):
            raise SomtodayApiError("Unexpected Somtoday response")
        return payload
