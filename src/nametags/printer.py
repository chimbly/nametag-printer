from io import BytesIO
import unicodedata
from os import environ, path

from brother_ql.backends.helpers import discover, send
from brother_ql.conversion import convert
from brother_ql.labels import LabelsManager
from brother_ql.raster import BrotherQLRaster
from PIL import Image, ImageDraw, ImageFont
from wand.color import Color
from wand.image import Image as WandImage

from .logconf import setup_logging

setup_logging()

# Get the directory of the current script
script_dir = path.dirname(path.abspath(__file__))
asset_dir = path.join(script_dir, "assets")

# Path to the font file
font_path = path.join(asset_dir, "OpenSans-Regular.ttf")
bold_font_path = path.join(asset_dir, "OpenSans-SemiBold.ttf")

# Path to the logo file
logo_path = path.join(asset_dir, "ps1-logo-clean-white.svg")

# Make sure the asset files exist
for asset_path in (logo_path, font_path, bold_font_path):
    if not path.isfile(asset_path):
        raise FileNotFoundError(f"Font file not found: {asset_path}")


LABEL_SIZE = environ.get("LABEL_SIZE", "62x100")
MIN_FONT_SIZE = int(environ.get("MIN_FONT_SIZE", "30"))

_FORMAT_CHARS = {"\u200c", "\u200d", "\ufe0e", "\ufe0f"}
_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}
_MISSING_CACHE: dict[tuple[str, int], tuple[tuple[int, int], bytes]] = {}
_SUPPORT_CACHE: dict[tuple[str, int, str], bool] = {}


def _font_chain(primary_font: str) -> list[str]:
    configured = [
        p.strip()
        for p in environ.get("UNICODE_FONT_PATHS", "").split(path.pathsep)
        if p.strip()
    ]
    common = [
        path.join(asset_dir, "NotoSans-Regular.ttf"),
        path.join(asset_dir, "NotoSansArabic-Regular.ttf"),
        path.join(asset_dir, "NotoSansHebrew-Regular.ttf"),
        path.join(asset_dir, "NotoSansEthiopic-Regular.ttf"),
        path.join(asset_dir, "NotoSansCJK-Regular.ttc"),
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansHebrew-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansEthiopic-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]

    ordered: list[str] = []
    for candidate in [primary_font, *configured, *common]:
        if path.isfile(candidate) and candidate not in ordered:
            ordered.append(candidate)
    return ordered


def _get_font(font_file: str, size: int) -> ImageFont.FreeTypeFont:
    key = (font_file, size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]

    if hasattr(ImageFont, "Layout"):
        try:
            _FONT_CACHE[key] = ImageFont.truetype(
                font_file,
                size=size,
                layout_engine=ImageFont.Layout.RAQM,
            )
            return _FONT_CACHE[key]
        except Exception:
            pass

    _FONT_CACHE[key] = ImageFont.truetype(font_file, size=size)
    return _FONT_CACHE[key]


def _missing_fingerprint(font_file: str, size: int) -> tuple[tuple[int, int], bytes]:
    key = (font_file, size)
    if key in _MISSING_CACHE:
        return _MISSING_CACHE[key]

    mask = _get_font(font_file, size).getmask("\u0378", mode="L")
    _MISSING_CACHE[key] = (mask.size, bytes(mask))
    return _MISSING_CACHE[key]


def _supports_char(font_file: str, size: int, ch: str) -> bool:
    key = (font_file, size, ch)
    if key in _SUPPORT_CACHE:
        return _SUPPORT_CACHE[key]

    if ch.isspace() or ch in _FORMAT_CHARS:
        _SUPPORT_CACHE[key] = True
        return True

    if unicodedata.category(ch).startswith("M"):
        _SUPPORT_CACHE[key] = True
        return True

    font = _get_font(font_file, size)
    char_mask = font.getmask(ch, mode="L")
    missing_size, missing_data = _missing_fingerprint(font_file, size)
    supported = not (
        char_mask.size == missing_size and bytes(char_mask) == missing_data
    )

    _SUPPORT_CACHE[key] = supported
    return supported


def _text_runs(text: str, font_files: list[str], size: int) -> list[tuple[str, str]]:
    runs: list[tuple[str, str]] = []
    run_text = ""
    run_font: str | None = None

    for ch in text:
        chosen = run_font if (run_font and ch.isspace()) else None
        if chosen is None:
            for font_file in font_files:
                if _supports_char(font_file, size, ch):
                    chosen = font_file
                    break

        if chosen is None:
            continue

        if run_font != chosen and run_text:
            runs.append((run_text, run_font))
            run_text = ""

        run_font = chosen
        run_text += ch

    if run_text and run_font is not None:
        runs.append((run_text, run_font))

    return runs


def _measure_runs(
    draw: ImageDraw.ImageDraw,
    runs: list[tuple[str, str]],
    size: int,
) -> tuple[list[int], int, int]:
    widths: list[int] = []
    total_width = 0
    line_height = 0

    for run_text, run_font_file in runs:
        run_font = _get_font(run_font_file, size)
        left, top, right, bottom = draw.textbbox((0, 0), run_text, font=run_font)
        width = max(0, right - left)
        height = max(0, bottom - top)
        widths.append(width)
        total_width += width
        line_height = max(line_height, height)

    return widths, total_width, line_height


def _fit_line(
    draw: ImageDraw.ImageDraw,
    text: str,
    start_size: int,
    max_width: int,
    font_files: list[str],
) -> tuple[int, list[tuple[str, str]], list[int], int, int]:
    size = start_size
    while True:
        runs = _text_runs(text, font_files, size)
        widths, total_width, line_height = _measure_runs(draw, runs, size)
        if total_width <= max_width or size <= MIN_FONT_SIZE:
            return size, runs, widths, total_width, line_height
        size -= 5


def _draw_centered_runs(
    draw: ImageDraw.ImageDraw,
    runs: list[tuple[str, str]],
    widths: list[int],
    center_x: int,
    baseline_y: int,
    size: int,
    line_height: int,
    fill: str,
):
    x = center_x - (sum(widths) // 2)
    y = baseline_y - line_height

    for (run_text, run_font_file), run_width in zip(runs, widths):
        run_font = _get_font(run_font_file, size)
        draw.text((x, y), run_text, anchor="lt", fill=fill, font=run_font)
        x += run_width


def get_printer_id():
    """Auto-discover the printer and return its identifier."""
    # Auto-discover the printer using the pyusb backend
    printer_id = discover("pyusb")[0]["identifier"]

    # Discard broken serial from identifier
    # https://github.com/pklaus/brother_ql_web/issues/10#issuecomment-994990935
    printer_id = printer_id.split("_")[0]

    return printer_id


def print_name(name: str, second_line: str | None):
    """Print a nametag with the given name."""
    image = make_image(name, second_line)
    image.rotate(90, expand=True)
    print_image(image)


def print_image(image: Image.Image):
    """Print the given PIL image."""
    qlr = BrotherQLRaster("QL-800")
    qr_data = convert(qlr, [image], LABEL_SIZE)
    printer_id = get_printer_id()
    send(qr_data, printer_id)


def make_image(name: str, second_line: str | None) -> Image.Image:
    """Generate a nametag image with the given name.

    Args:
        name: The name to display on the nametag
        second_line: Optional second line of text
    """

    name = unicodedata.normalize("NFC", name)

    # Trim second line, turn empty to None
    if second_line is not None:
        second_line = unicodedata.normalize("NFC", second_line).strip()
        if len(second_line) == 0:
            second_line = None

    # Define image dimensions
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

    # Define black bar heights
    top_bar_height = 200
    bottom_bar_height = 100

    # Define text positions
    hello_text_y = 0
    my_name_is_text_y = 115

    # Desired size of the logo (width, height)
    logo_size = (100, 100)
    logo_inset = 50  # Inset from the edges

    # Create a blank white image
    image = Image.new("RGB", (image_width, image_height), "white")
    draw = ImageDraw.Draw(image)

    # Load fonts
    font_name_size = 170
    font_second_line_size = 120
    font_hello_size = 100
    font_my_name_is_size = 50

    # Raises IOError if the font file is not found
    font_hello = _get_font(font_path, font_hello_size)
    font_my_name_is = _get_font(bold_font_path, font_my_name_is_size)

    text_fonts = _font_chain(font_path)
    font_name_size, name_runs, name_widths, _, text_height = _fit_line(
        draw,
        name,
        font_name_size,
        image_width - 100,
        text_fonts,
    )

    second_line_runs: list[tuple[str, str]] = []
    second_line_widths: list[int] = []
    second_line_height = 0
    if second_line:
        (
            font_second_line_size,
            second_line_runs,
            second_line_widths,
            _,
            second_line_height,
        ) = _fit_line(
            draw,
            second_line,
            font_second_line_size,
            image_width - 100,
            text_fonts,
        )

    # Add black bars at the top and bottom
    draw.rectangle([(0, 0), (image_width, top_bar_height)], fill="black")
    draw.rectangle(
        [(0, image_height - bottom_bar_height), (image_width, image_height)],
        fill="black",
    )

    # Render the SVG logo into a rasterized image using Wand
    with WandImage(
        filename=logo_path, background=Color("transparent"), resolution=300
    ) as wand_image:
        wand_image.format = "png"  # Convert the SVG to PNG format
        wand_image.resize(
            logo_size[0], logo_size[1]
        )  # Resize the image to the desired size
        logo_png_data = wand_image.make_blob("png")  # Get the PNG data as a binary blob
        logo_image = Image.open(BytesIO(logo_png_data)).convert(
            "RGBA"
        )  # Convert to a Pillow image

    # Add the logo to the top-left corner of the black bar
    top_left_logo_x = logo_inset
    top_left_logo_y = (
        top_bar_height - logo_size[1]
    ) // 2  # Center vertically in the black bar
    image.paste(logo_image, (top_left_logo_x, top_left_logo_y), logo_image)

    # Add the logo to the top-right corner of the black bar
    top_right_logo_x = image_width - logo_size[0] - logo_inset
    top_right_logo_y = (
        top_bar_height - logo_size[1]
    ) // 2  # Center vertically in the black bar
    image.paste(logo_image, (top_right_logo_x, top_right_logo_y), logo_image)

    # Add "Hello" text
    hello_text = "Hello"
    draw.text(
        (center_x, hello_text_y), hello_text, anchor="ma", fill="white", font=font_hello
    )

    # Add "my name is" text
    my_name_is_text = "my name is"
    draw.text(
        (center_x, my_name_is_text_y),
        my_name_is_text,
        anchor="ma",
        fill="white",
        font=font_my_name_is,
    )

    # Calculate text position to center the name within the white space
    white_space_top = top_bar_height
    white_space_bottom = image_height - bottom_bar_height
    white_space_height = white_space_bottom - white_space_top

    text_y = white_space_top + (white_space_height - text_height) // 2 + text_height

    # Draw the second line if specified (moves name up)
    if second_line_runs:
        spacing = 40

        combined_height = text_height + second_line_height + spacing
        text_y = (
            white_space_top + (white_space_height - combined_height) // 2 + text_height
        )

        _draw_centered_runs(
            draw,
            second_line_runs,
            second_line_widths,
            center_x,
            text_y + second_line_height + spacing,
            font_second_line_size,
            second_line_height,
            "black",
        )

    # Draw the name on the image
    _draw_centered_runs(
        draw,
        name_runs,
        name_widths,
        center_x,
        text_y,
        font_name_size,
        text_height,
        "black",
    )

    return image
