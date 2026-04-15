from unittest import TestCase, skipUnless
from unittest.mock import patch

try:
    from nametags.webserver import app
except ImportError:  # pragma: no cover
    app = None


@skipUnless(app is not None, "Web dependencies not installed")
class TestWebserver(TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_post_unicode_name(self):
        with patch("nametags.webserver.print_name") as mock_print_name:
            response = self.client.post(
                "/",
                data={
                    "name": "Jos\u00e9 \u0645\u0631\u062d\u0628\u0627 \U0001f469\u200d\U0001f4bb",
                    "second_line": "\u05e9\u05dc\u05d5\u05dd",
                },
            )

        self.assertEqual(response.status_code, 200)
        mock_print_name.assert_called_once()

    def test_post_invalid_name_rejected(self):
        response = self.client.post("/", data={"name": "\u0000\n", "second_line": "x"})
        self.assertEqual(response.status_code, 400)
