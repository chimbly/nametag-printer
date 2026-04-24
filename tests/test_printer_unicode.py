from io import BytesIO
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from PIL import Image

from nametags import printer


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


class TestPrinterUnicode(TestCase):
    def _label(self):
        return SimpleNamespace(identifier=printer.LABEL_SIZE, dots_printable=(696, 1109))

    def test_make_image_handles_unicode_text(self):
        with (
            patch("nametags.printer.LabelsManager") as labels_manager,
            patch("nametags.printer.WandImage", _FakeWandImage),
        ):
            labels_manager.return_value.iter_elements.return_value = [self._label()]
            image = printer.make_image(
                "ርሁዪነቿጋ 你好 नमस्ते مرحبا 👩‍💻",
                "Pumping Station One",
            )

        self.assertEqual(image.mode, "RGB")
        self.assertGreater(image.size[0], 0)
        self.assertGreater(image.size[1], 0)
