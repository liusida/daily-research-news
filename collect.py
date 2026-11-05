"""Collect new items from arXiv (cs.LG/cs.CL/cs.AI) and LessWrong/Alignment Forum.

Writes raw/YYYY-MM-DD.txt (for the agent) and raw/YYYY-MM-DD.json (for scripts).
Usage: uv run collect.py [--date YYYY-MM-DD] [--days 2]
arXiv: papers announced on DATE, from the "past week" listing pages (works up to ~1 week back).
Forums: posts from the full UTC day before DATE.
"""
import argparse, datetime as dt, json, re, xml.etree.ElementTree as ET
from pathlib import Path
import time
from zoneinfo import ZoneInfo
import requests
from tqdm import tqdm

UA = {"User-Agent": "news-digest/0.1 (personal research digest)"}
ARXIV_CATS = ["cs.LG", "cs.CL", "cs.AI"]
LW_GRAPHQL = "https://www.lesswrong.com/graphql"


def get_retry(url, **kw):
    for wait in (0, 10, 30, 60, 120, 240):  # back off if arXiv rate-limits us
        time.sleep(wait)
        r = requests.get(url, headers=UA, timeout=120, **kw)
        if r.status_code == 200:
            return r
    raise SystemExit(f"arXiv failed: HTTP {r.status_code} {r.text[:100]}")


def latest_listing_day():
    """Date label of the newest announced arXiv batch (e.g. 'Thu, 5 Nov 2026' -> 2026-11-05)."""
    html = get_retry(f"https://arxiv.org/list/{ARXIV_CATS[0]}/pastweek", params={"show": 25}).text
    label = html.split("<h3>")[1].split("(")[0].strip()
    return dt.datetime.strptime(label, "%a, %d %b %Y").date()


def fetch_arxiv_listing(day):
    """Papers announced on `day`, from arXiv's 'past week' listing pages (new + cross-lists)."""
    label = f"{day:%a}, {day.day} {day:%b %Y}"  # e.g. "Wed, 4 Nov 2026"
    ids = {}
    for cat in ARXIV_CATS:
        html = get_retry(f"https://arxiv.org/list/{cat}/pastweek", params={"show": 2000}).text
        for sec in html.split("<h3>")[1:]:
            if sec.split("(")[0].strip() == label:
                for aid in re.findall(r'href ?= ?"/abs/([0-9.]+)"', sec):
                    ids.setdefault(aid, []).append(cat)
        time.sleep(3)
    if not ids:
        raise SystemExit(f"No arXiv listing for {label} (weekend, or older than one week?)")
    ns = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
    items, idl = [], list(ids)
    for i in tqdm(range(0, len(idl), 200), desc="arXiv details"):
        chunk = idl[i:i + 200]
        root = ET.fromstring(get_retry("https://export.arxiv.org/api/query",
                                       params={"id_list": ",".join(chunk), "max_results": 200}).content)
        for e in root.findall("a:entry", ns):
            aid = re.sub(r"v\d+$", "", e.findtext("a:id", namespaces=ns).rsplit("/", 1)[-1])
            prim = e.find("x:primary_category", ns).get("term")
            items.append({"source": "arxiv", "title": " ".join(e.findtext("a:title", namespaces=ns).split()),
                          "url": "https://arxiv.org/abs/" + aid,
                          "authors": ", ".join(a.findtext("a:name", namespaces=ns) for a in e.findall("a:author", ns)),
                          "kind": "new" if prim in ARXIV_CATS else "cross", "cats": ids.get(aid, []),
                          "text": " ".join(e.findtext("a:summary", namespaces=ns).split())})
        time.sleep(3)
    print(f"arXiv listing '{label}': {len(ids)} ids, {len(items)} fetched")
    return items


def fetch_lesswrong(days, until=None):
    until = until or dt.datetime.now(dt.UTC)
    after = (until - dt.timedelta(days=days)).strftime("%Y-%m-%d")
    before = (until + dt.timedelta(days=1)).strftime("%Y-%m-%d")
    q = """query($after:String, $before:String){ posts(input:{terms:{view:"new", after:$after, before:$before, limit:500}}) { results {
      title pageUrl postedAt baseScore af tags { name } user { displayName }
      contents { plaintextDescription } } } }"""
    r = requests.post(LW_GRAPHQL, json={"query": q, "variables": {"after": after, "before": before}}, headers=UA, timeout=60)
    out = []
    for p in r.json()["data"]["posts"]["results"]:
        posted = dt.datetime.fromisoformat(p["postedAt"].replace("Z", "+00:00"))
        if not (until - dt.timedelta(days=days) <= posted < until):
            continue
        tags = [t["name"] for t in p.get("tags") or []]
        if not p["af"] and "AI" not in tags:  # keep AI-related posts and all AF posts
            continue
        text = ((p.get("contents") or {}).get("plaintextDescription") or "")[:1500]
        out.append({"source": "alignmentforum" if p["af"] else "lesswrong", "title": p["title"],
                    "url": p["pageUrl"], "authors": (p.get("user") or {}).get("displayName", ""),
                    "karma": p["baseScore"], "posted": p["postedAt"], "tags": tags, "text": text})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1, help="LessWrong/AF: number of full days before --date")
    ap.add_argument("--date", default=None, help="batch date to collect (default: newest arXiv batch)")
    ap.add_argument("--print-latest", action="store_true", help="only print the newest batch date")
    a = ap.parse_args()
    if a.print_latest:
        print(latest_listing_day().isoformat())
        return
    today = a.date or latest_listing_day().isoformat()
    day = dt.date.fromisoformat(today)
    arxiv = fetch_arxiv_listing(day)
    # Forums: the full UTC day(s) before the digest date, so days never overlap.
    lw = fetch_lesswrong(a.days, dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC))
    items = arxiv + lw
    Path("raw").mkdir(exist_ok=True)
    Path(f"raw/{today}.json").write_text(json.dumps(items, indent=1, ensure_ascii=False))
    with open(f"raw/{today}.txt", "w") as f:
        for i, x in enumerate(items, 1):
            meta = f"karma {x['karma']} | tags: {', '.join(x['tags'])}" if "karma" in x else f"{x['kind']} | {', '.join(x['cats'])}"
            f.write(f"[{i}] ({x['source']}) {x['title']}\n{x['url']}\n{x['authors']} | {meta}\n{x['text']}\n\n")
    kinds = {}
    for x in arxiv:
        kinds[x["kind"]] = kinds.get(x["kind"], 0) + 1
    print(f"arXiv: {len(arxiv)} papers {kinds}")
    print(f"LessWrong (AI): {sum(x['source']=='lesswrong' for x in lw)}, Alignment Forum: {sum(x['source']=='alignmentforum' for x in lw)}")
    print(f"LW/AF with karma>=20: {sum(x['karma']>=20 for x in lw)}")
    print(f"Wrote raw/{today}.txt ({Path(f'raw/{today}.txt').stat().st_size//1024} KB)")


if __name__ == "__main__":
    main()
