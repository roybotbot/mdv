"""mdv — Terminal markdown viewer with inline images for iTerm2."""

import argparse
import base64
import io
import os
import re
import signal
import sys
import urllib.request
import urllib.error
from pathlib import Path

from PIL import Image
from rich.console import Console
from rich.markdown import Markdown

# iTerm2 inline image escape sequence
# https://iterm2.com/documentation-images.html
OSC = "\033]"
ST = "\a"

IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def get_terminal_width():
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


def iterm2_image_bytes(data: bytes, width_cells: int | None = None) -> str:
    """Build an iTerm2 inline image escape sequence from raw image bytes."""
    b64 = base64.b64encode(data).decode("ascii")
    params = f"inline=1;size={len(data)}"
    if width_cells is not None:
        params += f";width={width_cells}"
    return f"{OSC}1337;File={params}:{b64}{ST}"


def fetch_image(src: str, base_dir: Path) -> bytes | None:
    """Fetch image bytes from a local path or remote URL."""
    if src.startswith(("http://", "https://")):
        try:
            req = urllib.request.Request(src, headers={"User-Agent": "mdv/0.1"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.read()
        except (urllib.error.URLError, OSError, TimeoutError):
            return None
    else:
        path = base_dir / src
        if path.is_file():
            return path.read_bytes()
        return None


def image_width_cells(data: bytes, term_cols: int) -> int | None:
    """Determine display width in terminal cells. Returns None if image fits, or term_cols if it needs scaling."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            # Rough heuristic: ~8 pixels per terminal cell
            img_cols = img.width // 8
            if img_cols > term_cols:
                return term_cols
            return None  # display at native size
    except Exception:
        return None


def render(filepath: str):
    path = Path(filepath).resolve()
    if not path.is_file():
        print(f"mdv: {filepath}: No such file", file=sys.stderr)
        sys.exit(1)

    text = path.read_text(encoding="utf-8")
    base_dir = path.parent
    term_cols = get_terminal_width()
    console = Console(width=term_cols)

    # Split markdown by image references, rendering text and images in order
    last_end = 0
    segments: list[tuple[str, str | None]] = []  # (text_chunk, image_src_or_none)

    for match in IMAGE_PATTERN.finditer(text):
        start, end = match.span()
        # Text before this image
        text_before = text[last_end:start]
        if text_before.strip():
            segments.append((text_before, None))
        # The image
        alt = match.group(1)
        src = match.group(2)
        segments.append((alt, src))
        last_end = end

    # Remaining text after last image
    remaining = text[last_end:]
    if remaining.strip():
        segments.append((remaining, None))

    # If no images found, just render the whole thing
    if not any(src for _, src in segments):
        console.print(Markdown(text))
        return

    for chunk_text, img_src in segments:
        if img_src is None:
            # Render markdown text
            console.print(Markdown(chunk_text))
        else:
            # Try to display the image
            data = fetch_image(img_src, base_dir)
            if data:
                width = image_width_cells(data, term_cols)
                escape = iterm2_image_bytes(data, width)
                sys.stdout.write(escape + "\n")
            else:
                # Fallback: show alt text or URL
                alt_display = chunk_text if chunk_text else img_src
                console.print(f"  [dim]\\[image: {alt_display}][/dim]")


def main():
    parser = argparse.ArgumentParser(
        prog="mdv",
        description="Render markdown in the terminal with inline images.",
    )
    parser.add_argument("file", help="Markdown file to render")
    args = parser.parse_args()

    # Ctrl+C exits cleanly
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))

    render(args.file)

    # Block until Ctrl+C
    console = Console()
    console.print("\n[dim]Press Ctrl+C to exit[/dim]", end="")
    try:
        signal.pause()
    except AttributeError:
        # Windows fallback
        import time
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
