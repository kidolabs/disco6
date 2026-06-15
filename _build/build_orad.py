#!/usr/bin/env python3
"""Build one Oxford Read & Discover book dir (pages/ + audio/ + spec.json) from its
extracted folder. Oxford R&D audio = TWO identical versions of K chapters (tracks
1..K and K+1..2K). We use the first version. Chapters map to consecutive content
pages right after the credits page (Great Clarendon St). Verified by matching each
chapter title (from the Contents page) to its mapped page's text.

Usage: build_orad.py <extracted-book-folder> <out-book-dir> <slug>
"""
import sys, re, json, shutil
from pathlib import Path
import fitz
from PIL import Image

src = Path(sys.argv[1]); out = Path(sys.argv[2]); slug = sys.argv[3]
(out / "pages").mkdir(parents=True, exist_ok=True)
(out / "audio").mkdir(parents=True, exist_ok=True)

pdf_path = next(src.rglob("*.pdf"))
adir = next(p for p in src.rglob("*") if p.is_dir() and "Audio" in p.name)
tracks = sorted(adir.glob("*.mp3"))
K = len(tracks) // 2                       # chapters = half (2nd half is a duplicate read)

doc = fitz.open(str(pdf_path))
ptext = [" ".join(doc[i].get_text().split()) for i in range(doc.page_count)]

# credits page: "Great Clarendon" / "OXFORD UNIVERSITY PRESS" (OCR-ish, match loosely)
def is_credits(t):
    t = t.lower()
    return "clarendon" in t or ("oxford" in t and "press" in t and "isbn" in t) or "all rights reserved" in t.replace(" ", "").lower()
credits_idx = next((i for i, t in enumerate(ptext) if is_credits(t)), 2)
first_content = credits_idx + 1

# chapter titles from Contents page (page with "Contents" + "Introduction")
contents_idx = next((i for i, t in enumerate(ptext) if "contents" in t.lower() and "introduction" in t.lower()), 1)

def titles_from_gemini(page_idx, k):
    """Read the Contents page IMAGE (text layer is OCR-garbled) -> clean ordered titles."""
    import os
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    pix = doc[page_idx].get_pixmap(dpi=160)
    img = types.Part.from_bytes(data=pix.tobytes("png"), mime_type="image/png")
    prompt = (f"This is the Contents page of an Oxford Read and Discover book. Return a strict JSON "
              f"array of the {k} numbered chapter titles in order (exclude 'Introduction', 'Activities', "
              f"'Picture Dictionary', 'Glossary', 'About...'). Each item just the title string. Output ONLY JSON.")
    r = client.models.generate_content(model="gemini-2.5-flash", contents=[prompt, img])
    t = r.text.strip()
    if t.startswith("```"): t = t.split("```")[1].replace("json", "", 1).strip()
    arr = json.loads(t)
    return [str(x).strip() for x in arr][:k]

# regex fallback from garbled text layer
ctext = ptext[contents_idx]
m = re.search(r'(?i)introduction\s+\d+\s*(.*?)(?:activities|picture dictionary|glossary|$)', ctext)
seg = m.group(1) if m else ctext
titles = re.findall(r'\d+\s+([A-Za-z][A-Za-z \'\-,&]+?)\s+\d+', seg)
titles = [re.sub(r'\s+', ' ', t).strip() for t in titles][:K]
try:
    g = titles_from_gemini(contents_idx, K)
    if len(g) == K:
        titles = g
        print(f"  titles via Gemini (Contents p{contents_idx+1})")
except Exception as e:
    print(f"  [warn] Gemini titles failed ({e}); using text-layer titles")

content_pages = list(range(first_content, first_content + K))

def toks(s): return set(re.findall(r'[a-z]{3,}', s.lower()))
print(f"{slug}: {doc.page_count} pages, {len(tracks)} tracks -> {K} chapters; credits=p{credits_idx+1}, content=p{first_content}..p{first_content+K-1}")
ok = True
for i, pg in enumerate(content_pages):
    title = titles[i] if i < len(titles) else f"Chapter {i+1}"
    overlap = len(toks(title) & toks(ptext[pg])) if pg < len(ptext) else 0
    flag = "ok" if (overlap >= 1 or not toks(title)) else "WEAK"
    if flag == "WEAK": ok = False
    print(f"  Ch{i+1} p{pg+1:02d} '{title}' (title-overlap {overlap}) {flag}")

# copy first-half tracks
for i in range(K):
    shutil.copy(tracks[i], out / "audio" / f"{slug}-{i+1:02d}.mp3")

# render all pages (clean digital PDF -> light touch, no heavy scan filters)
for f in (out / "pages").glob("p*.webp"): f.unlink()
for i in range(doc.page_count):
    pix = doc[i].get_pixmap(dpi=150)
    im = Image.frombytes("RGB" if pix.n < 4 else "RGBA", [pix.width, pix.height], pix.samples).convert("RGB")
    im.save(out / "pages" / f"p{i+1:03d}.webp", "WEBP", quality=85, method=6)

# spec: all pages; content pages get audio + chapter label
content_map = {pg: i for i, pg in enumerate(content_pages)}
pages = []
for i in range(doc.page_count):
    if i in content_map:
        ci = content_map[i]
        label = f"{ci+1} · {titles[ci]}" if ci < len(titles) else f"Chapter {ci+1}"
        pages.append({"n": i + 1, "audio": f"{slug}-{ci+1:02d}.mp3", "label": label})
    else:
        pages.append({"n": i + 1, "audio": None, "label": None})
spec = {"title": sys.argv[4] if len(sys.argv) > 4 else slug, "level": 1, "chapters": titles, "pages": pages}
(out / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2))
sz = sum(f.stat().st_size for f in (out / "pages").glob("*.webp"))
print(f"  -> spec: {doc.page_count} pages, {K} audio chapters, titles={len(titles)}; pages {sz//1024//1024}MB; verify={'OK' if ok else 'CHECK WEAK ROWS'}")
