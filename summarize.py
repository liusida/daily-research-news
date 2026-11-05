"""Write a short daily digest from scored items using Claude.

Reads raw/DATE.scored-jev.json (or --scored), writes digests/DATE.md.
Usage: uv run summarize.py [--date YYYY-MM-DD] [--min 2.0] [--backend claude|openai] [--model NAME]
  claude: uses the logged-in `claude` CLI (default model claude-sonnet-5-5)
  openai: uses OPENAI_API_KEY from .env (model from --model or OPENAI_MODEL, default gpt-6.1-terra)
"""
import argparse, re, datetime as dt, json, subprocess
from pathlib import Path

PROMPT = """You write a daily research digest for an independent interpretability researcher.
They read English slowly. Write very simply: short sentences, common words, no hype,
no paper-style phrases, no method details, few numbers. Only the main idea and the main result.
Be accurate: only state what the text clearly says. If the text is unclear or seems to contradict
itself, stay general. Never add timing ("before X"), causes, or numbers the text does not clearly state.

Their interests:
{interests}

Below are today's candidate items, already filtered for relevance (higher score = more relevant).
Write a Markdown digest with exactly these parts:

# Research digest — {date}

## Top picks
Choose the 5-8 most important items (fewer if there are only a few items, e.g. on weekends). For each:
### <short plain title>
Two short sentences, at most 35 words total: (1) the main idea, (2) the main result.
Then a line with only the item tag, like: `{{L12}}` (use the item's number).

## Today in one line
One sentence about the main trend today, if there is one.

Never write URLs yourself; only use {{L<number>}} tags. Reply with ONLY the Markdown.

ITEMS:
{items}"""


def ask_llm(prompt, backend, model):
    import os
    from dotenv import load_dotenv
    load_dotenv()
    backend = backend or os.getenv("SUMMARY_BACKEND", "claude")
    if backend == "openai":
        from openai import OpenAI
        model = model or os.getenv("OPENAI_MODEL", "gpt-6.1-terra")
        print(f"Using OpenAI model {model}")
        r = OpenAI().chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}])
        text = (r.choices[0].message.content or "").strip()
        if r.usage:
            print(f"Tokens: {r.usage.prompt_tokens} in, {r.usage.completion_tokens} out")
    else:
        model = model or "claude-sonnet-5-5"
        r = subprocess.run(["claude", "-p", "--model", model], input=prompt, capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            raise SystemExit(f"claude failed: {r.stderr[:500]}")
        text = r.stdout.strip()
    if not text:
        raise SystemExit(f"{backend} returned an empty reply")
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=max((p.stem for p in Path("raw").glob("????-??-??.json")), default=None),
                    help="default: newest collected day")
    ap.add_argument("--scored", default=None, help="scored json (default: jev, else claude)")
    ap.add_argument("--min", type=float, default=2.0, help="minimum score to include")
    ap.add_argument("--backend", choices=["claude", "openai"], default=None,
                    help="default: SUMMARY_BACKEND in .env, else claude")
    ap.add_argument("--model", default=None)
    a = ap.parse_args()
    path = Path(a.scored or f"raw/{a.date}.scored-jev.json")
    if not path.exists():
        path = Path(f"raw/{a.date}.scored.json")
    items = json.loads(path.read_text())
    key = lambda x: x.get("score_raw", x.get("score", 0))
    picked = sorted((x for x in items if key(x) >= a.min), key=key, reverse=True)
    blob = "\n\n".join(f"[item {i}] [score {key(x):.2f}] ({x['source']}) {x['title']}\n{x['text'][:1500]}" for i, x in enumerate(picked, 1))
    prompt = PROMPT.format(interests=Path("interests.md").read_text(), date=a.date, items=blob)
    print(f"Summarizing {len(picked)} items (score >= {a.min}) from {path} ...")
    if not picked:
        reply = f"# Research digest — {a.date}\n\nNo relevant new items today."
    else:
        reply = ask_llm(prompt, a.backend, a.model)
    names = {"arxiv": "arXiv", "lesswrong": "LessWrong", "alignmentforum": "Alignment Forum"}
    def link(m):
        n = int(m.group(1))
        if not 1 <= n <= len(picked):
            return "(link missing)"
        x = picked[n - 1]
        extra = f' <a class="likes" href="https://www.alphaxiv.org/abs/{x["url"].rsplit("/", 1)[-1]}" title="likes on alphaXiv">♥ {x["likes"]}</a>' if x.get("likes") else ""
        if "karma" in x:
            extra = f' <span class="likes" title="karma on {names[x["source"]]}">▲ {x["karma"]}</span>'
        return f"[{names[x['source']]}]({x['url']}){extra}"
    text = re.sub(r"`?\{L(\d+)\}`?", link, reply)
    text = re.sub(r"\n## [^\n]+\n+(?=## |\Z)", "\n", text)  # drop empty sections
    Path("digests").mkdir(exist_ok=True)
    out = Path(f"digests/{a.date}.md")
    out.write_text(text + "\n")
    print(f"Wrote {out} ({len(text.split())} words)")


if __name__ == "__main__":
    main()
