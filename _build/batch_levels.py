#!/usr/bin/env python3
"""Batch-build Oxford R&D books for given levels from the master zip.
For each nested book-zip: extract -> build_orad (render+map+spec) -> gen_orad (reader) -> cover.
Usage: batch_levels.py <master.zip> <levels e.g. 2,3,4,5,6>
Slugs are level-prefixed (l2-your-body) to stay unique across the whole repo.
"""
import sys, re, zipfile, subprocess, tempfile, shutil
from pathlib import Path
from PIL import Image

MASTER = Path(sys.argv[1])
LEVELS = set(sys.argv[2].split(","))
ROOT = Path(__file__).resolve().parent.parent          # projects/oxford-read-discover
BUILD = ROOT / "_build"
PY = str(Path.home() / ".claude/skills/.venv/bin/python3")

def kebab(s):
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return re.sub(r"-+", "-", s)

def clean_title(raw):
    t = raw.replace("_", " ").strip()
    t = re.sub(r"\s+L[0-9]\s*$", "", t)               # drop trailing "L5"/"L6"
    return re.sub(r"\s+", " ", t).strip()

zf = zipfile.ZipFile(MASTER)
entries = [n for n in zf.namelist() if n.endswith(".zip") and "__MACOSX" not in n and re.search(r"Level_\d", n)]
done = []
for name in sorted(entries):
    m = re.search(r"Level_(\d)_-_+(.+?)-\d{4}-\d{2}-\d{2}\.zip$", name)
    if not m: continue
    level, raw = m.group(1), m.group(2)
    if level not in LEVELS: continue
    title = clean_title(raw)
    slug = f"l{level}-{kebab(title)}"
    out = ROOT / slug
    print(f"\n########## L{level} · {title}  ({slug}) ##########", flush=True)
    with tempfile.TemporaryDirectory() as td:
        nested = Path(td) / "book.zip"
        nested.write_bytes(zf.read(name))
        ex = Path(td) / "ex"
        with zipfile.ZipFile(nested) as nz: nz.extractall(ex)
        if out.exists(): shutil.rmtree(out)
        r = subprocess.run([PY, str(BUILD / "build_orad.py"), str(ex), str(out), slug, title],
                           capture_output=True, text=True)
        print("\n".join(l for l in r.stdout.splitlines() if "warn" not in l.lower()))
        if r.returncode != 0:
            print("BUILD FAIL:", r.stderr[-400:]); continue
        rg = subprocess.run([PY, str(BUILD / "gen_orad.py"), str(out),
                             f"{title} — Oxford Read and Discover {level}"], capture_output=True, text=True)
        print("\n".join(l for l in rg.stdout.splitlines() if "warn" not in l.lower()))
        # cover
        p1 = next((out / "pages").glob("p001.*"))
        Image.open(p1).convert("RGB").save(ROOT / "covers" / f"{slug}.jpg", "JPEG", quality=85)
    done.append((level, title, slug))

print(f"\n===== BUILT {len(done)} books =====")
for lv, t, s in done: print(f"  L{lv} {t}  [{s}]")
