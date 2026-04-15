"""
There's really no good way to test this project without actually running it
on hardware (RFID reader and label printer). However, we can test the RFID
lookup and listen behavior with mocks.
"""

import os
from unittest import TestCase, skipUnless
from unittest.mock import MagicMock, patch

os.environ.setdefault("WA_CLIENT_ID", "test_client")
os.environ.setdefault("WA_CLIENT_SECRET", "test_secret")
os.environ.setdefault("WA_API_KEY", "test_api_key")

try:
    from nametags import rfid
except ImportError:  # pragma: no cover
    rfid = None


@skipUnless(rfid is not None, "RFID dependencies not installed")
class TestRfidLookup(TestCase):
    def test_returns_preferred_name_and_second_line(self):
        fake_contact = MagicMock()
        fake_contact.FieldValues = [
            MagicMock(SystemCode=rfid.PREFERRED_NAME_FIELD, Value="nickname"),
            MagicMock(SystemCode=rfid.FIRST_NAME_FIELD, Value="testy"),
            MagicMock(SystemCode=rfid.SECOND_LINE_FIELD, Value="she/her"),
        ]
        fake_response = MagicMock(Contacts=[fake_contact])

        with patch("nametags.rfid.get_api_client") as mock_api, patch(
            "nametags.rfid.get_contacts_url", return_value="https://example.org/contacts/"
        ):
            mock_api.return_value.execute_request.return_value = fake_response
            result = rfid.lookup_rfid("1111111111")

        self.assertEqual(result, ("nickname", "she/her"))


class FakeEvent:
    def __init__(self, name, event_type="down"):
        self.name = name
        self.event_type = event_type


@skipUnless(rfid is not None, "RFID dependencies not installed")
class TestRfidListen(TestCase):
    def test_listen_for_rfid(self):
        events = (
            [FakeEvent(str(d)) for d in range(1, 6)]
            + [FakeEvent("enter")]
            + [FakeEvent(str(d % 10)) for d in range(1, 13)]
            + [FakeEvent("enter")]
            + [FakeEvent(str(d)) for d in range(1, 10)]
            + [FakeEvent("0")]
            + [FakeEvent("enter")]
        )
        event_iter = iter(events)

        def fake_read_event():
            try:
                return next(event_iter)
            except StopIteration:
                raise StopIteration

        def mock_lookup_rfid(rfid_tag):
            if rfid_tag == "1234567890":
                return ("Test Name", "she/her")
            return (None, None)

        with patch("nametags.rfid.keyboard.read_event", fake_read_event), patch(
            "nametags.rfid.lookup_rfid", side_effect=mock_lookup_rfid
        ), patch("nametags.rfid.print_name") as mock_print_name, patch("nametags.rfid.logger"):
            try:
                rfid.listen_for_rfid()
            except StopIteration:
                pass

            mock_print_name.assert_called_once_with("Test Name", "she/her")
