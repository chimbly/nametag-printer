from __future__ import annotations

import logging
from dataclasses import dataclass
from io import BytesIO
from os import environ, path

from brother_ql.backends.helpers import discover, send
from brother_ql.conversion import convert
from brother_ql.labels import LabelsManager
from brother_ql.raster import BrotherQLRaster
from PIL import Image, ImageDraw, ImageFont

from .logconf import setup_logging
from .sanitize import sanitize_label_text, split_graphemes

try:
    import uharfbuzz as hb
except ImportError:  # pragma: no cover
    hb = None

try:
    from wand.color import Color
    from wand.image import Image as WandImage
except ImportError:  # pragma: no cover
    Color = None
    WandImage = None

try:
    from fontTools.ttLib import TTFont
    from fontTools.ttLib.ttCollection import TTCollection
except ImportError:  # pragma: no cover
    TTFont = None
    TTCollection = None

setup_logging()
logger = logging.getLogger(__name__)

# Get the directory of the current script
script_dir = path.dirname(path.abspath(__file__))
asset_dir = path.join(script_dir, "assets")

# Paths to static assets
font_path = path.join(asset_dir, "NotoSans-Regular.ttf")
bold_font_path = path.join(asset_dir, "NotoSans-Bold.ttf")
logo_path = path.join(asset_dir, "ps1-logo-clean-white.svg")

# Optional fallback fonts (best coverage first)
fallback_font_paths = [
    path.join(asset_dir, "Ebrima.ttf"),
    path.join(asset_dir, "msyh.ttc"),
    path.join(asset_dir, "malgun.ttf"),
    path.join(asset_dir, "seguiemj.ttf"),
    path.join(asset_dir, "seguisym.ttf"),
    path.join(asset_dir, "NotoSansArabic-Regular.ttf"),
    path.join(asset_dir, "NotoSansHebrew-Regular.ttf"),
    path.join(asset_dir, "OpenSans-Regular.ttf"),
]

# Make sure required files exist
for asset_path in (logo_path, font_path, bold_font_path):
    if not path.isfile(asset_path):
        raise FileNotFoundError(f"Required asset not found: {asset_path}")

fallback_font_paths = [font for font in fallback_font_paths if path.isfile(font)]

LABEL_SIZE = environ.get("LABEL_SIZE", "62x100")
MIN_NAME_FONT_SIZE = int(environ.get("MIN_NAME_FONT_SIZE", "40"))
MIN_SECOND_LINE_FONT_SIZE = int(environ.get("MIN_SECOND_LINE_FONT_SIZE", "30"))


@dataclass
class RenderRun:
    text: str
    font_path: str


@dataclass
class LineRenderMetrics:
    width: int
    height: int


_CMAP_CACHE: dict[str, set[int]] = {}
_HB_FACE_CACHE: dict[str, hb.Face] = {}


def _get_font(size: int, font_file: str) -> ImageFont.FreeTypeFont:
    # Use RAQM layout engine when available for shaping and bidirectional layout.
    if hasattr(ImageFont, "Layout"):
        try:
            return ImageFont.truetype(
                font_file,
                size=size,
                layout_engine=ImageFont.Layout.RAQM,
            )
        except Exception:
            pass
    return ImageFont.truetype(font_file, size=size)


def _get_supported_codepoints(font_file: str) -> set[int]:
    if TTFont is None:
        return set()

    if font_file in _CMAP_CACHE:
        return _CMAP_CACHE[font_file]

    supported: set[int] = set()
    if font_file.lower().endswith(".ttc") and TTCollection is not None:
        collection = TTCollection(font_file, lazy=True)
        for ttfont in collection.fonts:
            for table in ttfont["cmap"].tables:
                supported.update(table.cmap.keys())
    else:
        ttfont = TTFont(font_file, lazy=True)
        try:
            for table in ttfont["cmap"].tables:
                supported.update(table.cmap.keys())
        finally:
            ttfont.close()

    _CMAP_CACHE[font_file] = supported
    return supported


def _shape_width_harfbuzz(text: str, font_file: str, size: int) -> float | None:
    if hb is None or not text:
        return None

    if font_file not in _HB_FACE_CACHE:
        with open(font_file, "rb") as font_handle:
            _HB_FACE_CACHE[font_file] = hb.Face(font_handle.read())

    face = _HB_FACE_CACHE[font_file]
    hb_font = hb.Font(face)
    hb_font.scale = (size * 64, size * 64)

    buffer = hb.Buffer()
    buffer.add_str(text)
    buffer.guess_segment_properties()
    hb.shape(hb_font, buffer)

    return sum(pos.x_advance for pos in buffer.glyph_positions) / 64.0


def _font_supports_cluster(cluster: str, font_file: str) -> bool:
    codepoints = _get_supported_codepoints(font_file)
    if not codepoints:
        return True

    for char in cluster:
        cp = ord(char)
        if cp in {0x200C, 0x200D, 0xFE0E, 0xFE0F}:
            continue
        if cp not in codepoints:
            return False
    return True


def _split_graphemes(text: str) -> list[str]:
    return split_graphemes(text)


def _build_runs(text: str) -> list[RenderRun]:
    graphemes = _split_graphemes(text)
    candidate_fonts = [font_path, *fallback_font_paths]

    runs: list[RenderRun] = []
    current_font: str | None = None
    current_chars: list[str] = []

    for cluster in graphemes:
        target_font = next(
            (candidate for candidate in candidate_fonts if _font_supports_cluster(cluster, candidate)),
            None,
        )
        if target_font is None:
            logger.debug("Dropping unsupported cluster during render")
            continue

        if current_font != target_font:
            if current_chars and current_font:
                runs.append(RenderRun(text="".join(current_chars), font_path=current_font))
            current_font = target_font
            current_chars = [cluster]
        else:
            current_chars.append(cluster)

    if current_chars and current_font:
        runs.append(RenderRun(text="".join(current_chars), font_path=current_font))

    return runs


def _measure_run(text: str, font: ImageFont.FreeTypeFont, draw: ImageDraw.ImageDraw, font_file: str, size: int) -> int:
    shaped_width = _shape_width_harfbuzz(text, font_file, size)
    if shaped_width is not None:
        return max(0, int(round(shaped_width)))

    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return max(0, right - left)


def _measure_line(text: str, font_size: int, draw: ImageDraw.ImageDraw) -> LineRenderMetrics:
    runs = _build_runs(text)
    if not runs:
        return LineRenderMetrics(width=0, height=0)

    line_width = 0
    max_ascent = 0
    max_descent = 0

    for run in runs:
        run_font = _get_font(font_size, run.font_path)
        line_width += _measure_run(run.text, run_font, draw, run.font_path, font_size)
        ascent, descent = run_font.getmetrics()
        max_ascent = max(max_ascent, ascent)
        max_descent = max(max_descent, descent)

    return LineRenderMetrics(width=line_width, height=max_ascent + max_descent)


def _draw_centered_line(
    draw: ImageDraw.ImageDraw,
    text: str,
    center_x: int,
    baseline_y: int,
    font_size: int,
    fill: str,
) -> LineRenderMetrics:
    runs = _build_runs(text)
    if not runs:
        return LineRenderMetrics(width=0, height=0)

    widths: list[int] = []
    max_ascent = 0
    max_descent = 0

    for run in runs:
        run_font = _get_font(font_size, run.font_path)
        widths.append(_measure_run(run.text, run_font, draw, run.font_path, font_size))
        ascent, descent = run_font.getmetrics()
        max_ascent = max(max_ascent, ascent)
        max_descent = max(max_descent, descent)

    total_width = sum(widths)
    line_height = max_ascent + max_descent
    x = center_x - (total_width // 2)
    y = baseline_y - line_height

    for run, run_width in zip(runs, widths):
        run_font = _get_font(font_size, run.font_path)
        # Rely on RAQM for script shaping and direction handling when available.
        draw.text((x, y), run.text, fill=fill, font=run_font, anchor="lt")
        x += run_width

    return LineRenderMetrics(width=total_width, height=line_height)


def _fit_font_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    start_size: int,
    min_size: int,
    max_width: int,
) -> tuple[int, LineRenderMetrics]:
    size = start_size
    metrics = _measure_line(text, size, draw)

    while size > min_size and metrics.width > max_width:
        size -= 5
        metrics = _measure_line(text, size, draw)

    if metrics.width > max_width:
        logger.warning("Text still exceeds width at minimum font size; clipping may occur")

    return size, metrics


def get_printer_id() -> str:
    """Auto-discover the printer and return its identifier."""
    devices = discover("pyusb")
    if not devices:
        raise RuntimeError("No Brother label printer discovered")

    printer_id = devices[0]["identifier"]

    # Discard broken serial from identifier
    # https://github.com/pklaus/brother_ql_web/issues/10#issuecomment-994990935
    printer_id = printer_id.split("_")[0]

    return printer_id


def print_name(name: str, second_line: str | None):
    """Print a nametag with the given name."""
    image = make_image(name, second_line)
    image = image.rotate(90, expand=True)
    print_image(image)


def print_image(image: Image.Image):
    """Print the given PIL image."""
    qlr = BrotherQLRaster("QL-800")
    qr_data = convert(qlr, [image], LABEL_SIZE)

    try:
        printer_id = get_printer_id()
        send(qr_data, printer_id)
    except Exception as exc:
        logger.exception("Failed to send print job: %s", exc)
        raise RuntimeError("Unable to send print job") from exc


def make_image(name: str, second_line: str | None) -> Image.Image:
    """Generate a nametag image with the given text."""
    name, second_line = sanitize_label_text(name, second_line)

    label = next(
        (
            candidate
            for candidate in LabelsManager().iter_elements()
            if candidate.identifier == LABEL_SIZE
        ),
        None,
    )
    if label is None:
        raise ValueError(
            f"Invalid LABEL_SIZE '{LABEL_SIZE}'. Expected a known Brother QL label identifier."
        )
    image_height, image_width = label.dots_printable

    center_x = image_width // 2

    top_bar_height = 200
    bottom_bar_height = 100

    hello_text_y = 0
    my_name_is_text_y = 115

    logo_size = (100, 100)
    logo_inset = 50

    image = Image.new("RGB", (image_width, image_height), "white")
    draw = ImageDraw.Draw(image)

    font_name_size = 170
    font_second_line_size = 120
    font_hello_size = 100
    font_my_name_is_size = 50

    font_hello = _get_font(font_hello_size, font_path)
    font_my_name_is = _get_font(font_my_name_is_size, bold_font_path)

    font_name_size, name_metrics = _fit_font_size(
        draw,
        name,
        start_size=font_name_size,
        min_size=MIN_NAME_FONT_SIZE,
        max_width=image_width - 100,
    )

    second_line_metrics = LineRenderMetrics(width=0, height=0)
    if second_line:
        font_second_line_size, second_line_metrics = _fit_font_size(
            draw,
            second_line,
            start_size=font_second_line_size,
            min_size=MIN_SECOND_LINE_FONT_SIZE,
            max_width=image_width - 100,
        )

    draw.rectangle([(0, 0), (image_width, top_bar_height)], fill="black")
    draw.rectangle(
        [(0, image_height - bottom_bar_height), (image_width, image_height)],
        fill="black",
    )

    if WandImage is not None and Color is not None:
        with WandImage(filename=logo_path, background=Color("transparent"), resolution=300) as wand_image:
            wand_image.format = "png"
            wand_image.resize(logo_size[0], logo_size[1])
            logo_png_data = wand_image.make_blob("png")
            logo_image = Image.open(BytesIO(logo_png_data)).convert("RGBA")

        top_left_logo_x = logo_inset
        top_left_logo_y = (top_bar_height - logo_size[1]) // 2
        image.paste(logo_image, (top_left_logo_x, top_left_logo_y), logo_image)

        top_right_logo_x = image_width - logo_size[0] - logo_inset
        top_right_logo_y = (top_bar_height - logo_size[1]) // 2
        image.paste(logo_image, (top_right_logo_x, top_right_logo_y), logo_image)
    else:
        logger.warning("Wand/ImageMagick unavailable; rendering nametag without logo")

    draw.text((center_x, hello_text_y), "Hello", anchor="ma", fill="white", font=font_hello)
    draw.text(
        (center_x, my_name_is_text_y),
        "my name is",
        anchor="ma",
        fill="white",
        font=font_my_name_is,
    )

    white_space_top = top_bar_height
    white_space_bottom = image_height - bottom_bar_height
    white_space_height = white_space_bottom - white_space_top

    text_y = white_space_top + (white_space_height - name_metrics.height) // 2 + name_metrics.height

    if second_line:
        spacing = 40
        combined_height = name_metrics.height + second_line_metrics.height + spacing
        text_y = (
            white_space_top + (white_space_height - combined_height) // 2 + name_metrics.height
        )

        _draw_centered_line(
            draw=draw,
            text=second_line,
            center_x=center_x,
            baseline_y=text_y + second_line_metrics.height + spacing,
            font_size=font_second_line_size,
            fill="black",
        )

    _draw_centered_line(
        draw=draw,
        text=name,
        center_x=center_x,
        baseline_y=text_y,
        font_size=font_name_size,
        fill="black",
    )

    return image
