from io import BytesIO
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


def get_printer_id():
    """Auto-discover the printer and return its identifier."""
    # Auto-discover the printer using the pyusb backend
    printer_id = discover('pyusb')[0]['identifier']

    # Discard broken serial from identifier
    # https://github.com/pklaus/brother_ql_web/issues/10#issuecomment-994990935
    printer_id = printer_id.split("_")[0]

    return printer_id


def print_name(name: str, pronouns: str | None, second_line: str | None):
    """Print a nametag with the given name."""
    image = make_image(name, pronouns, second_line)
    image.rotate(90, expand=True)
    print_image(image)


def print_image(image: Image.Image):
    """Print the given PIL image."""
    qlr = BrotherQLRaster("QL-800")
    qr_data = convert(qlr, [image], LABEL_SIZE)
    printer_id = get_printer_id()
    send(qr_data, printer_id)


def make_image(name: str, pronouns: str | None, second_line: str | None) -> Image.Image:
    """Generate a nametag image with the given name.

    Args:
        name: The name to display on the nametag
        pronouns: Optional pronouns line (rendered between name and second line)
        second_line: Optional second line of text
    """

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
    font_pronouns_size = 80
    font_second_line_size = 120
    font_hello_size = 100
    font_my_name_is_size = 50

    # Raises IOError if the font file is not found
    font_hello = ImageFont.truetype(font_path, font_hello_size)
    font_my_name_is = ImageFont.truetype(bold_font_path, font_my_name_is_size)

    # Trim optional lines, treat empty as absent
    if pronouns is not None:
        pronouns = pronouns.strip()
        if len(pronouns) == 0:
            pronouns = None
    if second_line is not None:
        second_line = second_line.strip()
        if len(second_line) == 0:
            second_line = None

    def _fit_font(text: str, start_size: int, step: int = 5) -> tuple[ImageFont.FreeTypeFont, int]:
        """Shrink-to-fit: find the largest font size whose bbox fits horizontally."""
        size = start_size
        while True:
            font = ImageFont.truetype(font_path, size)
            (left, _, right, _) = font.getbbox(text)
            if right - left <= image_width - 100:
                return font, size
            size -= step

    font_name, font_name_size = _fit_font(name, font_name_size)
    (_, name_top, _, name_bottom) = font_name.getbbox(name)
    name_height = name_bottom - name_top

    if pronouns is not None:
        font_pronouns, font_pronouns_size = _fit_font(pronouns, font_pronouns_size)
        (_, pronouns_top, _, pronouns_bottom) = font_pronouns.getbbox(pronouns)
        pronouns_height = pronouns_bottom - pronouns_top

    if second_line is not None:
        font_second_line, font_second_line_size = _fit_font(second_line, font_second_line_size)
        (_, sl_top, _, sl_bottom) = font_second_line.getbbox(second_line)
        second_line_height = sl_bottom - sl_top

    # Add black bars at the top and bottom
    draw.rectangle([(0, 0), (image_width, top_bar_height)], fill="black")
    draw.rectangle([(0, image_height - bottom_bar_height), (image_width, image_height)], fill="black")

    # Render the SVG logo into a rasterized image using Wand
    with WandImage(filename=logo_path, background=Color('transparent'), resolution=300) as wand_image:
        wand_image.format = 'png'  # Convert the SVG to PNG format
        wand_image.resize(logo_size[0], logo_size[1])  # Resize the image to the desired size
        logo_png_data = wand_image.make_blob('png')  # Get the PNG data as a binary blob
        logo_image = Image.open(BytesIO(logo_png_data)).convert("RGBA")  # Convert to a Pillow image

    # Add the logo to the top-left corner of the black bar
    top_left_logo_x = logo_inset
    top_left_logo_y = (top_bar_height - logo_size[1]) // 2  # Center vertically in the black bar
    image.paste(logo_image, (top_left_logo_x, top_left_logo_y), logo_image)

    # Add the logo to the top-right corner of the black bar
    top_right_logo_x = image_width - logo_size[0] - logo_inset
    top_right_logo_y = (top_bar_height - logo_size[1]) // 2  # Center vertically in the black bar
    image.paste(logo_image, (top_right_logo_x, top_right_logo_y), logo_image)

    # Add "Hello" text
    hello_text = "Hello"
    draw.text((center_x, hello_text_y), hello_text, anchor="ma", fill="white", font=font_hello)

    # Add "my name is" text
    my_name_is_text = "my name is"
    draw.text((center_x, my_name_is_text_y), my_name_is_text, anchor="ma", fill="white", font=font_my_name_is)

    # Stack name + optional pronouns + optional second_line centered in the
    # white space between the black bars.
    white_space_top = top_bar_height
    white_space_bottom = image_height - bottom_bar_height
    white_space_height = white_space_bottom - white_space_top

    lines: list[tuple[str, ImageFont.FreeTypeFont, float]] = [(name, font_name, name_height)]
    if pronouns is not None:
        lines.append((pronouns, font_pronouns, pronouns_height))
    if second_line is not None:
        lines.append((second_line, font_second_line, second_line_height))

    spacing = 40
    combined_height = sum(h for _, _, h in lines) + spacing * (len(lines) - 1)
    top_y = white_space_top + (white_space_height - combined_height) // 2

    cursor_y = top_y
    for text, font, height in lines:
        # anchor="mb": (x, y) is bottom-center of the text box.
        draw.text((center_x, cursor_y + height), text, anchor="mb", fill="black", font=font)
        cursor_y += height + spacing

    return image
