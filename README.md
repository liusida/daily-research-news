# Daily Research News

A short daily digest of new **interpretability and large-model** research, published at
**https://daily.liusida.com/**.

## How it works

1. **Collect** (`collect.py`): every paper announced in arXiv `cs.LG`, `cs.CL` and `cs.AI` that day
   (from arXiv's day-labeled listing pages), plus AI posts from LessWrong and the Alignment Forum
   from the previous day.
2. **Score** (`filter.py`): each item's title and abstract are scored 0–3 for relevance by
   [Jev](https://docs.typesafe.ai/), a decision model, using the interests in `interests.md`.
   (`--backend claude` is also available.)
3. **Summarize** (`summarize.py`): an LLM (default OpenAI `gpt-6-luna`) writes a short, plain-English
   digest of the top items. Links are filled in by the script from the collected data, never written
   by the model.
4. **Publish** (`build_site.py`): all digests become one static page with a calendar.

All collected data is kept in `raw/` so anyone can check what the digest was based on:
`raw/DATE.txt` (every item), `raw/DATE.scored-jev.json` (scores).

## Run it

```bash
cp .env.example .env     # add TYPESAFE_API_KEY and OPENAI_API_KEY
./run.sh                 # newest batch, by hand
./daily.sh               # what the server cron runs: build, publish, commit, push
```

Past days (within one week): `uv run collect.py --date 2026-11-03`, then `filter.py` / `summarize.py`
with the same `--date`.

The server runs `daily.sh` from cron about one hour after arXiv's 20:00 US Eastern announcement.
