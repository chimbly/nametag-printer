from io import BytesIO
from types import SimpleNamespace
from unittest import TestCase, skipUnless
from unittest.mock import patch

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

try:
    from nametags import printer
except ImportError:  # pragma: no cover
    printer = None


class _FakeWandImage:
    def __init__(self, *args, **kwargs):
        self.format = "png"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def resize(self, width, height):
        return None

    def make_blob(self, fmt):
        img = Image.new("RGBA", (10, 10), (255, 255, 255, 0))
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()


@skipUnless(Image is not None and printer is not None, "Pillow/project deps not installed")
class TestPrinterUnicode(TestCase):
    def _label(self):
        return SimpleNamespace(identifier=printer.LABEL_SIZE, dots_printable=(696, 1109))

    def test_make_image_handles_mixed_unicode_without_crashing(self):
        with (
            patch("nametags.printer.LabelsManager") as labels_manager,
            patch("nametags.printer.WandImage", _FakeWandImage),
        ):
            labels_manager.return_value.iter_elements.return_value = [self._label()]
            image = printer.make_image("Jos\u00e9 \u0645\u0631\u062d\u0628\u0627 \U0001f469\u200d\U0001f4bb", "\u05e9\u05dc\u05d5\u05dd \u0928\u092e\u0938\u094d\u0924\u0947")

        self.assertEqual(image.mode, "RGB")
        self.assertGreater(image.size[0], 0)
        self.assertGreater(image.size[1], 0)

    def test_make_image_silently_drops_unsupported_clusters(self):
        with (
            patch("nametags.printer.LabelsManager") as labels_manager,
            patch("nametags.printer.WandImage", _FakeWandImage),
        ):
            labels_manager.return_value.iter_elements.return_value = [self._label()]
            image = printer.make_image("Name \U0002FA1D", None)

        self.assertEqual(image.mode, "RGB")

    def test_print_name_rotates_before_printing(self):
        test_image = Image.new("RGB", (20, 10), "white")
        with patch("nametags.printer.make_image", return_value=test_image), patch(
            "nametags.printer.print_image"
        ) as mock_print:
            printer.print_name("Test", None)

        printed_image = mock_print.call_args.args[0]
        self.assertEqual(printed_image.size, (10, 20))
