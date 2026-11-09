"""Teletext-style screen primitives: the 8-colour palette, rows of coloured
text, chunky mosaic lettering and ANSI output."""

import html
import re
import textwrap
import unicodedata

# The classic teletext palette: fully saturated, nothing in between.
BLACK = (0, 0, 0)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
YELLOW = (255, 255, 0)
BLUE = (0, 0, 255)
MAGENTA = (255, 0, 255)
CYAN = (0, 255, 255)
WHITE = (255, 255, 255)

_BASIC = {BLACK: 0, RED: 1, GREEN: 2, YELLOW: 3, BLUE: 4, MAGENTA: 5, CYAN: 6, WHITE: 7}

# Set to False (--basic-colors) for terminals without 24-bit colour.
TRUECOLOR = True

ROWS = 25          # a teletext page is 25 rows...
CONTENT_ROWS = 17  # ...of which rows 5-21 hold the page body


def T(text, fg=WHITE, bg=None):
    """A span of text. bg=None means 'use the row's background'."""
    return (str(text), fg, bg)


class Row:
    def __init__(self, *spans, fill=BLACK):
        self.spans = [s if isinstance(s, tuple) else T(s) for s in spans]
        self.fill = fill
        self.links = []  # (page, start column, end column or None = full width)

    def link(self, page, start=0, end=None):
        """Mark columns start..end of this row as a link the arrow keys can select."""
        self.links.append((page, start, end))
        return self

    def add(self, text, fg=WHITE, bg=None):
        self.spans.append(T(text, fg, bg))
        return self

    def length(self):
        return sum(len(s[0]) for s in self.spans)

    def cells(self, width):
        out = []
        for text, fg, bg in self.spans:
            for ch in text:
                if len(out) >= width:
                    return out
                out.append((ch, fg, self.fill if bg is None else bg))
        while len(out) < width:
            out.append((" ", WHITE, self.fill))
        return out

    def plain(self, width):
        return "".join(c[0] for c in self.cells(width)).rstrip()


def blank():
    return Row()


def split_lr(left_spans, right_spans, width, fill=BLACK):
    """A row with some spans on the left and some pushed to the right edge."""
    left = Row(*left_spans, fill=fill)
    right_len = sum(len(s[0]) for s in right_spans)
    room = width - right_len
    # Trim the left part if it would collide with the right part.
    spans, used = [], 0
    for text, fg, bg in left.spans:
        if used + len(text) > room - 1:
            text = text[: max(0, room - 1 - used)]
        spans.append((text, fg, bg))
        used += len(text)
    spans.append((" " * max(0, room - used), WHITE, None))
    return Row(*spans, *right_spans, fill=fill)


# ---------------------------------------------------------------- text tidy

_CHARMAP = str.maketrans({
    "–": "-", "—": "-", "‘": "'", "’": "'", "“": '"',
    "”": '"', "…": "...", " ": " ", "•": "*", "·": "-",
    "′": "'", "«": '"', "»": '"',
})


def clean(s):
    """Feed text -> plain ASCII on one line (teletext had no emoji)."""
    if s is None:
        return ""
    s = re.sub(r"<[^>]+>", " ", str(s))
    s = html.unescape(s).translate(_CHARMAP)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip()


def wrap(text, width):
    return textwrap.wrap(text, width, break_long_words=True, break_on_hyphens=False) or [""]


def clip(text, width):
    return text if len(text) <= width else text[: max(0, width - 1)] + "~"


def para(text, width, fg=WHITE, indent=0):
    """Wrap a paragraph into Rows."""
    pad = " " * indent
    return [Row(T(pad + line, fg)) for line in wrap(text, width - indent)]


# ------------------------------------------------------------ mosaic letters
# A 3x5 pixel font drawn with half-block characters, standing in for the
# teletext mosaic graphics used for big page banners.

_FONT = {
    "A": ".#.|#.#|###|#.#|#.#", "B": "##.|#.#|##.|#.#|##.", "C": ".##|#..|#..|#..|.##",
    "D": "##.|#.#|#.#|#.#|##.", "E": "###|#..|##.|#..|###", "F": "###|#..|##.|#..|#..",
    "G": ".##|#..|#.#|#.#|.##", "H": "#.#|#.#|###|#.#|#.#", "I": "###|.#.|.#.|.#.|###",
    "J": "..#|..#|..#|#.#|.#.", "K": "#.#|#.#|##.|#.#|#.#", "L": "#..|#..|#..|#..|###",
    "M": "#.#|###|###|#.#|#.#", "N": "##.|#.#|#.#|#.#|#.#", "O": ".#.|#.#|#.#|#.#|.#.",
    "P": "##.|#.#|##.|#..|#..", "Q": ".#.|#.#|#.#|##.|.##", "R": "##.|#.#|##.|#.#|#.#",
    "S": ".##|#..|.#.|..#|##.", "T": "###|.#.|.#.|.#.|.#.", "U": "#.#|#.#|#.#|#.#|###",
    "V": "#.#|#.#|#.#|#.#|.#.", "W": "#.#|#.#|###|###|#.#", "X": "#.#|#.#|.#.|#.#|#.#",
    "Y": "#.#|#.#|.#.|.#.|.#.", "Z": "###|..#|.#.|#..|###",
    "0": "###|#.#|#.#|#.#|###", "1": ".#.|##.|.#.|.#.|###", "2": "##.|..#|.#.|#..|###",
    "3": "##.|..#|.#.|..#|##.", "4": "#.#|#.#|###|..#|..#", "5": "###|#..|##.|..#|##.",
    "6": ".##|#..|###|#.#|###", "7": "###|..#|.#.|.#.|.#.", "8": "###|#.#|###|#.#|###",
    "9": "###|#.#|###|..#|##.", " ": "...|...|...|...|...", "-": "...|...|###|...|...",
}

_HALF = {(1, 1): "█", (1, 0): "▀", (0, 1): "▄", (0, 0): " "}


def mosaic(word, fg, bg, width):
    """Render a word as three rows of chunky block letters, centred.
    On wide screens each pixel is two columns wide, if the word still fits."""
    word = word.upper()
    scale = 2 if (len(word) * 4 - 1) * 2 <= width - 2 else 1
    grid = [[] for _ in range(6)]  # 5 pixel rows + 1 empty so rows pair up
    for i, ch in enumerate(word):
        glyph = _FONT.get(ch, _FONT[" "]).split("|")
        for y in range(6):
            bits = [1 if c == "#" else 0 for c in glyph[y]] if y < 5 else [0, 0, 0]
            bits += [0] if i < len(word) - 1 else []
            grid[y].extend(b for b in bits for _ in range(scale))
    cols = len(grid[0])
    left = max(0, (width - cols) // 2)
    rows = []
    for r in range(3):
        line = "".join(_HALF[(grid[2 * r][c], grid[2 * r + 1][c])] for c in range(cols))
        rows.append(Row(T(" " * left), T(line, fg), fill=bg))
    return rows


# ------------------------------------------------------------- ANSI output

def _fg(c):
    if TRUECOLOR:
        return "38;2;%d;%d;%d" % c
    n = _BASIC.get(c, 7)
    return str(90 + n) if n else "30"


def _bg(c):
    if TRUECOLOR:
        return "48;2;%d;%d;%d" % c
    n = _BASIC.get(c, 0)
    return str(100 + n) if n else "40"


def highlight(cells, fill, hl):
    """Invert columns start..end to black-on-colour. Cells with their own
    background (like a severity badge) keep their colours."""
    start, end, colour = hl
    for c in range(start, min(end, len(cells))):
        ch, fg, bg = cells[c]
        if bg == fill:
            cells[c] = (ch, BLACK, colour)
    return cells


def ansi(row, width, hl=None):
    out, cur = [], None
    cells = row.cells(width)
    if hl:
        highlight(cells, row.fill, hl)
    for ch, fg, bg in cells:
        if (fg, bg) != cur:
            out.append("\x1b[%s;%sm" % (_fg(fg), _bg(bg)))
            cur = (fg, bg)
        out.append(ch)
    out.append("\x1b[0m")
    return "".join(out)
