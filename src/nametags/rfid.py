import logging

import keyboard

from .dhservice import search_member_by_rfid_tag
from .logconf import setup_logging
from .printer import print_name

setup_logging()

logger = logging.getLogger(__name__)


def lookup_rfid(rfid_tag: str) -> tuple[str | None, str | None, str | None]:
    """Look up the nametag data for ``rfid_tag`` in deepharbor.

    Returns ``(name, pronouns, second_line)`` where any element may be
    ``None``. ``name`` is the member's ``nickname`` when set, otherwise
    ``first_name``. An unknown tag returns ``(None, None, None)``.
    """
    try:
        member = search_member_by_rfid_tag(rfid_tag)
    except Exception as exc:
        logger.warning(f"DHService lookup failed for RFID tag {rfid_tag}: {exc}")
        return (None, None, None)

    if member is None:
        logger.warning(f"RFID tag {rfid_tag} not found.")
        return (None, None, None)

    name = member.get("nickname") or member.get("first_name")
    pronouns = member.get("pronouns")
    second_line = member.get("nametag_subtitle")

    if not name:
        logger.warning(f"No name on record for member with RFID tag {rfid_tag}.")

    return (name, pronouns, second_line)


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
                    (name, pronouns, second_line) = lookup_rfid(buffer)
                    if name:
                        logger.info(f"Matched Name: {name}")
                        print_name(name, pronouns, second_line)
                buffer = ""  # Clear the buffer after processing
            elif char.isdigit():  # Append digits to the buffer
                buffer += char
                buffer = buffer[-10:]
                logger.debug(f"Buffer: {buffer}")


if __name__ == "__main__":
    listen_for_rfid()
