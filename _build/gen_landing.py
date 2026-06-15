#!/usr/bin/env python3
"""Generate the Oxford R&D series landing index.html from all book dirs, grouped by level.
Reads each <book>/spec.json for title + has_audio. L1 books have no level prefix."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
L1 = ["at-the-beach", "eyes", "in-the-sky", "schools", "wheels"]

def book_meta(slug):
    spec = json.loads((ROOT / slug / "spec.json").read_text())
    return spec.get("title", slug), spec.get("has_audio", True)

# collect by level
levels = {1: [s for s in L1 if (ROOT / s / "spec.json").exists()]}
for lv in range(2, 7):
    levels[lv] = sorted(d.name for d in ROOT.glob(f"l{lv}-*") if (d / "spec.json").exists())

cards = ""
total = 0
for lv in range(1, 7):
    slugs = levels.get(lv, [])
    if not slugs: continue
    cards += f'<h2 class="lvl-h"><span class="ln">LEVEL {lv}</span></h2><div class="grid">'
    for s in slugs:
        title, has_audio = book_meta(s)
        title = title.split("—")[0].strip()
        badge = '<span class="tag audio">🔊 audio</span>' if has_audio else '<span class="tag read">📖 read-only</span>'
        cards += (f'<a class="card" href="{s}/index.html"><div class="cov">'
                  f'<img loading="lazy" src="covers/{s}.jpg" alt="{title}"></div>'
                  f'<div class="meta"><h3>{title}</h3>{badge}</div></a>')
        total += 1
    cards += '</div>'

html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Oxford Read and Discover</title>
<style>
  :root{{--accent:#0e8a7d;--bg:#eef5f3}}
  *{{box-sizing:border-box}}
  body{{margin:0;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:var(--bg);color:#15302c}}
  header{{background:linear-gradient(135deg,#0e8a7d,#0a4f48);color:#fff;padding:34px 20px 26px;text-align:center}}
  header h1{{margin:0 0 6px;font-size:26px}}
  header p{{margin:0;opacity:.92;font-size:15px}}
  header .lib{{display:inline-block;margin-top:14px;font-size:13px;font-weight:700;color:#fff;background:rgba(255,255,255,.18);border-radius:20px;padding:7px 16px;text-decoration:none}}
  main{{max-width:1040px;margin:0 auto;padding:24px 18px 70px}}
  .lvl-h{{font-size:15px;color:var(--accent);margin:30px 0 12px;border-bottom:2px solid #cfe3df;padding-bottom:6px}}
  .lvl-h .ln{{font-weight:800;letter-spacing:.06em}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(165px,1fr));gap:18px}}
  .card{{background:#fff;border-radius:13px;overflow:hidden;box-shadow:0 3px 12px rgba(0,0,0,.1);text-decoration:none;color:inherit;display:flex;flex-direction:column;transition:transform .15s,box-shadow .15s}}
  .card:hover{{transform:translateY(-4px);box-shadow:0 8px 22px rgba(0,0,0,.16)}}
  .card .cov{{aspect-ratio:420/594;background:#e7efed;overflow:hidden;border-bottom:1px solid #e1ebe8}}
  .card .cov img{{width:100%;height:100%;object-fit:cover}}
  .card .meta{{padding:11px 13px 14px}}
  .card h3{{margin:0 0 7px;font-size:15px;line-height:1.25}}
  .tag{{display:inline-block;font-size:10px;font-weight:700;border-radius:6px;padding:2px 8px}}
  .tag.audio{{background:#d8efe9;color:#0e8a7d}}
  .tag.read{{background:#f0ead9;color:#9a7d2e}}
  footer{{text-align:center;color:#8aa39d;font-size:12px;padding:0 20px 40px}}
</style></head>
<body>
<header>
  <h1>🔎 Oxford Read and Discover</h1>
  <p>{total} books · 6 levels · Read · Listen · Discover the world</p>
  <a class="lib" href="https://kidolabs.github.io/shelf7/">📚 Back to Library</a>
</header>
<main>{cards}</main>
<footer>Read · Listen — one happy bookshelf.</footer>
</body></html>"""
(ROOT / "index.html").write_text(html, encoding="utf-8")
print(f"landing: {total} books across {sum(1 for v in levels.values() if v)} levels")
