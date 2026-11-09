"""Arrow-key selection: what on a page can be picked, and where the
highlight goes when an arrow key is pressed.

The browser has a JavaScript copy of move() and resolve() in web/index.html.
If you change the rules here, change them there too.

Rules (the same on every page):
  Up / Down     move to the nearest item in the row above / below. The coloured
                links bar at the bottom counts as a row. Down from the bar turns
                to the next subpage; Up from the top turns back to the previous one.
  Left / Right  move along the row. At the end of a row they turn the subpage.
  Enter         go to the highlighted page.
"""

from .teletext import CYAN, GREEN, RED, WHITE, YELLOW

FASTEXT_COLOURS = [RED, GREEN, YELLOW, CYAN]
HIGHLIGHT = WHITE  # body items turn black-on-white when highlighted
BANNER_ROWS = 4    # three rows of block letters + the title bar


def selectables(spec, subs, sub, W, H):
    """Everything pickable on the current subpage, top to bottom, left to right.
    'row' counts from the top of the banner (0), the same rows body_rows() returns,
    with the status row at BANNER_ROWS + H and the coloured links at BANNER_ROWS + H + 1."""
    items = []
    for i, row in enumerate(subs[sub]):
        for page, start, end in row.links:
            items.append({"row": BANNER_ROWS + i, "start": start,
                          "end": W if end is None else min(end, W),
                          "page": page, "hl": HIGHLIGHT, "fast": False})
    cell = W // 4
    for i, (_, page) in enumerate(spec.fastext[:4]):
        items.append({"row": BANNER_ROWS + H + 1, "start": i * cell, "end": (i + 1) * cell,
                      "page": page, "hl": FASTEXT_COLOURS[i], "fast": True})
    items.sort(key=lambda it: (it["row"], it["start"]))
    return items


def _centre(it):
    return (it["start"] + it["end"]) / 2


def anchor(it):
    """The column the highlight 'is in': just inside the item's left edge,
    so moving up and down stays in the same column of a two-column page."""
    return it["start"] + 1


def _covers(it, x):
    return it["start"] <= x < it["end"]


def _nearest(items, idxs, x):
    inside = [j for j in idxs if _covers(items[j], x)]
    return inside[0] if inside else min(idxs, key=lambda j: abs(_centre(items[j]) - x))


def resolve(items, where):
    """Turn a 'where' from move() (or a remembered index) into an item index.
    where is an int, or (kind, x) with kind 'first', 'last' or 'bar'."""
    if not items:
        return 0
    if isinstance(where, int):
        return max(0, min(where, len(items) - 1))
    kind, x = where
    body = [j for j, it in enumerate(items) if not it["fast"]]
    if kind == "first" and body:
        return body[0]
    if kind == "last" and body:
        return body[-1]
    bar = [j for j, it in enumerate(items) if it["fast"]]
    return _nearest(items, bar, x) if bar else 0


def move(items, i, key, sub, nsubs):
    """-> (subpage change, where). key is UP, DOWN, LEFT or RIGHT."""
    cur = items[i]
    x = anchor(cur)
    if key in ("UP", "DOWN"):
        d = 1 if key == "DOWN" else -1
        rows = sorted({it["row"] for it in items if (it["row"] - cur["row"]) * d > 0}, reverse=d < 0)
        if rows:
            # prefer the nearest row with something in this column, else just the nearest row
            same_col = [r for r in rows if any(it["row"] == r and _covers(it, x) for it in items)]
            row = same_col[0] if same_col else rows[0]
            return 0, _nearest(items, [j for j, it in enumerate(items) if it["row"] == row], x)
        if d > 0:
            return (1 if nsubs > 1 else 0), ("first", x)
        return (-1, ("last", x)) if sub > 0 else (0, ("bar", x))
    d = 1 if key == "RIGHT" else -1
    same = [j for j, it in enumerate(items) if it["row"] == cur["row"]]
    k = same.index(i) + d
    if 0 <= k < len(same):
        return 0, same[k]
    if cur["fast"]:
        return 0, same[k % len(same)]
    if nsubs > 1:
        return d, ("first", x)
    return 0, i
