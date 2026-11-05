"""Score each collected item for relevance using Claude (via the `claude` CLI).

Reads raw/DATE.json, writes raw/DATE.scored.json.
Usage: uv run filter.py [--date YYYY-MM-DD] [--model claude-haiku-5-5] [--batch 40] [--workers 4]
"""
import argparse, datetime as dt, json, re, subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tqdm import tqdm

PROMPT = """{interests}

Below are items (papers or posts). For EACH item, give a relevance score 0-3 using the rules above,
and a reason of at most 12 words. Judge by content, not by keywords.
Reply with ONLY a JSON array, no other text: [{{"id": 1, "score": 3, "reason": "..."}}, ...]

{items}"""


def score_batch(batch, interests, model):
    items = "\n\n".join(f"id {i}: {x['title']}\n{x['text'][:1200]}" for i, x in batch)
    prompt = PROMPT.format(interests=interests, items=items)
    for _ in range(3):  # retry on bad output
        r = subprocess.run(["claude", "-p", "--model", model], input=prompt,
                           capture_output=True, text=True, timeout=600)
        m = re.search(r"\[.*\]", r.stdout, re.S)
        try:
            got = {d["id"]: d for d in json.loads(m.group(0))}
            if all(i in got for i, _ in batch):
                return got
        except Exception:
            pass
    return {i: {"id": i, "score": -1, "reason": "scoring failed"} for i, _ in batch}


JEV_CRITERIA = [
    "Skip: applications, product benchmarks, policy, events, or ML unrelated to understanding models",
    "Maybe: general LLM research with a small link to understanding models",
    "Likely useful: LLM behavior or representations, training dynamics, scaling science, alignment work on internals",
    "Must see: mechanistic interpretability, SAEs, circuits, features/superposition, probing, steering, attribution, model internals",
]


def score_jev(x, client):
    from typesafe_sdk import Score
    r = client.system_one(
        state=f"{x['title']}\n\n{x['text'][:2000]}",
        questions={"rel": Score(instructions="How relevant this item is to a researcher in interpretability of large models",
                                criteria=JEV_CRITERIA)})
    a = r.scores["rel"]
    return {"score": round(a.score), "score_raw": a.score, "confidence": a.confidence}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=max((p.stem for p in Path("raw").glob("????-??-??.json")), default=None),
                    help="default: newest collected day")
    ap.add_argument("--model", default="claude-haiku-5-5")
    ap.add_argument("--batch", type=int, default=40)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--backend", choices=["claude", "jev"], default="claude")
    ap.add_argument("--verbose", action="store_true", help="also list score-3 and score-2 titles")
    a = ap.parse_args()
    items = json.loads(Path(f"raw/{a.date}.json").read_text())
    interests = Path("interests.md").read_text()
    indexed = list(enumerate(items, 1))
    batches = [indexed[i:i + a.batch] for i in range(0, len(indexed), a.batch)]
    out = f"raw/{a.date}.scored.json" if a.backend == "claude" else f"raw/{a.date}.scored-jev.json"
    if a.backend == "jev":
        from dotenv import load_dotenv
        from typesafe_sdk import TypeSafeClient
        load_dotenv()
        with TypeSafeClient(model="jev-latest") as client, ThreadPoolExecutor(8) as ex:
            futs = {ex.submit(score_jev, x, client): x for x in items}
            for f in tqdm(as_completed(futs), total=len(futs), desc="Jev scoring"):
                try:
                    futs[f].update(f.result())
                except Exception as e:
                    futs[f].update(score=-1, reason=f"failed: {e}"[:200])
        batches = []
    with ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(score_batch, b, interests, a.model) for b in batches]
        for f in tqdm(as_completed(futs), total=len(futs), desc="Scoring batches"):
            for i, d in f.result().items():
                items[i - 1]["score"], items[i - 1]["reason"] = d["score"], d["reason"]
    Path(out).write_text(json.dumps(items, indent=1, ensure_ascii=False))
    counts = {s: sum(x.get("score") == s for x in items) for s in (3, 2, 1, 0, -1)}
    print("Score counts:", counts)
    if not a.verbose:
        return
    for s in (3, 2):
        print(f"\n--- score {s} ---")
        for x in items:
            if x.get("score") == s:
                why = f"  — {x['reason']}" if x.get("reason") else ""
                print(f"[{x['source']}] {x['title']}{why}")


if __name__ == "__main__":
    main()
