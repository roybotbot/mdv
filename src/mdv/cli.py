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
from rich.padding import Padding

# iTerm2 inline image escape sequence
# https://iterm2.com/documentation-images.html
OSC = "\033]"
ST = "\a"

# Inline images: ![alt](url)
IMAGE_INLINE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
# Reference images: ![alt][ref]
IMAGE_REF_PATTERN = re.compile(r"!\[([^\]]*)\]\[([^\]]*)\]")
# Reference definitions: [ref]: url
REF_DEF_PATTERN = re.compile(r"^\[([^\]]+)\]:\s*(\S+)", re.MULTILINE)


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


def fetch_markdown(source: str) -> tuple[str, Path | str]:
    """Fetch markdown text from a local file or URL.

    Returns (text, base) where base is a Path for local files
    or a URL string for remote files (used to resolve relative images).
    """
    if source.startswith(("http://", "https://")):
        try:
            req = urllib.request.Request(source, headers={"User-Agent": "mdv/0.1"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                text = resp.read().decode("utf-8")
            # Base URL for resolving relative image paths
            base_url = source.rsplit("/", 1)[0] + "/"
            return text, base_url
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            print(f"mdv: failed to fetch {source}: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        path = Path(source).resolve()
        if not path.is_file():
            print(f"mdv: {source}: No such file", file=sys.stderr)
            sys.exit(1)
        return path.read_text(encoding="utf-8"), path.parent


def resolve_image_src(src: str, base: Path | str) -> str:
    """Resolve a potentially relative image src against the base."""
    if src.startswith(("http://", "https://")):
        return src
    if isinstance(base, str):
        # base is a URL — join relative path
        return base + src
    # base is a local Path — return as-is, fetch_image handles it
    return src


def render(source: str):
    text, base = fetch_markdown(source)
    base_dir = base if isinstance(base, Path) else Path(".")
    MARGIN = 2
    term_cols = get_terminal_width()
    content_width = term_cols - (MARGIN * 2)
    console = Console(width=term_cols)

    # Build reference map from [ref]: url definitions
    ref_map = {m.group(1).lower(): m.group(2) for m in REF_DEF_PATTERN.finditer(text)}

    # Find all images (inline and reference-style) with their positions
    images = []
    for m in IMAGE_INLINE_PATTERN.finditer(text):
        images.append((m.start(), m.end(), m.group(1), m.group(2)))
    for m in IMAGE_REF_PATTERN.finditer(text):
        ref_key = (m.group(2) or m.group(1)).lower()
        src = ref_map.get(ref_key)
        if src:
            images.append((m.start(), m.end(), m.group(1), src))
    images.sort(key=lambda x: x[0])

    # Split markdown by image references, rendering text and images in order
    last_end = 0
    segments: list[tuple[str, str | None]] = []  # (text_chunk, image_src_or_none)

    for start, end, alt, src in images:
        text_before = text[last_end:start]
        if text_before.strip():
            segments.append((text_before, None))
        segments.append((alt, src))
        last_end = end

    # Remaining text after last image
    remaining = text[last_end:]
    if remaining.strip():
        segments.append((remaining, None))

    def print_md(md_text: str):
        console.print(Padding(Markdown(md_text), (0, MARGIN)))

    # If no images found, just render the whole thing
    if not any(src for _, src in segments):
        print_md(text)
        return

    for chunk_text, img_src in segments:
        if img_src is None:
            # Render markdown text
            print_md(chunk_text)
        else:
            # Try to display the image
            resolved_src = resolve_image_src(img_src, base)
            data = fetch_image(resolved_src, base_dir)
            if data:
                width = image_width_cells(data, content_width)
                escape = iterm2_image_bytes(data, width)
                sys.stdout.write(" " * MARGIN + escape + "\n")
            else:
                # Fallback: show alt text or URL
                alt_display = chunk_text if chunk_text else img_src
                console.print(Padding(f"[dim]\\[image: {alt_display}][/dim]", (0, MARGIN)))


def main():
    parser = argparse.ArgumentParser(
        prog="mdv",
        description="Render markdown in the terminal with inline images.",
    )
    parser.add_argument("source", help="Markdown file path or URL to render")
    args = parser.parse_args()

    # Ctrl+C exits cleanly
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))

    render(args.source)

    # Block until q, Escape, or Ctrl+C
    console = Console()
    console.print(Padding("\n[dim]Press q, Esc, or Ctrl+C to exit[/dim]", (0, 2)), end="")
    sys.stdout.flush()

    import tty
    import termios

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch in ("q", "Q", "\x1b", "\x03"):  # q, Escape, Ctrl+C
                break
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
