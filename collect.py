"""Collect items: arXiv papers liked on alphaXiv, and LessWrong/Alignment Forum posts.

Writes raw/YYYY-MM-DD.txt (for the agent) and raw/YYYY-MM-DD.json (for scripts).
Usage: uv run collect.py [--date YYYY-MM-DD] [--days N]
arXiv: papers with >= MIN_LIKES likes on alphaXiv (last 30 days) not seen on an earlier date
  (first run: only papers from the last 7 days).
  alphaXiv likes are live, so run this for today; past dates would use today's likes.
Forums: posts from the full UTC day before DATE.
"""
import argparse, datetime as dt, json, re, xml.etree.ElementTree as ET
from pathlib import Path
import time
import requests
from tqdm import tqdm

UA = {"User-Agent": "news-digest/0.1 (personal research digest)"}
MIN_LIKES = 10  # alphaXiv likes a paper needs before we look at it
LW_GRAPHQL = "https://www.lesswrong.com/graphql"


def get_retry(url, **kw):
    for wait in (0, 10, 30, 60, 120, 240):  # back off if arXiv rate-limits us
        time.sleep(wait)
        r = requests.get(url, headers=UA, timeout=120, **kw)
        if r.status_code == 200:
            return r
    raise SystemExit(f"arXiv failed: HTTP {r.status_code} {r.text[:100]}")


def target_day():
    """Date of the next digest: today (UTC). alphaXiv likes and forum posts come in every day."""
    return dt.datetime.now(dt.UTC).date()


def seen_before(day):
    """arXiv IDs that had enough likes on an earlier date (featured or not), from raw/DATE.alphaxiv.json.
    Each paper is judged once. Returns None on the first run, when there is no earlier list."""
    files = [f for f in Path("raw").glob("????-??-??.alphaxiv.json") if f.name[:10] < day.isoformat()]
    if not files:
        return None
    seen = set().union(*(json.loads(f.read_text()) for f in files))
    for f in files:  # also every paper we actually judged that day (the feed's paging can miss a few)
        seen |= {x["url"].rsplit("/", 1)[-1] for x in json.loads(Path(f"raw/{f.name[:10]}.json").read_text())
                 if x["source"] == "arxiv"}
    return seen


def fetch_alphaxiv_liked(day, min_likes=MIN_LIKES):
    """arXiv papers with >= min_likes on alphaXiv (last 30 days), not seen on an earlier date.
    alphaXiv gives only the IDs and likes; titles, authors and abstracts come from the arXiv API."""
    likes, published, page = {}, {}, 0
    while True:
        r = requests.get("https://api.alphaxiv.org/papers/v3/feed", headers=UA, timeout=60, params={
            "pageNum": str(page), "pageSize": "100", "sort": "Likes", "interval": "30 Days"})
        r.raise_for_status()
        papers = r.json()["papers"]
        for p in papers:
            v = (p.get("metrics") or {}).get("public_total_votes", 0)
            aid = p.get("universal_paper_id", "")
            if v >= min_likes and re.fullmatch(r"\d{4}\.\d{4,5}", aid):  # skip blog posts etc.
                likes[aid] = v
                published[aid] = (p.get("first_publication_date") or "")[:10]
        if not papers or (p.get("metrics") or {}).get("public_total_votes", 0) < min_likes:
            break
        page += 1
    # Save every paper above the threshold today, so tomorrow skips all of them (not only the new ones).
    Path("raw").mkdir(exist_ok=True)
    Path(f"raw/{day}.alphaxiv.json").write_text(json.dumps(likes, indent=0))
    seen = seen_before(day)
    if seen is None:  # first run: skip the 30-day backlog, keep only papers from the last week
        ids = [a for a in likes if published[a] >= (day - dt.timedelta(days=7)).isoformat()]
        print("first alphaXiv run: only papers published in the last 7 days")
    else:
        ids = [a for a in likes if a not in seen]
    print(f"alphaXiv: {len(likes)} arXiv papers with >= {min_likes} likes, {len(ids)} new")
    ns = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
    items = []
    for i in tqdm(range(0, len(ids), 100), desc="arXiv details"):
        chunk = ids[i:i + 100]
        root = ET.fromstring(get_retry("https://export.arxiv.org/api/query",
                                       params={"id_list": ",".join(chunk), "max_results": 100}).content)
        for e in root.findall("a:entry", ns):
            aid = re.sub(r"v\d+$", "", e.findtext("a:id", namespaces=ns).rsplit("/", 1)[-1])
            items.append({"source": "arxiv", "title": " ".join(e.findtext("a:title", namespaces=ns).split()),
                          "url": "https://arxiv.org/abs/" + aid,
                          "authors": ", ".join(a.findtext("a:name", namespaces=ns) for a in e.findall("a:author", ns)),
                          "likes": likes.get(aid, 0), "cats": [c.get("term") for c in e.findall("a:category", ns)],
                          "published": e.findtext("a:published", namespaces=ns)[:10],
                          "text": " ".join(e.findtext("a:summary", namespaces=ns).split())})
        time.sleep(3)
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
    ap.add_argument("--days", type=int, default=1, help="LessWrong/AF: full UTC days before --date")
    ap.add_argument("--date", default=None, help="digest date (default: today, UTC)")
    ap.add_argument("--min-likes", type=int, default=MIN_LIKES, help="alphaXiv likes needed")
    ap.add_argument("--print-latest", action="store_true", help="only print the date the next digest is for")
    a = ap.parse_args()
    if a.print_latest:
        print(target_day().isoformat())
        return
    today = a.date or target_day().isoformat()
    day = dt.date.fromisoformat(today)
    arxiv = fetch_alphaxiv_liked(day, a.min_likes)
    # Forums: the full UTC day(s) before the digest date, so days never overlap.
    days = a.days
    lw = fetch_lesswrong(days, dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC))
    print(f"Forum window: {days} day(s) before {day}")
    items = arxiv + lw
    Path("raw").mkdir(exist_ok=True)
    Path(f"raw/{today}.json").write_text(json.dumps(items, indent=1, ensure_ascii=False))
    with open(f"raw/{today}.txt", "w") as f:
        for i, x in enumerate(items, 1):
            meta = f"karma {x['karma']} | tags: {', '.join(x['tags'])}" if "karma" in x else f"{x['likes']} alphaXiv likes | {', '.join(x['cats'])}"
            f.write(f"[{i}] ({x['source']}) {x['title']}\n{x['url']}\n{x['authors']} | {meta}\n{x['text']}\n\n")
    print(f"arXiv (via alphaXiv likes): {len(arxiv)} papers")
    print(f"LessWrong (AI): {sum(x['source']=='lesswrong' for x in lw)}, Alignment Forum: {sum(x['source']=='alignmentforum' for x in lw)}")
    print(f"LW/AF with karma>=20: {sum(x['karma']>=20 for x in lw)}")
    print(f"Wrote raw/{today}.txt ({Path(f'raw/{today}.txt').stat().st_size//1024} KB)")


if __name__ == "__main__":
    main()
