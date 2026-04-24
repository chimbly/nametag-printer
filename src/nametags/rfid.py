import logging
from os import environ
from urllib.parse import urlencode

import keyboard

from .logconf import setup_logging
from .printer import print_name
from .WaApi import WaApiClient
from .DhApi import DhApiClient

setup_logging()

logger = logging.getLogger(__name__)

# WildApricot configuration
# Raises KeyError if not set
WA_CLIENT_ID = environ["WA_CLIENT_ID"]
WA_CLIENT_SECRET = environ["WA_CLIENT_SECRET"]
WA_API_KEY = environ["WA_API_KEY"]

# WildApricot field names
WA_RFID_FIELD = "custom-9894255"
WA_FIRST_NAME_FIELD = "FirstName"
WA_PREFERRED_NAME_FIELD = "custom-17061153"
WA_SECOND_LINE_FIELD = "custom-17703390"

# Deep Harbor configuration
DH_BASE_URL = environ.get("DH_BASE_URL", "")
DH_CLIENT_ID = environ.get("DH_CLIENT_ID", "")
DH_CLIENT_SECRET = environ.get("DH_CLIENT_SECRET", "")

# Globals to cache the API clients
_wa_api_client: WaApiClient | None = None
_wa_contacts_url: str | None = None
_dh_api_client: DhApiClient | None = None


def get_wa_api_client() -> WaApiClient:
    """Get an authenticated WaApiClient instance."""
    global _wa_api_client
    if _wa_api_client is None:
        _wa_api_client = WaApiClient(WA_CLIENT_ID, WA_CLIENT_SECRET)
        _wa_api_client.authenticate_with_apikey(WA_API_KEY)
    return _wa_api_client


def get_wa_contacts_url(api: WaApiClient) -> str:
    """Get the WildApricot contacts URL."""
    global _wa_contacts_url
    if _wa_contacts_url is None:
        accounts = api.execute_request("/v2/accounts/")
        account = accounts[0]
        _wa_contacts_url = next(
            res for res in account.Resources if res.Name == "Contacts"
        ).Url
    return _wa_contacts_url


def lookup_rfid_wa(rfid_tag: str) -> tuple[str | None, str | None]:
    """Lookup the name corresponding to the RFID tag using WildApricot."""
    api = get_wa_api_client()
    contacts_url = get_wa_contacts_url(api)

    # https://gethelp.wildapricot.com/en/articles/502#filtering
    params = {
        "$filter": f"substringof('{WA_RFID_FIELD}', '{rfid_tag}')",
        "$async": "false",
    }
    request = contacts_url[:-1] + "?" + urlencode(params)

    response = api.execute_request(request)

    if not hasattr(response, "Contacts") or len(response.Contacts) != 1:
        logger.warning(f"RFID tag {rfid_tag} not found or multiple matches.")
        return (None, None)

    contact = response.Contacts[0]

    preferred_name = next(
        i for i in contact.FieldValues if i.SystemCode == WA_PREFERRED_NAME_FIELD
    ).Value
    first_name = next(
        i for i in contact.FieldValues if i.SystemCode == WA_FIRST_NAME_FIELD
    ).Value
    second_line = next(
        i for i in contact.FieldValues if i.SystemCode == WA_SECOND_LINE_FIELD
    ).Value

    first_line = None
    if first_name:
        first_line = first_name
    if preferred_name:
        first_line = preferred_name

    if not first_line:
        logger.warning(
            f"No name on record for member with RFID tag {rfid_tag} in WildApricot."
        )

    return (first_line, second_line)


def get_dh_api_client() -> DhApiClient:
    """Get an authenticated DhApiClient instance."""
    global _dh_api_client
    if _dh_api_client is None:
        _dh_api_client = DhApiClient(DH_BASE_URL, DH_CLIENT_ID, DH_CLIENT_SECRET)
    return _dh_api_client


def lookup_rfid_dh(rfid_tag: str) -> tuple[str | None, str | None]:
    """Lookup the name corresponding to the RFID tag using Deep Harbor."""
    api = get_dh_api_client()
    members = api.search_by_rfid_tag(rfid_tag)

    if not members or len(members) != 1:
        logger.warning(
            f"RFID tag {rfid_tag} not found or multiple matches in Deep Harbor."
        )
        return (None, None)

    member = members[0]

    # First line: nickname if set, otherwise first_name
    nickname = member.get("nickname")
    first_name = member.get("first_name")
    first_line = nickname if nickname else first_name

    # Second line: pronouns and/or nametag_subtitle
    pronouns = member.get("pronouns")
    subtitle = member.get("nametag_subtitle")

    if pronouns and subtitle:
        second_line = f"{pronouns} - {subtitle}"
    elif pronouns:
        second_line = pronouns
    elif subtitle:
        second_line = subtitle
    else:
        second_line = None

    if not first_line:
        logger.warning(
            f"No name on record for member with RFID tag {rfid_tag} in Deep Harbor."
        )

    return (first_line, second_line)


def lookup_rfid(rfid_tag: str) -> tuple[str | None, str | None]:
    """Lookup the name corresponding to the RFID tag."""
    # Use Deep Harbor as the default lookup service
    return lookup_rfid_dh(rfid_tag)


def listen_for_rfid():
    """Listen for RFID inputs via the keyboard."""
    logger.info("Listening for RFID scans...")
    buffer = ""
    while True:
        event = keyboard.read_event()
        if event.event_type == "down":  # Only process key press events
            char = event.name
            if char == "enter":  # Linebreak indicates end of RFID input
                if len(buffer) == 10 and buffer.isdigit():
                    logger.info(f"RFID Tag Detected: {buffer}")
                    (first_line, second_line) = lookup_rfid(buffer)
                    if first_line:
                        logger.info(f"Matched Name: {first_line}")
                        print_name(first_line, second_line)
                buffer = ""  # Clear the buffer after processing
            elif char.isdigit():  # Append digits to the buffer
                buffer += char
                buffer = buffer[-10:]
                logger.debug(f"Buffer: {buffer}")


if __name__ == "__main__":
    listen_for_rfid()
