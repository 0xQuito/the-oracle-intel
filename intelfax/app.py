"""The ORACLE receiver: draws pages, ticks the clock and reads keys."""

import argparse
import datetime as dt
import os
import shutil
import sys
import time

from . import keys, nav, pages, teletext
from .feeds import FeedManager
from .nav import FASTEXT_COLOURS
from .teletext import (BLUE, CYAN, WHITE, YELLOW, CONTENT_ROWS,
                       ROWS, Row, T, mosaic)

ARROWS = ("UP", "DOWN", "LEFT", "RIGHT")
FASTEXT_KEYS = {"r": 0, "g": 1, "y": 2, "c": 3, "F1": 0, "F2": 1, "F3": 2, "F4": 3}


class Context:
    def __init__(self, width, feeds, height=CONTENT_ROWS):
        self.W = width       # columns
        self.H = height      # rows available for the page body
        self.feeds = feeds
        self.reveal = False


def body_rows(spec, subs, sub, W, H):
    """Banner, title bar and the current subpage, padded to H body rows."""
    word, fg, bg = spec.banner
    rows = mosaic(word, fg, bg, W)
    counter = f"{sub + 1}/{len(subs)} " if len(subs) > 1 else ""
    rows.append(teletext.split_lr([T(" " + spec.title, spec.title_fg)],
                                  [T(counter, WHITE)], W, fill=spec.title_bg))
    content = list(subs[sub])
    content += [Row()] * (H - len(content))
    return rows + content


def status_row(spec):
    return Row(T(" " + spec.status, spec.status_fg))


def fastext_row(spec, W):
    row, cell = Row(), W // 4
    for i, (label, _) in enumerate(spec.fastext[:4]):
        row.add(f" {label:<{cell - 1}}"[:cell], FASTEXT_COLOURS[i])
    return row


def paginate(blocks, size=CONTENT_ROWS, cap=0):
    subs, cur = [], []
    for block in blocks:
        while len(block) > size:  # a block taller than a page gets split
            if cur:
                subs.append(cur)
                cur = []
            subs.append(block[:size])
            block = block[size:]
        if len(cur) + len(block) > size and cur:
            subs.append(cur)
            cur = []
        if not cur:  # don't start a subpage with blank rows
            while block and not block[0].length():
                block = block[1:]
        cur.extend(block)
    if cur or not subs:
        subs.append(cur)
    return subs[:cap] if cap else subs


class Receiver:
    def __init__(self, width):
        self.W = width
        self.feeds = FeedManager()
        self.ctx = Context(width, self.feeds)
        self.page = 100
        self.shown = 100       # number in the header (rolls while searching)
        self.sub = 0
        self.entry = ""
        self.history = []
        self.spec = None
        self.subs = [[]]
        self.items = []        # what the arrow keys can highlight (see nav.py)
        self.sel = 0           # index of the highlighted item
        self.want = None       # where the highlight should land once the page is built
        self.memory = {}       # page -> (subpage, highlighted item), so Back returns to it
        self.searching = None  # (target page, started at)
        self.seen_version = -1
        self.term_size = None

    # ---------------------------------------------------------------- data

    def build(self, n):
        r = pages.resolve(n)
        if r is None:
            return pages.not_found(n)
        return r[1](self.ctx) or pages.not_found(n)

    def needs(self, n):
        r = pages.resolve(n)
        return r[0] if r else []

    def waiting_for(self, n):
        return any(self.feeds.pending(f) for f in self.needs(n))

    # ---------------------------------------------------------- navigation

    def goto(self, n, remember=True, force=False):
        if self.spec is not None:
            self.memory[self.page] = (self.sub, self.sel)
        if remember and n != self.page:
            self.history.append(self.page)
            del self.history[:-50]
        self.page = n
        self.sub, self.want = self.memory.get(n, (0, ("first", 0)))
        for f in self.needs(n):
            self.feeds.request(f, force=force)
        if pages.resolve(n) is None or self.waiting_for(n) or force:
            self.searching = (n, time.monotonic())
        else:
            self.show()

    def show(self):
        """(Re)build the current page, keeping the subpage and highlight where possible."""
        self.searching = None
        self.shown = self.page
        self.spec = self.build(self.page)
        self.subs = paginate(self.spec.blocks, self.ctx.H, self.spec.max_subpages)
        self.sub = min(self.sub, len(self.subs) - 1)
        self.seen_version = self.feeds.version
        self.update_items()
        self.draw()

    def update_items(self):
        self.items = nav.selectables(self.spec, self.subs, self.sub, self.W, self.ctx.H)
        if self.want is not None:
            self.sel = nav.resolve(self.items, self.want)
            self.want = None
        self.sel = max(0, min(self.sel, len(self.items) - 1))

    def turn(self, delta, where=None):
        """Flip to another subpage and put the highlight on its first item."""
        x = nav.anchor(self.items[self.sel]) if self.items else 0
        self.sub = (self.sub + delta) % len(self.subs)
        self.want = where or ("first", x)
        self.update_items()
        self.draw()

    def arrow(self, key):
        if not self.items:
            return
        delta, where = nav.move(self.items, self.sel, key, self.sub, len(self.subs))
        if delta:
            return self.turn(delta, where)
        self.sel = nav.resolve(self.items, where)
        self.draw()

    def step(self, delta):
        n = self.page
        for _ in range(800):
            n = (n - 100 + delta) % 800 + 100
            if pages.exists(n, self.ctx):
                return self.goto(n)

    def handle(self, k):
        if k is None:
            return True
        low = k.lower() if len(k) == 1 else k
        if k.isdigit() and len(k) == 1:
            if not self.entry and k in "09":
                return True  # pages run 100-899
            self.entry += k
            if len(self.entry) == 3:
                n, self.entry = int(self.entry), ""
                self.goto(n)
            else:
                self.draw_chrome()
        elif k in ("\b", "\x08"):
            self.entry = self.entry[:-1]
            self.draw_chrome()
        elif k == "ESC":
            self.entry = ""
            self.draw_chrome()
        elif low in ("q", "\x03"):
            return False
        elif self.searching:
            return True  # ignore other keys until the page arrives
        elif low in ARROWS:
            self.arrow(low)
        elif k == "\r":
            if self.items:
                self.goto(self.items[self.sel]["page"])
        elif low in ("n", " "):
            self.turn(1)
        elif low == "p":
            self.turn(-1)
        elif low in ("+", "="):
            self.step(1)
        elif low == "-":
            self.step(-1)
        elif low in FASTEXT_KEYS:
            links = self.spec.fastext if self.spec else []
            i = FASTEXT_KEYS[low]
            if i < len(links):
                self.goto(links[i][1])
        elif low == "i":
            self.goto(100)
        elif low in ("?", "h"):
            self.goto(199)
        elif low == "b":
            if self.history:
                self.goto(self.history.pop(), remember=False)
        elif low == "u":
            self.goto(self.page, remember=False, force=True)
        elif low == "v":
            self.ctx.reveal = not self.ctx.reveal
            self.show()
        elif k == "\x0c":  # Ctrl+L: redraw the whole screen
            self.draw(clear=True)
        return True

    # ------------------------------------------------------------- drawing

    def header(self):
        t = dt.datetime.now()
        typed = (self.entry + "___")[:3] if self.entry else f"{self.page}"
        time_s = t.strftime("%H:%M/%S")
        left = [T(f" P{typed}", WHITE), T(" THE ORACLE ", CYAN), T(f"{self.shown:>3}", WHITE)]
        right = [T(t.strftime("%a %d %b") + " ", WHITE), T(time_s, YELLOW)]
        return teletext.split_lr(left, right, self.W)

    def footer_rows(self):
        spec = self.spec
        status = status_row(spec) if spec else Row()
        if self.searching:
            status = Row(T(" Searching for page %d..." % self.searching[0], YELLOW))
        fast = fastext_row(spec, self.W) if spec else Row()
        typed = (self.entry + "___")[:3]
        hint = "  ARROWS+ENTER:select  N/P:subpage  Q:quit" if self.W >= 60 else "  ARROWS+ENTER  Q:quit"
        prompt = Row(T(" PAGE> ", YELLOW), T(typed, WHITE), T(hint, CYAN), fill=BLUE)
        return [status, fast, prompt]

    def body_rows(self):
        if self.spec is None:
            return [Row()] * (ROWS - 4)
        return body_rows(self.spec, self.subs, self.sub, self.W, self.ctx.H)

    def frame(self):
        return [self.header()] + self.body_rows() + self.footer_rows()

    def origin(self):
        cols, lines = shutil.get_terminal_size((80, 25))
        return max(0, (cols - self.W) // 2) + 1, max(0, (lines - ROWS) // 2) + 1

    def highlight_on(self, screen_row):
        """(start, end, colour) if the highlight sits on this screen row."""
        if self.searching or not self.items:
            return None
        it = self.items[self.sel]
        return (it["start"], it["end"], it["hl"]) if it["row"] + 1 == screen_row else None

    def put(self, y_off, rows):
        x, y = self.origin()
        out = []
        for i, row in enumerate(rows):
            hl = self.highlight_on(y_off + i)
            out.append(f"\x1b[{y + y_off + i};{x}H" + teletext.ansi(row, self.W, hl))
        sys.stdout.write("".join(out))
        sys.stdout.flush()

    def draw(self, clear=False):
        size = shutil.get_terminal_size((80, 25))
        if clear or size != self.term_size:
            self.term_size = size
            sys.stdout.write("\x1b[0m\x1b[2J")
        self.put(0, self.frame())

    def draw_chrome(self):
        """Redraw only the header and footer (cheap, for typing and the clock)."""
        self.put(0, [self.header()])
        self.put(ROWS - 3, self.footer_rows())

    # ---------------------------------------------------------------- loop

    def tick(self):
        if shutil.get_terminal_size((80, 25)) != self.term_size:
            self.draw()
        if self.searching:
            target, started = self.searching
            elapsed = time.monotonic() - started
            ready = pages.resolve(target) is not None and not self.waiting_for(target)
            # Roll the header page counter like a real set hunting for a page.
            if not ready or elapsed < 0.4:
                if not (pages.resolve(target) is None and elapsed > 1.2):
                    self.shown = (self.shown - 100 + 7) % 800 + 100
                    self.draw_chrome()
                    return
            self.show()
        elif self.feeds.version != self.seen_version:
            changed = self.needs(self.page) or self.page == 100
            self.seen_version = self.feeds.version
            if changed:
                self.show()

    def run(self):
        enable_terminal()
        sys.stdout.write("\x1b]0;THE ORACLE\x07\x1b[?1049h\x1b[?25l\x1b[2J")
        try:
            with keys.raw_mode():
                for f in pages.ALL_FEEDS:  # warm every feed in the background
                    self.feeds.request(f)
                self.goto(100, remember=False)
                last_sec = None
                while True:
                    key = keys.get_key(0.08 if self.searching else 0.25)
                    if not self.handle(key):
                        break
                    self.tick()
                    sec = int(time.time())
                    if sec != last_sec and not self.searching:
                        last_sec = sec
                        self.put(0, [self.header()])
        except KeyboardInterrupt:
            pass
        finally:
            sys.stdout.write("\x1b[0m\x1b[?25h\x1b[?1049l")
            sys.stdout.flush()


def enable_terminal():
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if k32.GetConsoleMode(h, ctypes.byref(mode)):
            k32.SetConsoleMode(h, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass


def snapshot(width, n, sub, plain, timeout=90):
    """Print one page and exit (handy for testing or piping)."""
    rx = Receiver(width)
    for f in rx.needs(n):
        rx.feeds.request(f)
    end = time.time() + timeout
    while rx.waiting_for(n) and time.time() < end:
        time.sleep(0.2)
    rx.page = rx.shown = n
    rx.spec = rx.build(n)
    rx.subs = paginate(rx.spec.blocks, rx.ctx.H, rx.spec.max_subpages)
    rx.sub = min(sub, len(rx.subs) - 1)
    enable_terminal()
    for row in rx.frame():
        print(row.plain(width) if plain else teletext.ansi(row, width))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="intelfax", description="Teletext-style cyber threat intel.")
    ap.add_argument("--wide", action="store_true", help="80 columns instead of the classic 40")
    ap.add_argument("--basic-colors", action="store_true", help="16-colour mode for older terminals")
    ap.add_argument("--snapshot", type=int, metavar="PAGE", help="print one page and exit")
    ap.add_argument("--sub", type=int, default=1, help="subpage for --snapshot (from 1)")
    ap.add_argument("--plain", action="store_true", help="no colours in --snapshot output")
    ap.add_argument("--web", action="store_true", help="run as a web page in your browser")
    ap.add_argument("--port", type=int, default=8040, help="port for --web (default 8040)")
    ap.add_argument("--cols", type=int, default=80, help="--web screen width in characters")
    ap.add_argument("--rows", type=int, default=32, help="--web screen height in rows")
    ap.add_argument("--no-browser", action="store_true", help="--web without opening a browser")
    args = ap.parse_args(argv)
    teletext.TRUECOLOR = not args.basic_colors
    if args.web:
        from .web import serve
        serve(args.port, args.cols, args.rows, open_browser=not args.no_browser)
        return
    width = 80 if args.wide else 40
    if args.snapshot:
        snapshot(width, args.snapshot, args.sub - 1, args.plain)
        return
    if not sys.stdin.isatty():
        sys.exit("intelfax needs an interactive terminal (or use --snapshot PAGE).")
    Receiver(width).run()
