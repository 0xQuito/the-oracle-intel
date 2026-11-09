"""Single-keypress input on Windows and Unix, with a timeout so the clock
can keep ticking while we wait. Returns a character, or one of
UP/DOWN/LEFT/RIGHT/F1-F4/ESC, or None on timeout."""

import os
import sys
import time

if os.name == "nt":
    import msvcrt

    _SPECIAL = {"H": "UP", "P": "DOWN", "K": "LEFT", "M": "RIGHT",
                ";": "F1", "<": "F2", "=": "F3", ">": "F4"}

    class raw_mode:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def get_key(timeout):
        end = time.monotonic() + timeout
        while True:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0"):
                    return _SPECIAL.get(msvcrt.getwch())
                if ch == "\x1b":
                    return "ESC"
                return ch
            if time.monotonic() >= end:
                return None
            time.sleep(0.02)

else:
    import select
    import termios
    import tty

    _SEQ = {"[A": "UP", "[B": "DOWN", "[C": "RIGHT", "[D": "LEFT",
            "OP": "F1", "OQ": "F2", "OR": "F3", "OS": "F4"}

    class raw_mode:
        def __enter__(self):
            self.fd = sys.stdin.fileno()
            self.saved = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
            return self

        def __exit__(self, *exc):
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)
            return False

    def get_key(timeout):
        fd = sys.stdin.fileno()
        if not select.select([fd], [], [], timeout)[0]:
            return None
        ch = os.read(fd, 1).decode(errors="ignore")
        if ch == "\x1b":
            seq = ""
            while select.select([fd], [], [], 0.02)[0] and len(seq) < 6:
                seq += os.read(fd, 1).decode(errors="ignore")
            return _SEQ.get(seq, "ESC" if not seq else None)
        if ch == "\x7f":
            return "\b"
        if ch == "\n":
            return "\r"
        return ch
