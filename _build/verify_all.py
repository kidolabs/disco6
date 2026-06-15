import os, json, sys
from pathlib import Path
from google import genai
from google.genai import types
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
prompt='Given ONE book page image and ONE audio file: does the audio read aloud the passage on this page? Return strict JSON {"match":true/false}. Only JSON.'
def check(slug,p):
    pimg=next(Path(f"{slug}/pages").glob(f"p{p['n']:03d}.*"))
    img=types.Part.from_bytes(data=pimg.read_bytes(),mime_type="image/webp")
    aud=types.Part.from_bytes(data=Path(f"{slug}/audio/{p['audio']}").read_bytes(),mime_type="audio/mpeg")
    r=client.models.generate_content(model="gemini-2.5-flash",contents=[prompt,img,aud])
    t=r.text.strip()
    if t.startswith("```"): t=t.split("```")[1].replace("json","",1).strip()
    try: return json.loads(t).get("match")==True
    except: return None
out=open("/tmp/orad-verify.log","w")
books=sorted([d for d in Path(".").glob("l[23456]-*") if (d/"spec.json").exists()])
gtotal=gbad=0
for d in books:
    spec=json.loads((d/"spec.json").read_text())
    if not spec.get("has_audio"): continue
    chs=[p for p in spec["pages"] if p.get("audio")]
    bad=[]
    for p in chs:
        if check(d.name,p)!=True: bad.append(p["label"].split("·")[0].strip())
    gtotal+=len(chs); gbad+=len(bad)
    line=f"{d.name}: {len(chs)-len(bad)}/{len(chs)} OK" + (f"  MISS Ch{bad}" if bad else "")
    out.write(line+"\n"); out.flush()
    print(line, flush=True)
out.write(f"=== TOTAL {gtotal-gbad}/{gtotal} chapters OK, {gbad} mismatch ===\n"); out.flush(); out.close()
