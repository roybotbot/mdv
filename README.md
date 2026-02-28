# mdv — Terminal Markdown Viewer

Render markdown files in the terminal with inline image support for iTerm2.

## Install

```
pipx install .
```

## Usage

```
mdv README.md
mdv path/to/any/file.md
```

Press `q`, `Esc`, or `Ctrl+C` to exit.

## Features

- Full markdown rendering via `rich`
- Inline images (local files + remote URLs) via iTerm2 image protocol
- Images scaled to fit terminal width when too large
- Graceful fallback when images can't be loaded
