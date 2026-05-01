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
    font_hello = ImageFont.truetype(font_path, font_hello_size)
    font_my_name_is = ImageFont.truetype(bold_font_path, font_my_name_is_size)

    # Trim second line, turn empty to None
    if second_line is not None:
        second_line = second_line.strip()
        if len(second_line) == 0:
            second_line = None

    # Dynamically adjust font size for the name
    while True:
        font_name = ImageFont.truetype(font_path, font_name_size)

        (left, top, right, bottom) = font_name.getbbox(name)
        text_width = right - left
        text_height = bottom - top

        # Leave a margin on both sides
        if text_width <= image_width - 100:
            break

        # Decrease font size if text is too wide
        font_name_size -= 5

    # Dynamically adjust font size for the second line
    while second_line:
        font_second_line = ImageFont.truetype(font_path, font_second_line_size)

        (left, top, right, bottom) = font_second_line.getbbox(second_line)
        second_line_width = right - left
        second_line_height = bottom - top

        # Leave a margin on both sides
        if second_line_width <= image_width - 100:
            break

        # Decrease font size if text is too wide
        font_second_line_size -= 5

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
    if second_line is not None:
        spacing = 40

        combined_height = text_height + second_line_height + spacing
        text_y = (
            white_space_top + (white_space_height - combined_height) // 2 + text_height
        )

        draw.text(
            (center_x, text_y + second_line_height + spacing),
            second_line,
            anchor="mb",
            fill="black",
            font=font_second_line,
        )

    # Draw the name on the image
    draw.text((center_x, text_y), name, anchor="mb", fill="black", font=font_name)

    return image
