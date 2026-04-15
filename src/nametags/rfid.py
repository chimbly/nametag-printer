import logging
from os import environ
from urllib.parse import urlencode

import keyboard

from .logconf import setup_logging
from .printer import print_name
from .sanitize import safe_log_text, sanitize_label_text
from .WaApi import WaApiClient

setup_logging()

logger = logging.getLogger(__name__)

# Raises KeyError if not set
WA_CLIENT_ID = environ["WA_CLIENT_ID"]
WA_CLIENT_SECRET = environ["WA_CLIENT_SECRET"]
WA_API_KEY = environ["WA_API_KEY"]

# Field names
RFID_FIELD = "custom-9894255"
FIRST_NAME_FIELD = "FirstName"
PREFERRED_NAME_FIELD = "custom-17061153"
SECOND_LINE_FIELD = "custom-17703390"

# Globals to cache the API client and contacts URL
# (API client will refresh the token as needed)
_api_client = None
_contacts_url = None


def get_api_client():
    """Get an authenticated WaApiClient instance."""
    global _api_client
    if _api_client is None:
        _api_client = WaApiClient(WA_CLIENT_ID, WA_CLIENT_SECRET)
        _api_client.authenticate_with_apikey(WA_API_KEY)
    return _api_client


def get_contacts_url(api):
    """Get the contacts URL."""
    global _contacts_url
    if _contacts_url is None:
        accounts = api.execute_request("/v2/accounts/")
        account = accounts[0]
        _contacts_url = next(res for res in account.Resources if res.Name == "Contacts").Url
    return _contacts_url


def lookup_rfid(rfid_tag: str) -> (str | None, str | None):
    """Lookup the name corresponding to the RFID tag."""
    api = get_api_client()
    contacts_url = get_contacts_url(api)

    # https://gethelp.wildapricot.com/en/articles/502#filtering
    params = {"$filter": f"substringof('{RFID_FIELD}', '{rfid_tag}')", "$async": "false"}
    request = contacts_url[:-1] + "?" + urlencode(params)

    response = api.execute_request(request)

    if not hasattr(response, "Contacts") or len(response.Contacts) != 1:
        logger.warning("RFID tag %s not found or multiple matches.", safe_log_text(rfid_tag))
        return (None, None)

    contact = response.Contacts[0]

    preferred_name = next(i for i in contact.FieldValues if i.SystemCode == PREFERRED_NAME_FIELD).Value
    first_name = next(i for i in contact.FieldValues if i.SystemCode == FIRST_NAME_FIELD).Value
    second_line = next(i for i in contact.FieldValues if i.SystemCode == SECOND_LINE_FIELD).Value

    first_line = None
    if first_name:
        first_line = first_name
    if preferred_name:
        first_line = preferred_name

    if not first_line:
        logger.warning(
            "No name on record for member with RFID tag %s.",
            safe_log_text(rfid_tag),
        )

    return (first_line, second_line)


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
                    logger.info("RFID Tag Detected: %s", safe_log_text(buffer))
                    (first_line, second_line) = lookup_rfid(buffer)
                    if first_line:
                        logger.info("Matched Name: %s", safe_log_text(first_line))
                        try:
                            first_line, second_line = sanitize_label_text(first_line, second_line)
                        except ValueError as exc:
                            logger.warning("Skipping invalid label text: %s", exc)
                            continue
                        print_name(first_line, second_line)
                buffer = ""  # Clear the buffer after processing
            elif char.isdigit():  # Append digits to the buffer
                buffer += char
                buffer = buffer[-10:]
                logger.debug("Buffer: %s", safe_log_text(buffer))


if __name__ == "__main__":
    listen_for_rfid()
