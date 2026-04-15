"""Client for the deepharbor DHService REST API.

Authenticates via OAuth2 password flow (client_id/client_secret → JWT bearer)
and exposes the single endpoint the nametag printer needs:
``GET /v1/member/search_by_rfid_tag/``.
"""

import json
import logging
from os import environ
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

# Raises KeyError if not set — matches the existing rfid.py import-time pattern
# so misconfiguration fails loudly at startup rather than on the first scan.
DH_BASE_URL = environ["DH_BASE_URL"].rstrip("/")
DH_CLIENT_ID = environ["DH_CLIENT_ID"]
DH_CLIENT_SECRET = environ["DH_CLIENT_SECRET"]

_HTTP_TIMEOUT = 5  # seconds

_token: str | None = None


def _fetch_token() -> str:
    """POST /token and return a fresh access token."""
    body = urlencode({"username": DH_CLIENT_ID, "password": DH_CLIENT_SECRET}).encode()
    request = Request(
        f"{DH_BASE_URL}/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=_HTTP_TIMEOUT) as response:
        payload = json.loads(response.read())
    return payload["access_token"]


def _get_token(force_refresh: bool = False) -> str:
    global _token
    if _token is None or force_refresh:
        _token = _fetch_token()
    return _token


def _authed_get(path: str) -> object:
    """GET a path under DH_BASE_URL with bearer auth; refresh once on 401."""
    def do(token: str) -> object:
        request = Request(
            f"{DH_BASE_URL}{path}",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urlopen(request, timeout=_HTTP_TIMEOUT) as response:
            return json.loads(response.read())

    try:
        return do(_get_token())
    except HTTPError as exc:
        if exc.code == 401:
            return do(_get_token(force_refresh=True))
        raise


def search_member_by_rfid_tag(rfid_tag: str) -> dict | None:
    """Return the first member match for ``rfid_tag``, or ``None`` if unknown."""
    path = f"/v1/member/search_by_rfid_tag/?{urlencode({'rfid_tag': rfid_tag})}"
    matches = _authed_get(path)
    if not isinstance(matches, list) or not matches:
        return None
    if len(matches) > 1:
        logger.warning(f"RFID tag {rfid_tag} matched {len(matches)} members; using the first.")
    return matches[0]
