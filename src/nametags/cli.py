"""CLI for nametag printer."""

import argparse
import sys
from pathlib import Path

from .printer import make_image


def render(args):
    """Generate a nametag image from a local name or stdin."""
    if args.name == "-":
        lines = sys.stdin.read().splitlines()
        if not lines:
            print("Error: No stdin input", file=sys.stderr)
            sys.exit(1)
        name = lines[0]
        pronouns = lines[1] if len(lines) > 1 else None
        second_line = lines[2] if len(lines) > 2 else None
    else:
        name = args.name
        pronouns = args.pronouns
        second_line = args.second_line

    image = make_image(name, pronouns, second_line)

    if args.rotate:
        image = image.rotate(90, expand=True)

    output_path = Path(args.output)
    image.save(output_path)

    print(f"Nametag saved to: {output_path.absolute()}")
    print(f"Image size: {image.size[0]}x{image.size[1]} pixels")


def lookup(args):
    """Look up a name by RFID tag and output as text."""
    try:
        from .rfid import lookup_rfid
    except KeyError as e:
        print(f"Error: Missing environment variable {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: Failed to import rfid module: {e}", file=sys.stderr)
        sys.exit(1)

    (name, pronouns, second_line) = lookup_rfid(args.rfid_tag)

    if name is None:
        print(f"Error: RFID tag '{args.rfid_tag}' not found", file=sys.stderr)
        sys.exit(1)

    print(name)
    if pronouns:
        print(pronouns)
    if second_line:
        print(second_line)


def main():
    """CLI for nametag printer."""
    parser = argparse.ArgumentParser(description="Nametag printer CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    render_parser = subparsers.add_parser(
        "render", help="Generate a nametag image from a text input"
    )
    render_parser.add_argument(
        "name",
        help="Name to print, or '-' to read from stdin",
    )
    render_parser.add_argument(
        "--pronouns",
        "-p",
        default=None,
        help="Optional pronouns line (rendered between the name and second line)",
    )
    render_parser.add_argument(
        "--second-line",
        "-s",
        default=None,
        help="Optional second line of text",
    )
    render_parser.add_argument(
        "--output",
        "-o",
        default="nametag.png",
        help="Output filename (default: nametag.png)",
    )
    render_parser.add_argument(
        "--rotate",
        "-r",
        action="store_true",
        help="Rotate image 90 degrees (as it would be printed)",
    )

    lookup_parser = subparsers.add_parser("lookup", help="Look up a name by RFID tag")
    lookup_parser.add_argument("rfid_tag", help="RFID tag number to look up")

    args = parser.parse_args()

    if args.command == "render":
        render(args)
    elif args.command == "lookup":
        lookup(args)


if __name__ == "__main__":
    main()
