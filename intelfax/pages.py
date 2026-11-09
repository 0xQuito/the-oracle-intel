"""Every page in the service. A page builder returns a PageSpec; the app
splits its blocks into subpages and draws it.

Page map
  100 Index              150 Threat barometer      199 Help
  200 Security news      201-240 stories
  300 Latest CVEs        301-349 CVE pages
  350 Critical CVEs      351-399 CVE pages
  400 Exploited (KEV)    401-449 KEV pages
  500 IoC index          510 C2  520 Phishing  530 SSL certs  540 Compromised
  600 Ransomware victims 601-649
  700 HIBP breaches      701-749
  800 Breach news        801-840
"""

import collections
import datetime as dt
from dataclasses import dataclass, field

from .teletext import (BLACK, BLUE, CYAN, GREEN, MAGENTA, RED, WHITE, YELLOW,
                       Row, T, blank, clip, mosaic, para, split_lr, wrap)


@dataclass
class PageSpec:
    title: str
    banner: tuple = ("THE ORACLE", CYAN, BLUE)  # (word, fg, bg) for mosaic letters
    title_fg: tuple = YELLOW
    title_bg: tuple = BLUE
    blocks: list = field(default_factory=list)  # list of lists of Rows
    status: str = ""
    status_fg: tuple = CYAN
    fastext: list = field(default_factory=lambda: [("Index", 100), ("News", 200),
                                                   ("CVEs", 300), ("Breach", 600)])
    max_subpages: int = 0  # 0 = unlimited
    link: str = ""         # web version: the 'O' key opens this


# ---------------------------------------------------------------- helpers

def local(d):
    return d.astimezone() if d else None


def short_date(d):
    d = local(d)
    return d.strftime("%d %b %H:%M") if d else "--"


def long_date(d):
    d = local(d)
    return d.strftime("%d %b %Y %H:%M") if d else "unknown"


def iso_day(s):
    """'2026-11-06' -> '06 Nov 2026'."""
    try:
        return dt.date.fromisoformat(s[:10]).strftime("%d %b %Y")
    except (TypeError, ValueError):
        return s or "unknown"


def defang_url(u):
    return u.replace("https://", "hxxps://").replace("http://", "hxxp://").replace(".", "[.]")


def defang_ip(ip):
    head, sep, tail = ip.rpartition(".")
    return f"{head}[.]{tail}" if sep else ip


SEVERITY = {
    "CRITICAL": (WHITE, RED), "HIGH": (BLACK, MAGENTA), "MEDIUM": (BLACK, YELLOW),
    "LOW": (BLACK, GREEN), "NONE": (BLACK, CYAN), "": (WHITE, BLUE),
}


SHORT_SEV = {"CRITICAL": "CRIT", "HIGH": "HIGH", "MEDIUM": "MED", "LOW": "LOW", "NONE": "NONE"}


def severity_badge(score, sev):
    fg, bg = SEVERITY.get(sev, (WHITE, BLUE))
    if isinstance(score, (int, float)):
        return T(f" {score:4.1f} {SHORT_SEV.get(sev, sev[:4]):<4} ", fg, bg)
    return T(" NOT SCORED ", fg, bg)


def tidy_vector(v):
    """Drop the 'not defined' (X) metrics that bloat CVSS 4.0 vectors."""
    return "/".join(p for p in v.split("/") if not p.endswith(":X"))


def kv(label, value, width, fg=WHITE, label_fg=GREEN):
    """'Label     value' rows with the value wrapped under itself."""
    pad = 12
    lines = wrap(str(value), width - pad)
    rows = [Row(T(f" {label:<{pad - 1}}", label_fg), T(lines[0], fg))]
    rows += [Row(T(" " * pad + l, fg)) for l in lines[1:]]
    return rows


def heading(text, width, fg=BLACK, bg=CYAN):
    return Row(T(" " + text, fg), fill=bg)


def feed_problem(ctx, feed):
    """Blocks to show when a feed has no data."""
    err = ctx.feeds.error(feed)
    if err is None:
        return [[Row(T(" Fetching data...", YELLOW))]]
    rows = [Row(T(" SERVICE INTERRUPTION", WHITE, RED)), blank()]
    rows += para(f"Could not reach the {feed} feed:", ctx.W, CYAN, 1)
    rows += para(err, ctx.W, WHITE, 1)
    rows += [blank(), Row(T(" Press U to try again.", YELLOW))]
    return [rows]


def status_for(ctx, feed, source):
    if ctx.feeds.error(feed) and ctx.feeds.data(feed) is None:
        return f"{source} - offline"
    return f"{source} @ {ctx.feeds.updated(feed)}"


# --------------------------------------------------------- story sections

class Section:
    def __init__(self, base, feed, banner, title, source, items, index_rows, story,
                 limit=49, fastext=None, link=None):
        self.base, self.feed, self.banner, self.title, self.source = base, feed, banner, title, source
        self.items, self.index_rows, self.story, self.limit = items, index_rows, story, limit
        self.fastext = fastext
        self.link = link or (lambda item: "")

    def list(self, ctx):
        data = ctx.feeds.data(self.feed)
        return self.items(data)[: self.limit] if data else []

    def index_page(self, ctx):
        spec = PageSpec(self.title, banner=self.banner, status=status_for(ctx, self.feed, self.source))
        if self.fastext:
            spec.fastext = self.fastext
        items = self.list(ctx)
        if not items:
            spec.blocks = feed_problem(ctx, self.feed) if ctx.feeds.data(self.feed) is None \
                else [[Row(T(" Nothing reported in this period.", CYAN))]]
            return spec
        spec.blocks = [self.index_rows(self.base + i + 1, it, ctx) for i, it in enumerate(items)]
        return spec

    def story_page(self, ctx, n):
        if ctx.feeds.data(self.feed) is None:
            spec = PageSpec(self.title, banner=self.banner, status=status_for(ctx, self.feed, self.source))
            spec.blocks = feed_problem(ctx, self.feed)
            return spec
        items = self.list(ctx)
        i = n - self.base - 1
        if i >= len(items):
            return None
        title, rows = self.story(items[i], ctx)
        spec = PageSpec(title, banner=self.banner, status=status_for(ctx, self.feed, self.source),
                        fastext=[("Back", self.base), ("Prev", n - 1 if i else self.base),
                                 ("Next", n + 1 if i + 1 < len(items) else self.base), ("Index", 100)],
                        link=self.link(items[i]))
        spec.blocks = [[r] for r in rows]
        return spec


# News -------------------------------------------------------------------

def news_index_rows(n, it, ctx):
    W = ctx.W
    lines = wrap(it["title"], W - 4)
    if len(lines) > 2:
        lines = [lines[0], clip(lines[1] + " " + lines[2], W - 4)]
    rows = [Row(T(f"{n} ", YELLOW), T(lines[0])).link(n)]
    rows += [Row(T("    " + l)) for l in lines[1:]]
    rows.append(Row(T(f"    {it['source']:<11} ", GREEN), T(short_date(it["date"]), CYAN)))
    return rows


def news_story(it, ctx):
    W = ctx.W
    rows = [Row(T(" " + l, YELLOW)) for l in wrap(it["title"], W - 2)]
    rows.append(Row(T(f" {it['source']}", GREEN), T("  " + long_date(it["date"]), CYAN)))
    rows.append(blank())
    rows += para(it["summary"] or "No summary available.", W, WHITE, 1)
    rows.append(blank())
    rows.append(Row(T(" Full story:", GREEN)))
    rows += para(it["link"], W, CYAN, 1)
    return it["source"], rows


def news_items(data):
    return data["items"]


# CVEs -------------------------------------------------------------------

def cve_index_rows(n, c, ctx):
    W = ctx.W
    top = split_lr([T(f"{n} ", YELLOW), T(c["id"])], [severity_badge(c["score"], c["severity"])], W).link(n)
    desc = c["description"] or "No description yet."
    return [top, Row(T("    " + clip(desc, W - 4), CYAN))]


def cve_story(c, ctx):
    W = ctx.W
    fg, bg = SEVERITY.get(c["severity"], (WHITE, BLUE))
    score = f"{c['score']:.1f}" if isinstance(c["score"], (int, float)) else "N/A"
    ver = f"  (CVSS v{c['cvss_version']})" if c["cvss_version"] else ""
    rows = [Row(T(f" SCORE {score}  {c['severity'] or 'NOT YET SCORED'}{ver}", fg), fill=bg), blank()]
    rows += kv("Published", long_date(c["published"]), W)
    rows += kv("Status", c["status"] or "-", W)
    rows += kv("Reported", c["source"] or "-", W)
    if c["cwes"]:
        rows += kv("Weakness", ", ".join(c["cwes"]), W)
    if c["vector"]:
        rows += kv("Vector", tidy_vector(c["vector"]), W, CYAN)
    rows.append(blank())
    rows += para(c["description"] or "No description yet.", W, WHITE, 1)
    if c["refs"]:
        rows += [blank(), heading("REFERENCES", W)]
        for r in c["refs"]:
            rows += para(r, W, CYAN, 1)
    return c["id"], rows


def cve_recent(data):
    return data["items"]


def cve_critical(data):
    return [c for c in data["items"] if isinstance(c["score"], (int, float)) and c["score"] >= 9.0]


# KEV --------------------------------------------------------------------

def kev_index_rows(n, k, ctx):
    W = ctx.W
    right = [T(" RANSOM ", WHITE, RED)] if k["ransomware"] else []
    right.append(T(" " + iso_day(k["added"])[:6], CYAN))
    top = split_lr([T(f"{n} ", YELLOW), T(k["id"])], right, W).link(n)
    return [top, Row(T("    " + clip(f"{k['vendor']} {k['product']}", W - 4), GREEN))]


def kev_story(k, ctx):
    W = ctx.W
    rows = [Row(T(" ACTIVELY EXPLOITED", WHITE), fill=RED)]
    rows += [Row(T(" " + l, YELLOW)) for l in wrap(k["name"], W - 2)]
    rows.append(blank())
    rows += kv("Vendor", k["vendor"], W)
    rows += kv("Product", k["product"], W)
    rows += kv("Added", iso_day(k["added"]), W)
    rows += kv("Fix by", iso_day(k["due"]), W)
    rows += kv("Ransomware", "Known use" if k["ransomware"] else "Not known", W,
               RED if k["ransomware"] else WHITE)
    if k["cwes"]:
        rows += kv("Weakness", ", ".join(k["cwes"]), W)
    rows.append(blank())
    rows += para(k["description"], W, WHITE, 1)
    rows += [blank(), heading("REQUIRED ACTION", W)]
    rows += para(k["action"], W, WHITE, 1)
    if k["notes"]:
        rows += [blank(), heading("NOTES", W)]
        for part in k["notes"].split(" ; "):
            rows += para(part, W, CYAN, 1)
    return k["id"], rows


# Ransomware -------------------------------------------------------------

def ransom_index_rows(n, v, ctx):
    W = ctx.W
    return [Row(T(f"{n} ", YELLOW), T(clip(v["victim"], W - 4))).link(n),
            Row(T("    "), T(f"{clip(v['group'], 14):<15}", RED),
                T(f"{(v['country'] or '--'):<4}", CYAN), T(short_date(v["discovered"]), GREEN))]


def ransom_story(v, ctx):
    W = ctx.W
    rows = [Row(T(" " + l, YELLOW)) for l in wrap(v["victim"], W - 2)]
    rows.append(blank())
    rows += kv("Group", v["group"] or "?", W, RED)
    rows += kv("Country", v["country"] or "unknown", W)
    if v["sector"] and v["sector"].lower() != "not found":
        rows += kv("Sector", v["sector"], W)
    if v["domain"]:
        rows += kv("Domain", v["domain"], W, CYAN)
    rows += kv("Attacked", long_date(v["attacked"]), W)
    rows += kv("Posted", long_date(v["discovered"]), W)
    if v["description"]:
        rows.append(blank())
        rows += para(v["description"][:700], W, WHITE, 1)
    if v["url"]:
        rows += [blank(), Row(T(" More:", GREEN))]
        rows += para(v["url"], W, CYAN, 1)
    return f"{v['group'].upper()} LEAK SITE", rows


# HIBP -------------------------------------------------------------------

def hibp_index_rows(n, b, ctx):
    W = ctx.W
    return [Row(T(f"{n} ", YELLOW), T(clip(b["title"], W - 4))).link(n),
            Row(T("    "), T(f"{b['count']:,} ", WHITE), T("accounts  ", GREEN),
                T("added " + short_date(b["added"])[:6], CYAN))]


def hibp_story(b, ctx):
    W = ctx.W
    rows = [Row(T(" " + l, YELLOW)) for l in wrap(b["title"], W - 2)]
    rows.append(blank())
    rows += kv("Accounts", f"{b['count']:,}", W, WHITE)
    rows += kv("Domain", b["domain"] or "-", W, CYAN)
    rows += kv("Breached", iso_day(b["breach_date"]), W)
    rows += kv("Added", long_date(b["added"]), W)
    flags = [f for f, on in (("verified", b["verified"]), ("sensitive", b["sensitive"]),
                             ("spam list", b["spam"])) if on]
    rows += kv("Flags", ", ".join(flags) or "unverified", W)
    rows += [blank(), heading("DATA EXPOSED", W)]
    rows += para(", ".join(b["classes"]) or "-", W, WHITE, 1)
    rows.append(blank())
    rows += para(b["description"], W, WHITE, 1)
    return "HAVE I BEEN PWNED", rows


def nvd_link(item):
    return f"https://nvd.nist.gov/vuln/detail/{item['id']}"


SECTIONS = {
    200: Section(200, "news", ("NEWS", YELLOW, BLUE), "SECURITY NEWS",
                 "Bleeping/THN/Krebs/SANS", news_items, news_index_rows, news_story, 40,
                 [("Index", 100), ("Breach", 800), ("CVEs", 300), ("Level", 150)],
                 link=lambda it: it["link"]),
    300: Section(300, "nvd", ("CVE", WHITE, RED), "LATEST CVEs - PUBLISHED",
                 "NIST NVD", cve_recent, cve_index_rows, cve_story,
                 fastext=[("Index", 100), ("Critical", 350), ("Exploit", 400), ("Level", 150)],
                 link=nvd_link),
    350: Section(350, "nvd", ("CRITICAL", WHITE, RED), "CRITICAL CVEs (CVSS 9.0+)",
                 "NIST NVD", cve_critical, cve_index_rows, cve_story,
                 fastext=[("Index", 100), ("Latest", 300), ("Exploit", 400), ("Level", 150)],
                 link=nvd_link),
    400: Section(400, "kev", ("EXPLOITED", YELLOW, RED), "EXPLOITED IN THE WILD",
                 "CISA KEV", lambda d: d["items"], kev_index_rows, kev_story,
                 fastext=[("Index", 100), ("Latest", 300), ("Critical", 350), ("Level", 150)],
                 link=nvd_link),
    600: Section(600, "ransom", ("RANSOM", WHITE, MAGENTA), "RANSOMWARE LEAK-SITE VICTIMS",
                 "ransomware.live", lambda d: d["items"], ransom_index_rows, ransom_story,
                 fastext=[("Index", 100), ("HIBP", 700), ("News", 800), ("Level", 150)],
                 link=lambda v: v["url"]),
    700: Section(700, "hibp", ("BREACHES", WHITE, MAGENTA), "NEWLY LOADED BREACHES",
                 "haveibeenpwned.com", lambda d: d["items"], hibp_index_rows, hibp_story,
                 fastext=[("Index", 100), ("Ransom", 600), ("News", 800), ("Level", 150)],
                 link=lambda b: f"https://haveibeenpwned.com/Breach/{b['name']}" if b["name"] else ""),
    800: Section(800, "breachnews", ("BREACH", WHITE, MAGENTA), "DATA BREACH NEWS",
                 "databreaches.net", news_items, news_index_rows, news_story, 40,
                 fastext=[("Index", 100), ("Ransom", 600), ("HIBP", 700), ("News", 200)],
                 link=lambda it: it["link"]),
}


# --------------------------------------------------------------- IoC pages

IOC_FASTEXT = [("IoCs", 500), ("C2", 510), ("Phish", 520), ("Index", 100)]


def ioc_page(ctx, feed, title, source, rows_fn, max_sub=12):
    spec = PageSpec(title, banner=("IOC", BLACK, GREEN), title_fg=BLACK, title_bg=GREEN,
                    status=status_for(ctx, feed, source), fastext=IOC_FASTEXT, max_subpages=max_sub)
    if ctx.reveal:
        spec.status, spec.status_fg = "REVEALED - live indicators, take care", RED
    data = ctx.feeds.data(feed)
    spec.blocks = rows_fn(data) if data else feed_problem(ctx, feed)
    return spec


def side_by_side(rows, W, cell):
    """Lay single rows out in columns across a wide screen."""
    per = max(1, W // cell)
    out = []
    for i in range(0, len(rows), per):
        spans = []
        for r in rows[i:i + per]:
            spans += r.spans + [T(" " * max(0, cell - r.length()))]
        out.append([Row(*spans)])
    return out


def page_c2(ctx):
    W = ctx.W
    cell = 40 if W >= 80 else W

    def rows(data):
        out = []
        for it in data["items"]:
            ioc = it["ioc"] if ctx.reveal else defang_ip(it["ioc"].split(":")[0]) + (
                ":" + it["ioc"].split(":")[1] if ":" in it["ioc"] else "")
            right = [T(clip(it["label"], 14), YELLOW)]
            if it["status"]:
                right.append(T(" ON" if it["status"] == "online" else " --",
                               GREEN if it["status"] == "online" else CYAN))
            right.append(T(" "))
            out.append(split_lr([T(" " + ioc)], right, cell))
        return side_by_side(out, W, cell)
    return ioc_page(ctx, "c2", "COMMAND & CONTROL SERVERS", "Feodo Tracker, C2IntelFeeds", rows)


def page_phish(ctx):
    W = ctx.W

    def rows(data):
        out = []
        for i, u in enumerate(data["items"]):
            lines = wrap(u if ctx.reveal else defang_url(u), W - 3)
            if len(lines) > 2:
                lines = [lines[0], clip("".join(lines[1:]), W - 3)]
            fg = WHITE if i % 2 else CYAN
            out.append([Row(T(" " + lines[0], fg))] + [Row(T("   " + l, fg)) for l in lines[1:]])
        return out
    return ioc_page(ctx, "phish", "PHISHING URLs - LIVE", "OpenPhish community feed", rows)


def page_ssl(ctx):
    W = ctx.W

    def rows(data):
        return [[Row(T(f" {iso_day(i['date'])[:6]} ", GREEN), T(clip(i["reason"], W - 9), YELLOW)),
                 Row(T(i["sha1"][: W], CYAN))] for i in data["items"]]
    return ioc_page(ctx, "sslbl", "MALICIOUS SSL CERTS (SHA1)", "abuse.ch SSLBL", rows)


def page_compromised(ctx):
    W = ctx.W
    cell = W // max(2, W // 20)

    def rows(data):
        ips = [ip if ctx.reveal else defang_ip(ip) for ip in data["items"]]
        cells = [Row(T(f" {ip}", CYAN if i % 2 else WHITE)) for i, ip in enumerate(ips)]
        return side_by_side(cells, W, cell)
    return ioc_page(ctx, "compromised", "KNOWN COMPROMISED HOSTS", "Emerging Threats", rows)


def page_ioc_index(ctx):
    W = ctx.W
    spec = PageSpec("INDICATORS OF COMPROMISE", banner=("IOC", BLACK, GREEN), title_fg=BLACK,
                    title_bg=GREEN, status="Indicators are defanged.  V = reveal",
                    fastext=[("C2", 510), ("Phish", 520), ("SSL", 530), ("Index", 100)])
    entries = [
        (510, "C2 servers", "c2", "Botnet and Cobalt Strike controllers"),
        (520, "Phishing URLs", "phish", "Live phishing pages"),
        (530, "SSL blacklist", "sslbl", "Certs used by malware C2"),
        (540, "Compromised", "compromised", "Hosts seen attacking others"),
    ]
    blocks = []
    for n, name, feed, desc in entries:
        data = ctx.feeds.data(feed)
        count = f"{len(data['items'])} live" if data else ("offline" if ctx.feeds.error(feed) else "...")
        blocks.append([split_lr([T(f" {n} ", YELLOW), T(name)], [T(count + " ", GREEN)], W).link(n),
                       Row(T("     " + clip(desc, W - 5), CYAN)), blank()])
    blocks.append(para("Defanged indicators like 1.2.3[.]4 and hxxp:// cannot be clicked by "
                       "accident. Press V to reveal them, like the teletext REVEAL button.", W, WHITE, 1))
    spec.blocks = blocks
    return spec


# ----------------------------------------------------------- static pages

def index_row(left, right, W):
    col = W // 2

    def cell(entry):
        if not entry:
            return [T(" " * col)]
        if isinstance(entry, str):
            return [T(f" {entry:<{col - 1}}", CYAN)]
        name, n = entry
        label = min(col - 5, 18)
        return [T(f" {name:<{label}}", WHITE), T(f"{n}", YELLOW), T(" " * (col - label - 4))]
    row = Row(*cell(left), *cell(right))
    for i, entry in enumerate((left, right)):
        if isinstance(entry, tuple):
            row.link(entry[1], i * col, (i + 1) * col)
    return row


def page_index(ctx):
    W = ctx.W
    spec = PageSpec("GLOBAL CYBER THREAT INTELLIGENCE",
                    fastext=[("News", 200), ("CVEs", 300), ("IoCs", 500), ("Breach", 600)])
    news = ctx.feeds.data("news")
    top = []
    if news and news["items"] and W >= 60:
        # Wide screens: one line per headline, as many as fit.
        count = max(1, min(6, ctx.H - 15))
        top = [Row(T(f"{201 + i} ", YELLOW), T(clip(it["title"], W - 4))).link(201 + i)
               for i, it in enumerate(news["items"][:count])]
    elif news and news["items"]:
        lines = wrap(news["items"][0]["title"], W - 4)[:2]
        top = [Row(T("201 ", YELLOW), T(lines[0], WHITE)).link(201)] + [Row(T("    " + l)) for l in lines[1:]]
    else:
        top = [Row(T(" Headlines loading...", CYAN))]
    while len(top) < 2:
        top.append(blank())
    layout = [
        ("NEWS", "INDICATORS"),
        (("Headlines", 200), ("C2 servers", 510)),
        (("Breach news", 800), ("Phishing", 520)),
        (None, ("SSL certs", 530)),
        ("VULNERABILITIES", ("Compromised", 540)),
        (("Latest CVEs", 300), None),
        (("Critical", 350), "BREACHES"),
        (("Exploited", 400), ("Ransomware", 600)),
        (None, ("Pwned dbs", 700)),
        ("SERVICE", None),
        (("Threat level", 150), ("Help", 199)),
    ]
    rows = top + [blank()] + [index_row(l, r, W) for l, r in layout] + [blank()]
    level = threat_level(ctx)
    if level:
        name, _, fg, bg = level
        rows.append(split_lr([T(" THREAT LEVEL", WHITE)], [T(f" {name} ", fg, bg), T(" 150 ", YELLOW)], W).link(150))
    spec.blocks = [rows]
    spec.status = "Arrows + Enter, or type a number"
    return spec


LEVELS = [(20, "LOW", BLACK, GREEN), (40, "GUARDED", BLACK, CYAN), (70, "ELEVATED", BLACK, YELLOW),
          (110, "HIGH", WHITE, MAGENTA), (10 ** 9, "SEVERE", WHITE, RED)]


def _stats(ctx):
    s = {}
    nvd, kev, ransom = ctx.feeds.data("nvd"), ctx.feeds.data("kev"), ctx.feeds.data("ransom")
    t = dt.datetime.now(dt.timezone.utc)
    if nvd:
        s["cves"] = nvd["total"]
        s["critical"] = len(cve_critical(nvd))
    if kev:
        week = (t - dt.timedelta(days=7)).date().isoformat()
        month = (t - dt.timedelta(days=30)).date().isoformat()
        s["kev7"] = sum(1 for k in kev["items"] if k["added"] >= week)
        s["vendors"] = collections.Counter(k["vendor"] for k in kev["items"] if k["added"] >= month)
    if ransom:
        day = t - dt.timedelta(days=1)
        s["ransom24"] = sum(1 for v in ransom["items"] if v["discovered"] and v["discovered"] >= day)
        s["groups"] = collections.Counter(v["group"] for v in ransom["items"])
    return s


def threat_level(ctx):
    s = _stats(ctx)
    if not {"critical", "kev7", "ransom24"} <= s.keys():
        return None
    score = s["critical"] + 4 * s["kev7"] + s["ransom24"] // 2
    for limit, name, fg, bg in LEVELS:
        if score < limit:
            return name, score, fg, bg


def bars(counter, n, W, fg):
    top = counter.most_common(n)
    if not top:
        return [Row(T(" no data", CYAN))]
    peak = top[0][1]
    room = W - 18
    return [Row(T(f" {clip(name, 12):<13}", WHITE), T("█" * max(1, round(c / peak * room)), fg),
                T(f" {c}", YELLOW)) for name, c in top]


def page_barometer(ctx):
    W = ctx.W
    level = threat_level(ctx)
    banner = (level[0], level[2], level[3]) if level else ("LEVEL", WHITE, BLUE)
    spec = PageSpec("THREAT BAROMETER", banner=banner,
                    fastext=[("Index", 100), ("Critical", 350), ("Exploit", 400), ("Ransom", 600)])
    s = _stats(ctx)

    def stat(label, key, page):
        v = s.get(key)
        return split_lr([T(f" {label}", CYAN)], [T(f"{v if v is not None else '...':>5}", WHITE),
                                                  T(f" {page} ", YELLOW)], W).link(page)
    rows = [stat("CVEs published, 3 days", "cves", 300),
            stat("Critical CVEs (9.0+)", "critical", 350),
            stat("KEV additions, 7 days", "kev7", 400),
            stat("Ransom victims, 24 hrs", "ransom24", 600), blank()]
    extra = max(0, ctx.H - 17)  # taller screens get longer charts
    rows.append(heading("BUSIEST RANSOM GROUPS", W, WHITE, MAGENTA))
    rows += bars(s.get("groups", collections.Counter()), 5 + extra // 2, W, RED)
    rows.append(heading("MOST EXPLOITED VENDORS, 30 DAYS", W, WHITE, RED))
    rows += bars(s.get("vendors", collections.Counter()), 4 + extra - extra // 2, W, YELLOW)
    spec.blocks = [rows]
    spec.status = "Level = criticals + 4x KEV + ransom/2" if level else "Gathering figures..."
    return spec


def page_help(ctx):
    W = ctx.W
    spec = PageSpec("HOW TO USE THE ORACLE", banner=("HELP", YELLOW, BLUE), status="Press 100 for the index")
    keys = [("100-899", "go to that page"), ("Arrows", "move the highlight box"),
            ("Enter", "open the highlighted page"), ("N / P", "next / previous subpage"),
            ("+ / -", "step through page numbers"), ("R G Y C", "coloured links (or F1-F4)"),
            ("B", "back to previous page"), ("I", "index (page 100)"), ("U", "update: refetch the feed"),
            ("V", "reveal / hide live IoCs"), ("Esc", "clear what you typed"), ("Q", "quit")]
    rows = [heading("KEYS", W)]
    rows += [Row(T(f" {k:<9}", YELLOW), T(clip(v, W - 10))) for k, v in keys]
    blocks = [rows, [blank(), heading("SOURCES (free, no API keys)", W)]]
    for name, what in [("NIST NVD", "new CVEs, 300 & 350"), ("CISA KEV", "exploited bugs, 400"),
                       ("BleepingComputer", "news, 200"), ("The Hacker News", "news, 200"),
                       ("Krebs / SANS ISC", "news, 200"), ("ransomware.live", "victims, 600"),
                       ("HaveIBeenPwned", "breaches, 700"), ("DataBreaches.net", "breach news, 800"),
                       ("abuse.ch", "C2 + SSL, 510 & 530"), ("C2IntelFeeds", "C2 servers, 510"),
                       ("OpenPhish", "phishing, 520"), ("EmergingThreats", "bad hosts, 540")]:
        blocks.append([Row(T(f" {name:<17}", GREEN), T(clip(what, W - 18), CYAN))])
    blocks.append([blank()] + para("Feeds refresh every 15 minutes. The threat level on 150 is a rough "
                                   "heuristic, not an official rating.", W, WHITE, 1))
    spec.blocks = blocks
    return spec


# ------------------------------------------------------------------ lookup

STATIC = {
    100: ([], page_index),
    150: (["nvd", "kev", "ransom"], page_barometer),
    199: ([], page_help),
    500: ([], page_ioc_index),
    510: (["c2"], page_c2),
    520: (["phish"], page_phish),
    530: (["sslbl"], page_ssl),
    540: (["compromised"], page_compromised),
}

ALL_FEEDS = ["news", "nvd", "kev", "ransom", "hibp", "breachnews", "c2", "phish", "sslbl", "compromised"]


def resolve(n):
    """-> (feeds the page needs, builder(ctx) -> PageSpec or None), or None."""
    if n in STATIC:
        return STATIC[n]
    if n in SECTIONS:
        sec = SECTIONS[n]
        return [sec.feed], sec.index_page
    for base, sec in SECTIONS.items():
        if base < n <= base + sec.limit:
            return [sec.feed], (lambda ctx, sec=sec: sec.story_page(ctx, n))
    return None


def exists(n, ctx):
    """For +/- stepping: is there something on page n right now?"""
    r = resolve(n)
    if r is None:
        return False
    for base, sec in SECTIONS.items():
        if base < n <= base + sec.limit:
            return n - base <= len(sec.list(ctx))
    return True


def not_found(n):
    spec = PageSpec(f"PAGE {n}", banner=("THE ORACLE", CYAN, BLUE), status="Page not in service")
    spec.blocks = [[blank(), Row(T(f" Page {n} is not in service.", YELLOW)), blank(),
                    Row(T(" Try the index on page "), T("100", YELLOW)).link(100),
                    Row(T(" or the help page on "), T("199", YELLOW)).link(199)]]
    return spec
