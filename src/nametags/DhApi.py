"""
This module provides a client for working with the Deep Harbor API.
"""

import datetime
import json
import urllib.error
import urllib.parse
import urllib.request

import jwt


class DhApiClient:
    """Deep Harbor API client."""

    token_endpoint = "/token"
    rfid_search_endpoint = "/v1/member/search_by_rfid_tag/"

    _token: str | None = None
    _token_expiry: datetime.datetime | None = None
    base_url: str
    client_id: str
    client_secret: str

    def __init__(self, base_url: str, client_id: str, client_secret: str):
        self.base_url = base_url
        self.client_id = client_id
        self.client_secret = client_secret

    def get_token(self) -> str:
        """
        Get a valid access token, refreshing if necessary.

        Refreshes token if:
        - No current token exists
        - Current token has expired
        - Current token will expire in the next 60 seconds
        """
        now = datetime.datetime.now(datetime.timezone.utc)

        if (
            self._token is None
            or self._token_expiry is None
            or now > self._token_expiry - datetime.timedelta(seconds=60)
        ):
            self._authenticate()
            assert self._token is not None

        assert self._token is not None

        # Need to get a new token
        return self._token

    def _authenticate(self):
        """Perform authentication and store the token."""
        url = self.base_url + self.token_endpoint
        data = {
            "username": self.client_id,
            "password": self.client_secret,
        }
        encoded_data = urllib.parse.urlencode(data).encode()
        request = urllib.request.Request(url, encoded_data, method="POST")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")

        response = urllib.request.urlopen(request)
        response_data = json.loads(response.read().decode())

        access_token: str = response_data["access_token"]
        self._token = access_token

        # Decode the JWT to get expiration time
        # We don't verify the signature since we just received it from the server
        decoded = jwt.decode(access_token, options={"verify_signature": False})
        exp_timestamp = decoded.get("exp")
        if exp_timestamp:
            self._token_expiry = datetime.datetime.fromtimestamp(
                exp_timestamp, tz=datetime.timezone.utc
            )
        else:
            # If no exp claim, assume token is valid for 1 hour
            self._token_expiry = datetime.datetime.now(
                datetime.timezone.utc
            ) + datetime.timedelta(hours=1)

    def search_by_rfid_tag(self, rfid_tag: str) -> list[dict] | None:
        """
        Search for a member by RFID tag.

        Returns the list of matching members as dicts, or None on error.
        """
        token = self.get_token()
        url = self.base_url + self.rfid_search_endpoint
        params = {"rfid_tag": rfid_tag}
        full_url = url + "?" + urllib.parse.urlencode(params)

        request = urllib.request.Request(full_url, method="GET")
        request.add_header("Authorization", "Bearer " + token)
        request.add_header("Accept", "application/json")

        try:
            response = urllib.request.urlopen(request)
            response_data = json.loads(response.read().decode())
            return response_data
        except urllib.error.HTTPError:
            return None
