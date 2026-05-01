"""
The Brother QL-800 printer seems to go to sleep after a period of inactivity.
This module periodically sends a status request to keep it awake.
"""

import logging
import time

from brother_ql.backends.helpers import status as status_fn

from .logconf import setup_logging
from .printer import get_printer_id

setup_logging()


def keep_printer_awake():
    while True:
        status_fn(
            printer_model="QL-800",
            printer_identifier=get_printer_id(),
            backend_identifier="pyusb",
        )
        time.sleep(300)  # Every 5 minutes


if __name__ == "__main__":
    try:
        keep_printer_awake()
    except KeyboardInterrupt:
        pass
