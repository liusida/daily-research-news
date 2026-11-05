"""Build site/index.html: all digests in one page with a calendar to jump between days.

Usage: uv run build_site.py   (then open site/index.html)
"""
import json
from pathlib import Path
import markdown

TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Research Digest</title>
<style>
:root { --bg:#fafaf8; --panel:#fff; --text:#1d1d1f; --muted:#6b6b70; --line:#e4e4e0;
        --accent:#2f5fd0; --accent-soft:#e6edfb; --has:#1d1d1f; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg:#141416; --panel:#1c1c1f; --text:#ececee; --muted:#9a9aa2; --line:#2c2c31;
  --accent:#7ea2ff; --accent-soft:#232c44; --has:#ececee; } }
:root[data-theme="dark"] { --bg:#141416; --panel:#1c1c1f; --text:#ececee; --muted:#9a9aa2;
  --line:#2c2c31; --accent:#7ea2ff; --accent-soft:#232c44; --has:#ececee; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text);
  font:17px/1.65 -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif; }
.wrap { display:grid; grid-template-columns:260px minmax(0,1fr); gap:40px; max-width:1080px; margin:0 auto; padding:32px 16px; }
aside { position:sticky; top:24px; align-self:start; }
.cal { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px; }
.cal-head { display:flex; align-items:center; justify-content:space-between; margin-bottom:8px; font-weight:600; }
.cal-head button { background:none; border:0; color:var(--text); font-size:18px; cursor:pointer; padding:2px 8px; border-radius:6px; }
.cal-head button:hover { background:var(--accent-soft); }
.grid { display:grid; grid-template-columns:repeat(7,1fr); gap:2px; text-align:center; font-size:14px; }
.dow { color:var(--muted); font-size:12px; padding:4px 0; }
.day { padding:6px 0; border-radius:6px; color:var(--muted); opacity:.45; }
.day.has { color:var(--has); opacity:1; cursor:pointer; font-weight:600; }
.day.has:hover { background:var(--accent-soft); }
.day.sel { background:var(--accent); color:#fff; }
.nav { display:flex; gap:8px; margin-top:12px; }
.nav button { flex:1; padding:8px; border:1px solid var(--line); background:var(--panel); color:var(--text); border-radius:8px; cursor:pointer; font-size:14px; }
.nav button:disabled { opacity:.4; cursor:default; }
main { min-width:0; }
main h1 { font-size:28px; margin:0 0 8px; }
main h2 { font-size:20px; margin:36px 0 12px; padding-bottom:6px; border-bottom:1px solid var(--line); }
main h3 { font-size:18px; margin:26px 0 6px; }
main p { margin:6px 0; }
main a { color:var(--accent); text-decoration:none; } main a:hover { text-decoration:underline; }
main ul { padding-left:20px; } main li { margin:6px 0; }
.empty { color:var(--muted); }
.src { margin-top:40px; padding-top:12px; border-top:1px solid var(--line); color:var(--muted); font-size:14px; }
.theme { position:fixed; top:14px; right:16px; width:36px; height:36px; border-radius:50%;
  border:1px solid var(--line); background:var(--panel); color:var(--text); cursor:pointer;
  font-size:17px; line-height:1; display:flex; align-items:center; justify-content:center; z-index:10; }
.theme:hover { background:var(--accent-soft); }
@media (max-width:760px) { .wrap { grid-template-columns:1fr; gap:20px; } aside { position:static; } }
</style></head>
<body><button class="theme" id="theme" aria-label="Switch theme"></button><div class="wrap">
<aside><div class="cal">
  <div class="cal-head"><button id="pm" aria-label="Previous month">‹</button><span id="mlabel"></span><button id="nm" aria-label="Next month">›</button></div>
  <div class="grid" id="grid"></div>
</div>
<div class="nav"><button id="prev">← Older</button><button id="next">Newer →</button></div>
</aside>
<main id="content"></main>
</div>
<script>
const root = document.documentElement;
function isDark() { return getComputedStyle(root).getPropertyValue("--bg").trim() === "#141416"; }
function paintIcon() { document.getElementById("theme").textContent = isDark() ? "☀" : "☾";
  document.getElementById("theme").title = isDark() ? "Switch to light" : "Switch to dark"; }
try { const t = localStorage.getItem("theme"); if (t) root.dataset.theme = t; } catch (e) {}
document.getElementById("theme").onclick = () => {
  root.dataset.theme = isDark() ? "light" : "dark";
  try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
  paintIcon();
};
paintIcon();
const DIGESTS = __DATA__;
const REPO = "https://github.com/liusida/daily-research-news";
const dates = Object.keys(DIGESTS).sort();
let cur = location.hash.slice(1); if (!DIGESTS[cur]) cur = dates[dates.length-1];
let view = cur ? new Date(cur+"T00:00") : new Date();
const $ = id => document.getElementById(id);
function show(d) {
  cur = d; history.replaceState(null, "", "#"+d);
  $("content").innerHTML = (DIGESTS[d] || '<p class="empty">No digest yet.</p>') +
    `<p class="src">Source data for this day: <a href="${REPO}/blob/main/raw/${d}.txt">raw items</a> ·
     <a href="${REPO}/blob/main/raw/${d}.scored-jev.json">scores</a> · <a href="${REPO}">how it works</a></p>`;
  $("content").querySelectorAll("a").forEach(a => { a.target = "_blank"; a.rel = "noopener"; });
  const i = dates.indexOf(d);
  $("prev").disabled = i <= 0; $("next").disabled = i >= dates.length-1;
  view = new Date(d+"T00:00"); cal(); window.scrollTo(0,0);
}
function cal() {
  const y = view.getFullYear(), m = view.getMonth();
  $("mlabel").textContent = view.toLocaleString("en", {month:"long", year:"numeric"});
  const g = $("grid"); g.innerHTML = "";
  ["M","T","W","T","F","S","S"].forEach(x => g.insertAdjacentHTML("beforeend", `<div class="dow">${x}</div>`));
  const pad = (new Date(y,m,1).getDay()+6)%7;
  for (let i=0;i<pad;i++) g.insertAdjacentHTML("beforeend","<div></div>");
  const n = new Date(y,m+1,0).getDate();
  for (let d=1; d<=n; d++) {
    const k = `${y}-${String(m+1).padStart(2,"0")}-${String(d).padStart(2,"0")}`;
    const el = document.createElement("div"); el.textContent = d;
    el.className = "day" + (DIGESTS[k] ? " has" : "") + (k===cur ? " sel" : "");
    if (DIGESTS[k]) el.onclick = () => show(k);
    g.appendChild(el);
  }
}
$("pm").onclick = () => { view = new Date(view.getFullYear(), view.getMonth()-1, 1); cal(); };
$("nm").onclick = () => { view = new Date(view.getFullYear(), view.getMonth()+1, 1); cal(); };
$("prev").onclick = () => show(dates[dates.indexOf(cur)-1]);
$("next").onclick = () => show(dates[dates.indexOf(cur)+1]);
document.addEventListener("keydown", e => {
  if (e.key==="ArrowLeft" && !$("prev").disabled) $("prev").click();
  if (e.key==="ArrowRight" && !$("next").disabled) $("next").click();
});
if (cur) show(cur); else { $("content").innerHTML = '<p class="empty">No digests yet.</p>'; cal(); }
</script></body></html>"""


def main():
    data = {p.stem: markdown.markdown(p.read_text()) for p in sorted(Path("digests").glob("*.md"))}
    Path("site").mkdir(exist_ok=True)
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    Path("site/index.html").write_text(TEMPLATE.replace("__DATA__", blob))
    print(f"Wrote site/index.html with {len(data)} day(s)")


if __name__ == "__main__":
    main()
