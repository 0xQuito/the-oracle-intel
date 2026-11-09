# THE ORACLE

A Ceefax-style teletext service for live cyber threat intelligence: new CVEs,
exploited vulnerabilities, indicators of compromise, ransomware victims and
data breaches. You move around by typing three-digit page numbers.

Pure Python standard library: nothing to install and no API keys.

## Run it

```
py -m intelfax          # classic 40-column teletext
py -m intelfax --wide   # 80 columns, more text per line
```

Or double-click `intelfax.bat`. Windows Terminal gives the best result. Make the
window at least 25 rows tall. Use `--basic-colors` if the colours look wrong.

### In your web browser

```
py -m intelfax --web
```

Or double-click `intelfax-web.bat`. It starts a small server on your own machine
(http://127.0.0.1:8040, not reachable from other computers) and opens your browser.
The screen is 80 x 32 characters by default and scales to fill the window, so
pages hold about twice as much as the terminal version. Change the size with
`--cols` and `--rows` (for example `--cols 100 --rows 40`), or add `?cols=100&rows=40`
to the address.

Extras in the browser:
- point at a link to highlight it, click to open it
- `O` opens the full story, CVE or breach page in a new tab
- every page has its own address (`#300`), so the browser's Back button and bookmarks work
- `S` turns the CRT scanlines on and off
- data refreshes quietly every 20 seconds while you're on a page

## Pages

| Page | What | Source |
|------|------|--------|
| 100 | Index | |
| 150 | Threat barometer (stats + level) | NVD, KEV, ransomware.live |
| 199 | Help | |
| 200 | Security news, stories 201-240 | BleepingComputer, The Hacker News, Krebs, SANS ISC |
| 300 | Latest CVEs, detail 301-349 | NIST NVD (last 3 days) |
| 350 | Critical CVEs (CVSS 9+), detail 351-399 | NIST NVD |
| 400 | Exploited in the wild, detail 401-449 | CISA KEV |
| 500 | IoC index | |
| 510 | C2 servers | abuse.ch Feodo Tracker, C2IntelFeeds |
| 520 | Phishing URLs | OpenPhish |
| 530 | Malicious SSL certificates | abuse.ch SSLBL |
| 540 | Compromised hosts | Emerging Threats |
| 600 | Ransomware leak-site victims, 601-649 | ransomware.live |
| 700 | Breaches added to HIBP, 701-749 | Have I Been Pwned |
| 800 | Breach news, 801-840 | DataBreaches.net |

## Keys

| Key | Action |
|-----|--------|
| `100`-`899` | go to a page (it jumps as soon as you type the third digit) |
| Arrow keys | move the highlight box between the links on the page, including the coloured links at the bottom |
| `Enter` | open the highlighted page |
| `N` / `P` | next / previous subpage (the `1/7` counter) |
| `+` / `-` | step to the next / previous page number |
| `R` `G` `Y` `C` or F1-F4 | the four coloured links along the bottom |
| `B` | back |
| `I` | index |
| `U` | update: refetch this page's feed |
| `V` | reveal: show IoCs un-defanged (`1.2.3[.]4` becomes `1.2.3.4`) |
| `Esc` | clear the number you're typing |
| `Q` | quit |

The arrow keys work the same on every page. Up / Down move to the row above or
below; going down past the coloured links turns to the next subpage, and going up
past the top turns back. Left / Right move along a row, and turn the subpage at
the end of it. The highlight remembers where it was, so `B` (back) lands you on
the item you came from.

Every feed starts loading in the background at launch and is cached for 15
minutes. If a page's data isn't ready yet, the header counter rolls through
page numbers like an old TV searching for the page.

## Testing without a terminal

`py -m intelfax --snapshot 300 --plain` prints one page as plain text and exits.
Add `--sub 2` to pick a subpage.

## Code layout

- `intelfax/teletext.py`: palette, rows, block-letter banners, ANSI output
- `intelfax/feeds.py`: fetchers for every source, background loading and caching
- `intelfax/pages.py`: page map and every page layout
- `intelfax/app.py`: screen drawing, keyboard handling, main loop
- `intelfax/nav.py`: arrow-key highlight rules (what can be selected, where the arrows go)
- `intelfax/keys.py`: single-keypress input on Windows and Unix
- `intelfax/web.py`: local web server for the browser version (same pages, sent as coloured text)
- `intelfax/web/index.html`: the browser screen, keyboard and clicks

To add a source, write a fetcher in `feeds.py`, add it to `FETCHERS`, then add a
page in `pages.py` (`SECTIONS` for list-plus-story feeds, `STATIC` for one-off pages).
