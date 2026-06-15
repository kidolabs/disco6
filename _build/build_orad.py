#!/usr/bin/env python3
"""Build one Oxford Read & Discover book dir (pages/ + audio/ + spec.json) from its
extracted folder. Oxford R&D audio = TWO identical versions of K chapters (tracks
1..K and K+1..2K). We use the first version. Chapters map to consecutive content
pages right after the credits page (Great Clarendon St). Verified by matching each
chapter title (from the Contents page) to its mapped page's text.

Usage: build_orad.py <extracted-book-folder> <out-book-dir> <slug>
"""
import sys, re, json, shutil, os, time
from pathlib import Path
import fitz
from PIL import Image

def _gem(contents, retries=4):
    """Gemini call with per-request timeout (no hangs) + retry on transient errors."""
    from google import genai
    from google.genai import types
    last = None
    for a in range(retries):
        try:
            cl = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options=types.HttpOptions(timeout=90000))
            return cl.models.generate_content(model="gemini-2.5-flash", contents=contents)
        except Exception as e:
            last = e; time.sleep(2 * (a + 1))
    raise last

src = Path(sys.argv[1]); out = Path(sys.argv[2]); slug = sys.argv[3]
(out / "pages").mkdir(parents=True, exist_ok=True)
(out / "audio").mkdir(parents=True, exist_ok=True)

# a book can ship extra PDFs (Activity Book, Answers) — the real reader is always the longest
pdf_path = max(src.rglob("*.pdf"), key=lambda p: fitz.open(str(p)).page_count)
adirs = [p for p in src.rglob("*") if p.is_dir() and "audio" in p.name.lower()]   # case-insensitive
# accept mp3 OR wma (some books ship .wma — converted to mp3 on copy)
tracks = sorted([p for p in adirs[0].iterdir() if p.suffix.lower() in (".mp3", ".wma")]) if adirs else []
has_audio = len(tracks) >= 2
K_audio = len(tracks) // 2                  # chapters = half (2nd half is a duplicate read)

doc = fitz.open(str(pdf_path))
ptext = [" ".join(doc[i].get_text().split()) for i in range(doc.page_count)]

# credits page: "Great Clarendon" / "OXFORD UNIVERSITY PRESS" (OCR-ish, match loosely)
def is_credits(t):
    t = t.lower()
    return "clarendon" in t or ("oxford" in t and "press" in t and "isbn" in t) or "all rights reserved" in t.replace(" ", "").lower()
credits_idx = next((i for i, t in enumerate(ptext) if is_credits(t)), 2)
first_content = credits_idx + 1

_SMALL = {"a", "an", "and", "the", "of", "to", "in", "on", "at", "for", "or", "but", "with", "from"}
def titlecase(s):
    ws = s.split()
    return " ".join(w if (i > 0 and w.lower() in _SMALL) else (w[:1].upper() + w[1:]) for i, w in enumerate(ws))

_NUM = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty".split())}

def chapters_from_audio(tracks):
    """GROUND TRUTH: transcribe track openings, extract 'Chapter N. <title>' announcements.
    Skips intro/title tracks; takes the FIRST occurrence of each chapter (2nd half duplicates).
    Returns ordered [{'title','track'}]. Converts .wma to a short mp3 clip for transcription."""
    import tempfile, subprocess
    from google.genai import types
    def clip_bytes(tr):
        if tr.suffix.lower() == ".mp3":
            return tr.read_bytes()
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False).name
        subprocess.run(["ffmpeg", "-y", "-t", "18", "-i", str(tr), "-codec:a", "libmp3lame", "-q:a", "6", tmp],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        b = Path(tmp).read_bytes(); os.unlink(tmp); return b
    found = {}
    for tr in tracks[: len(tracks) // 2 + 3]:           # 2nd half duplicates -> scan first half (+slack)
        aud = types.Part.from_bytes(data=clip_bytes(tr), mime_type="audio/mpeg")
        r = _gem([
            ('This audio is from a children\'s audiobook. If it ANNOUNCES a numbered chapter '
             '(e.g. "Chapter three. Volcanoes. ..."), return strict JSON {"num":<int>,"title":"<the chapter '
             'title ONLY, a few words, not the body text>"}. If it is an intro/title/credits with no chapter '
             'number, return {"num":null}. Output ONLY JSON.'), aud])
        t = r.text.strip()
        if t.startswith("```"): t = t.split("```")[1].replace("json", "", 1).strip()
        try:
            d = json.loads(t)
        except Exception:
            continue
        if isinstance(d, list):
            d = next((x for x in d if isinstance(x, dict) and x.get("num")), {})
        if not isinstance(d, dict):
            continue
        n = d.get("num")
        if isinstance(n, str) and n.strip().isdigit(): n = int(n)
        if isinstance(n, int) and n > 0 and n not in found and d.get("title"):
            found[n] = {"title": titlecase(str(d["title"]).strip().rstrip(". ")), "track": tr}
    return [found[n] for n in sorted(found)]

src_tracks = []
if has_audio:
    chapters = chapters_from_audio(tracks)
    titles = [c["title"] for c in chapters]
    src_tracks = [c["track"] for c in chapters]
    K = len(titles)
    print(f"  chapters via AUDIO (ground truth): {K} -> {titles}")
else:
    # no audio: titles from Contents page image (text layer is OCR-garbled)
    contents_idx = next((i for i, t in enumerate(ptext) if "contents" in t.lower() and "introduction" in t.lower()), 1)
    from google.genai import types
    titles = []
    try:
        _img = types.Part.from_bytes(data=doc[contents_idx].get_pixmap(dpi=160).tobytes("png"), mime_type="image/png")
        _r = _gem([
            ("This is the Contents page of an Oxford Read and Discover book. Return a strict JSON array of ALL the "
             "numbered chapter titles in order (exclude Introduction, Activities, Picture Dictionary, Glossary, About). "
             "Each item just the title string. Output ONLY JSON."), _img])
        _t = _r.text.strip()
        if _t.startswith("```"): _t = _t.split("```")[1].replace("json", "", 1).strip()
        titles = [str(x).strip() for x in json.loads(_t)]
        print(f"  titles via Gemini Contents (no-audio): {len(titles)}")
    except Exception as e:
        print(f"  [warn] Contents titles failed ({e})")
    K = len(titles)

def detect_content_pages(titles, first_content):
    """Find each chapter's START pdf page (0-based) by reading page headings via Gemini.
    Robust to 1- or 2-page-per-chapter layouts. Raises on any inconsistency (caller falls back)."""
    from google.genai import types
    k = len(titles)
    lo, hi = first_content, min(doc.page_count, first_content + 2 * k + 6)
    parts = []
    for pi in range(lo, hi):
        parts.append(f"=== PDF page {pi+1} ===")
        parts.append(types.Part.from_bytes(data=doc[pi].get_pixmap(dpi=120).tobytes("png"), mime_type="image/png"))
    tl = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
    prompt = (f"These are consecutive pages of an Oxford Read & Discover book, each labeled with its PDF page number.\n"
              f"The {k} chapter titles in order:\n{tl}\n\n"
              f"For EACH chapter, find the PDF page where that chapter STARTS (its title is the big heading at the top). "
              f"Return a strict JSON array of {k} integers — the PDF page number for chapters 1..{k} in order. Output ONLY JSON.")
    r = _gem([prompt, *parts])
    t = r.text.strip()
    if t.startswith("```"): t = t.split("```")[1].replace("json", "", 1).strip()
    arr = [int(x) - 1 for x in json.loads(t)]
    if len(arr) != k: raise ValueError("count")
    if any(arr[i] <= arr[i-1] for i in range(1, k)): raise ValueError("not-increasing")
    if arr[0] < first_content or arr[-1] >= doc.page_count: raise ValueError("range")
    return arr

try:
    content_pages = detect_content_pages(titles, first_content)
    print(f"  content pages via Gemini heading-detect: {[p+1 for p in content_pages]}")
except Exception as e:
    content_pages = list(range(first_content, first_content + K))
    print(f"  [warn] heading-detect failed ({e}); fallback consecutive p{first_content+1}..")

def toks(s): return set(re.findall(r'[a-z]{3,}', s.lower()))
print(f"{slug}: {doc.page_count} pages, {len(tracks)} tracks -> {K} chapters; credits=p{credits_idx+1}, content=p{first_content}..p{first_content+K-1}")
ok = True
for i, pg in enumerate(content_pages):
    title = titles[i] if i < len(titles) else f"Chapter {i+1}"
    overlap = len(toks(title) & toks(ptext[pg])) if pg < len(ptext) else 0
    flag = "ok" if (overlap >= 1 or not toks(title)) else "WEAK"
    if flag == "WEAK": ok = False
    print(f"  Ch{i+1} p{pg+1:02d} '{title}' (title-overlap {overlap}) {flag}")

# copy each chapter's source track (audio-driven order); convert .wma -> .mp3 via ffmpeg
if has_audio:
    import subprocess as _sp
    for i, src_t in enumerate(src_tracks):
        dest = out / "audio" / f"{slug}-{i+1:02d}.mp3"
        if src_t.suffix.lower() == ".wma":
            _sp.run(["ffmpeg", "-y", "-i", str(src_t), "-codec:a", "libmp3lame", "-q:a", "4", str(dest)],
                    check=True, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        else:
            shutil.copy(src_t, dest)

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
        pages.append({"n": i + 1, "audio": (f"{slug}-{ci+1:02d}.mp3" if has_audio else None), "label": label})
    else:
        pages.append({"n": i + 1, "audio": None, "label": None})
spec = {"title": sys.argv[4] if len(sys.argv) > 4 else slug, "level": 1,
        "has_audio": has_audio, "chapters": titles, "pages": pages}
(out / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2))
sz = sum(f.stat().st_size for f in (out / "pages").glob("*.webp"))
print(f"  -> spec: {doc.page_count} pages, {'AUDIO ' if has_audio else 'NO-AUDIO '}{K} chapters, titles={len(titles)}; pages {sz//1024//1024}MB; verify={'OK' if ok else 'CHECK WEAK ROWS'}")
