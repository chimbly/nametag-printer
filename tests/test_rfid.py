"""
There's really no good way to test this project without actually running it
on hardware (RFID reader and label printer). However, we can test the RFID
lookup function against known RFID values.
"""
from unittest import TestCase
from unittest.mock import patch

from nametags.rfid import lookup_rfid


class TestRfidLookup(TestCase):
    def test_first_name(self):
        # ID: 94877866
        (name, _, _) = lookup_rfid("1111111111")
        self.assertEqual(name, "testy")

    def test_nickname(self):
        # ID: 86867117
        (name, _, _) = lookup_rfid("2222222222")
        self.assertEqual(name, "nickname")


class FakeEvent:
    def __init__(self, name, event_type="down"):
        self.name = name
        self.event_type = event_type


class TestRfidListen(TestCase):
    def test_listen_for_rfid(self):
        # Simulate: invalid short RFID, invalid long RFID, then valid RFID, each followed by 'enter'
        # Short: 5 digits, Long: 12 digits, Valid: 10 digits
        events = (
            [FakeEvent(str(d)) for d in range(1, 6)] + [FakeEvent("enter")]  # short
            + [FakeEvent(str(d % 10)) for d in range(1, 13)] + [FakeEvent("enter")]  # long
            + [FakeEvent(str(d)) for d in range(1, 10)] + [FakeEvent("0")] + [FakeEvent("enter")]  # valid: 1234567890
        )
        event_iter = iter(events)

        def fake_read_event():
            try:
                return next(event_iter)
            except StopIteration:
                raise StopIteration  # Used to break the loop

        def mock_lookup_rfid(rfid_tag):
            # Only return a match for the valid 10-digit RFID
            if rfid_tag == "1234567890":
                return ("Test Name", "they/them", "Test Subtitle")
            return (None, None, None)

        with patch('nametags.rfid.keyboard.read_event', fake_read_event), \
             patch('nametags.rfid.lookup_rfid', side_effect=mock_lookup_rfid), \
             patch('nametags.rfid.print_name') as mock_print_name, \
             patch('nametags.rfid.logger'):
            try:
                from nametags import rfid
                rfid.listen_for_rfid()
            except StopIteration:
                pass
            # Only the valid RFID should trigger print_name
            mock_print_name.assert_called_once_with("Test Name", "they/them", "Test Subtitle")
