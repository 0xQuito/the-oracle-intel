"""Threat-intel fetchers. Every source is free and needs no API key.
Each fetch runs in a background thread and is cached for CACHE_TTL seconds."""

import concurrent.futures
import datetime as dt
import email.utils
import json
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET

from .teletext import clean

UA = "Mozilla/5.0 (compatible; intelfax-teletext/1.0)"
CACHE_TTL = 15 * 60
RETRY_AFTER = 60  # seconds to wait before retrying a failed feed automatically
UTC = dt.timezone.utc

NEWS_SOURCES = [
    ("BLEEPING", "https://www.bleepingcomputer.com/feed/"),
    ("HACKERNEWS", "https://feeds.feedburner.com/TheHackersNews"),
    ("KREBS", "https://krebsonsecurity.com/feed/"),
    ("SANS ISC", "https://isc.sans.edu/rssfeed_full.xml"),
]
BREACH_NEWS_SOURCES = [
    ("DATABREACH", "https://databreaches.net/feed/"),
]


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def now():
    return dt.datetime.now(UTC)


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


# ------------------------------------------------------------------ news

def _parse_rss(raw, source):
    root = ET.fromstring(raw)
    items = []
    atom = "{http://www.w3.org/2005/Atom}"
    for it in root.iter("item"):
        items.append({
            "title": clean(it.findtext("title")),
            "link": (it.findtext("link") or "").strip(),
            "date": parse_date(it.findtext("pubDate")),
            "summary": clean(it.findtext("description"))[:900],
            "source": source,
        })
    for it in root.iter(atom + "entry"):
        link = it.find(atom + "link")
        items.append({
            "title": clean(it.findtext(atom + "title")),
            "link": link.get("href", "") if link is not None else "",
            "date": parse_date(it.findtext(atom + "updated") or it.findtext(atom + "published")),
            "summary": clean(it.findtext(atom + "summary") or it.findtext(atom + "content"))[:900],
            "source": source,
        })
    return [i for i in items if i["title"]]


def _fetch_rss_group(sources, limit):
    items, errors = [], []
    with concurrent.futures.ThreadPoolExecutor(len(sources)) as pool:
        futures = {pool.submit(http_get, url): name for name, url in sources}
        for fut in concurrent.futures.as_completed(futures):
            name = futures[fut]
            try:
                items.extend(_parse_rss(fut.result(), name))
            except Exception as e:  # one dead feed shouldn't sink the page
                errors.append(f"{name}: {e}")
    if not items:
        raise RuntimeError("; ".join(errors) or "no stories")
    epoch = dt.datetime(1970, 1, 1, tzinfo=UTC)
    items.sort(key=lambda i: i["date"] or epoch, reverse=True)
    return {"items": items[:limit], "errors": errors}


def fetch_news():
    return _fetch_rss_group(NEWS_SOURCES, 40)


def fetch_breach_news():
    return _fetch_rss_group(BREACH_NEWS_SOURCES, 40)


# ------------------------------------------------------------------ CVEs

def _cvss(metrics):
    """Pick the best available CVSS score: v3.1, then v4.0, v3.0, v2."""
    for key, label in (("cvssMetricV31", "3.1"), ("cvssMetricV40", "4.0"),
                       ("cvssMetricV30", "3.0"), ("cvssMetricV2", "2.0")):
        entries = metrics.get(key) or []
        if not entries:
            continue
        entries = sorted(entries, key=lambda e: e.get("type") != "Primary")
        e = entries[0]
        d = e.get("cvssData", {})
        sev = d.get("baseSeverity") or e.get("baseSeverity") or ""
        return d.get("baseScore"), sev.upper(), d.get("vectorString", ""), label
    return None, "", "", ""


def _parse_cve(c):
    desc = next((d["value"] for d in c.get("descriptions", []) if d.get("lang") == "en"), "")
    score, sev, vector, ver = _cvss(c.get("metrics", {}))
    cwes = []
    for w in c.get("weaknesses", []):
        for d in w.get("description", []):
            v = d.get("value", "")
            if v.startswith("CWE-") and v not in cwes:
                cwes.append(v)
    return {
        "id": c.get("id", "?"),
        "published": parse_date(c.get("published")),
        "status": c.get("vulnStatus", ""),
        "source": c.get("sourceIdentifier", ""),
        "description": clean(desc),
        "score": score, "severity": sev, "vector": vector, "cvss_version": ver,
        "cwes": cwes,
        "refs": [r.get("url", "") for r in c.get("references", [])][:6],
    }


def fetch_nvd():
    """CVEs published in the last 3 days (newest 1000 at most)."""
    base = "https://services.nvd.nist.gov/rest/json/cves/2.0"
    end = now()
    fmt = "%Y-%m-%dT%H:%M:%S.000"
    q = f"pubStartDate={(end - dt.timedelta(days=3)).strftime(fmt)}&pubEndDate={end.strftime(fmt)}"
    total = json.loads(http_get(f"{base}?{q}&resultsPerPage=1"))["totalResults"]
    items = []
    if total:
        n = min(total, 1000)
        data = json.loads(http_get(f"{base}?{q}&resultsPerPage={n}&startIndex={total - n}", timeout=90))
        items = [_parse_cve(v["cve"]) for v in data.get("vulnerabilities", [])]
        items = [i for i in items if i["status"] != "Rejected"]
    epoch = dt.datetime(1970, 1, 1, tzinfo=UTC)
    items.sort(key=lambda i: i["published"] or epoch, reverse=True)
    return {"total": total, "items": items}


def fetch_kev():
    data = json.loads(http_get(
        "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json", timeout=60))
    vulns = data.get("vulnerabilities", [])
    vulns.sort(key=lambda v: (v.get("dateAdded", ""), v.get("cveID", "")), reverse=True)
    items = [{
        "id": v.get("cveID", "?"),
        "vendor": clean(v.get("vendorProject")),
        "product": clean(v.get("product")),
        "name": clean(v.get("vulnerabilityName")),
        "added": v.get("dateAdded", ""),
        "due": v.get("dueDate", ""),
        "description": clean(v.get("shortDescription")),
        "action": clean(v.get("requiredAction")),
        "ransomware": v.get("knownRansomwareCampaignUse", "") == "Known",
        "notes": clean(v.get("notes")),
        "cwes": v.get("cwes") or [],
    } for v in vulns]
    return {"total": len(vulns), "items": items, "version": data.get("catalogVersion", "")}


# ---------------------------------------------------------------- breaches

def fetch_ransom():
    data = json.loads(http_get("https://api.ransomware.live/v2/recentvictims"))
    items = [{
        "victim": clean(v.get("victim")) or "(unnamed)",
        "group": clean(v.get("group")),
        "country": clean(v.get("country")),
        "sector": clean(v.get("activity")),
        "attacked": parse_date(v.get("attackdate")),
        "discovered": parse_date(v.get("discovered")),
        "description": clean(v.get("description")),
        "domain": clean(v.get("domain")),
        "url": v.get("url") or "",
    } for v in data]
    epoch = dt.datetime(1970, 1, 1, tzinfo=UTC)
    items.sort(key=lambda i: i["discovered"] or epoch, reverse=True)
    return {"items": items}


def fetch_hibp():
    data = json.loads(http_get("https://haveibeenpwned.com/api/v3/breaches", timeout=60))
    data.sort(key=lambda b: b.get("AddedDate", ""), reverse=True)
    items = [{
        "title": clean(b.get("Title")),
        "name": clean(b.get("Name")),
        "domain": clean(b.get("Domain")),
        "breach_date": b.get("BreachDate", ""),
        "added": parse_date(b.get("AddedDate")),
        "count": b.get("PwnCount") or 0,
        "classes": [clean(c) for c in b.get("DataClasses", [])],
        "description": clean(b.get("Description")),
        "verified": b.get("IsVerified", False),
        "sensitive": b.get("IsSensitive", False),
        "spam": b.get("IsSpamList", False),
    } for b in data[:60]]
    return {"items": items, "total": len(data)}


# -------------------------------------------------------------------- IoCs

def fetch_c2():
    items = []
    try:
        for e in json.loads(http_get("https://feodotracker.abuse.ch/downloads/ipblocklist.json")):
            items.append({"ioc": f"{e['ip_address']}:{e.get('port', '')}",
                          "label": e.get("malware", "?"), "status": e.get("status", "")})
    except Exception:
        pass
    raw = http_get("https://raw.githubusercontent.com/drb-ra/C2IntelFeeds/master/feeds/IPC2s-30day.csv")
    for line in raw.decode(errors="ignore").splitlines():
        if not line or line.startswith("#") or "," not in line:
            continue
        ip, label = line.split(",", 1)
        label = label.replace("Possible ", "").replace(" C2 IP", "").replace(" C2", "").strip()
        items.append({"ioc": ip.strip(), "label": label, "status": ""})
    return {"items": items}


def fetch_phish():
    raw = http_get("https://openphish.com/feed.txt").decode(errors="ignore")
    return {"items": [u.strip() for u in raw.splitlines() if u.strip()]}


def fetch_sslbl():
    raw = http_get("https://sslbl.abuse.ch/blacklist/sslblacklist.csv").decode(errors="ignore")
    items = []
    for line in raw.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split(",", 2)
        if len(parts) == 3:
            items.append({"date": parts[0][:10], "sha1": parts[1], "reason": clean(parts[2])})
    items.sort(key=lambda i: i["date"], reverse=True)
    return {"items": items[:200], "total": len(items)}


def fetch_compromised():
    raw = http_get("https://rules.emergingthreats.net/blockrules/compromised-ips.txt").decode(errors="ignore")
    ips = [l.strip() for l in raw.splitlines() if l.strip() and not l.startswith("#")]
    return {"items": ips}


FETCHERS = {
    "news": fetch_news,
    "breachnews": fetch_breach_news,
    "nvd": fetch_nvd,
    "kev": fetch_kev,
    "ransom": fetch_ransom,
    "hibp": fetch_hibp,
    "c2": fetch_c2,
    "phish": fetch_phish,
    "sslbl": fetch_sslbl,
    "compromised": fetch_compromised,
}


# ----------------------------------------------------------------- manager

class FeedState:
    def __init__(self):
        self.data = None
        self.error = None
        self.fetched_at = 0.0
        self.failed_at = 0.0
        self.loading = False


class FeedManager:
    def __init__(self):
        self.states = {name: FeedState() for name in FETCHERS}
        self.version = 0
        self._lock = threading.Lock()

    def request(self, name, force=False):
        st = self.states[name]
        with self._lock:
            if st.loading:
                return
            t = time.time()
            if not force:
                if st.data is not None and t - st.fetched_at < CACHE_TTL:
                    return
                if st.error and t - st.failed_at < RETRY_AFTER:
                    return
            st.loading = True
        threading.Thread(target=self._run, args=(name,), daemon=True).start()

    def _run(self, name):
        st = self.states[name]
        try:
            data = FETCHERS[name]()
            st.data, st.error, st.fetched_at = data, None, time.time()
        except Exception as e:
            st.error, st.failed_at = (str(e) or type(e).__name__)[:200], time.time()
        finally:
            st.loading = False
            with self._lock:
                self.version += 1

    def data(self, name):
        return self.states[name].data

    def error(self, name):
        return self.states[name].error

    def pending(self, name):
        """True while we have nothing to show yet but an answer is coming."""
        st = self.states[name]
        return st.data is None and st.error is None

    def updated(self, name):
        t = self.states[name].fetched_at
        return dt.datetime.fromtimestamp(t).strftime("%H:%M") if t else "--:--"
