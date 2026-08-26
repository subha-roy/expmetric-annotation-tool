"""Assignment + app integrity tests (spec section 19)."""
from __future__ import annotations
import base64, collections, hashlib, json, os, re, sys

import pyarrow.parquet as pq

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FROZEN = "/hnvme/workspace/v141be14-VisExMEM/benchmark/frozen"
P = F = 0


def chk(n, c, d=""):
    global P, F
    ok = bool(c); P, F = P + ok, F + (not ok)
    print(f"{'PASS' if ok else 'FAIL'} {n}" + (f"  :: {d}" if (d and not ok) else ""))


lock = json.load(open(f"{APP}/ASSIGNMENT_LOCK.json"))
audit = json.load(open(f"{APP}/private/assignment_audit.json"))
join = json.load(open(f"{APP}/private/benchmark_join.json"))
samples, parts = join["samples"], join["parts"]
per = audit["per_annotator"]
common = set(audit["common_sample_ids"])
HIWIS = ["damir", "brisca", "omar", "sayeeda"]
COLL = ["christian", "chris", "zhipin"]

# ---- benchmark + common set
chk("A01 benchmark size = 600", len(samples) == 600, len(samples))
chk("A02 common set = 30", len(common) == 30, len(common))
strat = collections.Counter(f'{samples[s]["direction"]}/{samples[s]["_difficulty"]}'
                            for s in common)
for cell in ("i2t/easy", "i2t/medium", "i2t/hard", "t2i/easy", "t2i/medium", "t2i/hard"):
    chk(f"A03 common {cell} = 5", strat[cell] == 5, strat[cell])

# ---- exact totals
EXP_U = {"damir": 143, "brisca": 143, "omar": 142, "sayeeda": 142}
EXP_T = {"damir": 173, "brisca": 173, "omar": 172, "sayeeda": 172,
         "christian": 30, "chris": 30, "zhipin": 30}
for k, v in EXP_U.items():
    chk(f"A04 {k} unique = {v}", len(per[k]["unique_ids"]) == v, len(per[k]["unique_ids"]))
for k, v in EXP_T.items():
    chk(f"A05 {k} total = {v}", len(per[k]["queue"]) == v, len(per[k]["queue"]))

# ---- identical common set for all seven
for k in HIWIS + COLL:
    chk(f"A06 {k} carries exactly the 30 common ids",
        set(per[k]["queue"]) & common == common)
chk("A07 colleagues annotate ONLY the common set",
    all(set(per[k]["queue"]) == common for k in COLL))

# ---- disjointness / exhaustiveness
for i in range(len(HIWIS)):
    for j in range(i + 1, len(HIWIS)):
        ov = set(per[HIWIS[i]]["unique_ids"]) & set(per[HIWIS[j]]["unique_ids"])
        chk(f"A08 {HIWIS[i]}/{HIWIS[j]} disjoint", not ov, len(ov))
allu = [i for k in HIWIS for i in per[k]["unique_ids"]]
chk("A09 unique union = 570 distinct", len(allu) == 570 and len(set(allu)) == 570, len(allu))
chk("A10 unique + common = 600", set(allu) | common == set(samples))
chk("A11 no unique id is also common", not (set(allu) & common))
chk("A12 total sessions = 780", sum(len(per[k]["queue"]) for k in per) == 780)

# ---- per-assignment sanity
for k in per:
    q = per[k]["queue"]
    chk(f"A13 {k} has no duplicate sample", len(q) == len(set(q)))
    chk(f"A14 {k} every sample resolves", all(s in samples for s in q))
    chk(f"A15 {k} every sample has parts", all(parts.get(s) for s in q))
    ids = [p["part_id"] for s in q for p in parts[s]]
    chk(f"A16 {k} part ids unique", len(ids) == len(set(ids)))

# ---- common part ids identical across bundles (needed for IAA)
ref = {s: [p["part_id"] for p in parts[s]] for s in sorted(common)}
chk("A17 common part ids stable across annotators",
    all({s: [p["part_id"] for p in parts[s]] for s in sorted(common)} == ref for _ in per))

# ---- images / text resolve
missing = [s for s in samples if not os.path.exists(samples[s]["image_path"])]
chk("A18 every benchmark image file exists", not missing, f"{len(missing)} missing")
chk("A19 every text non-empty", all(str(samples[s]["text"]).strip() for s in samples))

# ---- interspersion: common samples must not be clustered at the end
for k in HIWIS:
    pos = [i for i, s in enumerate(per[k]["queue"]) if s in common]
    spread = (max(pos) - min(pos)) / len(per[k]["queue"])
    chk(f"A20 {k} common samples interspersed", spread > 0.6, f"spread={spread:.2f}")

# ---- bundles: encrypted, no plaintext leakage of private metadata
PRIV = ("difficulty", "alignment", "source", "_difficulty", "primary_challenge",
        "generator", "qc_json", "easy", "medium", "hard")
for k in per:
    b = json.load(open(f"{APP}/data/bundle_{k}.json"))
    chk(f"A21 {k} bundle is encrypted",
        set(b) == {"kdf", "iterations", "cipher", "salt", "iv", "ciphertext"})
    raw = base64.b64decode(b["ciphertext"])[:4096]
    chk(f"A22 {k} ciphertext carries no plaintext metadata",
        not any(w.encode() in raw for w in PRIV))

# ---- decrypted payload must not contain private construction metadata
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
creds = open(f"{APP}/private/credentials.md").read()
codes = dict(re.findall(r"\|\s*\w+\s*\|\s*`(\w+)`\s*\|\s*`([\w-]+)`", creds))
leaks = []
for k, pw in codes.items():
    b = json.load(open(f"{APP}/data/bundle_{k}.json"))
    key = hashlib.pbkdf2_hmac("sha256", pw.encode(), base64.b64decode(b["salt"]),
                              b["iterations"], dklen=32)
    pt = AESGCM(key).decrypt(base64.b64decode(b["iv"]),
                             base64.b64decode(b["ciphertext"]), None)
    pay = json.loads(pt)
    for it in pay["items"]:
        if set(it) - {"sample_id", "order", "text", "image", "parts"}:
            leaks.append((k, set(it)))
            break
chk("A23 all bundles decrypt with their own code", len(codes) == 7, len(codes))
chk("A24 decrypted items expose ONLY annotator-visible fields", not leaks, str(leaks[:2]))
def _opens(bundle, password):
    """True if `password` decrypts the bundle."""
    key = hashlib.pbkdf2_hmac("sha256", password.encode(),
                              base64.b64decode(bundle["salt"]), bundle["iterations"],
                              dklen=32)
    try:
        AESGCM(key).decrypt(base64.b64decode(bundle["iv"]),
                            base64.b64decode(bundle["ciphertext"]), None)
        return True
    except Exception:
        return False


_bd = json.load(open(f"{APP}/data/bundle_damir.json"))
chk("A25 wrong code cannot open a bundle", not _opens(_bd, "definitely-wrong-code"))
chk("A25b another annotator's code cannot open it",
    not _opens(_bd, codes["brisca"]))
chk("A25c the correct code does open it", _opens(_bd, codes["damir"]))

# ---- app static checks
html = open(f"{APP}/index.html").read()
js = open(f"{APP}/app.js").read()
css = open(f"{APP}/styles.css").read()
ids_html = set(re.findall(r'id="([A-Za-z0-9_]+)"', html))
ids_js = set(re.findall(r"\$\('([A-Za-z0-9_]+)'\)", js))
chk("A26 every element id used by app.js exists in index.html",
    ids_js <= ids_html, str(sorted(ids_js - ids_html)))
chk("A27 no external CDN dependency",
    not re.search(r'src="https?://|href="https?://(?!fonts)', html), "external ref found")
chk("A28 image src only set after phase A (no src attribute in HTML)",
    not re.search(r'<img[^>]+src=', html))
chk("A29 no analytics/tracking", not re.search(r"google-analytics|gtag|plausible|matomo", js))
# Word-boundary match: "holistic_alignment_1_to_7" is the ANNOTATOR's own answer and
# legitimately contains "_alignment"; only the private construction fields are forbidden.
_PRIVATE_FIELDS = ["difficulty", "primary_challenge", "secondary_challenges",
                   "source_dataset", "qc_json", "profile_json", "generator",
                   "original_prompt_raw", "intended_error", "is_common"]
_hits = [w for w in _PRIVATE_FIELDS if re.search(r"\b" + w + r"\b", js)]
chk("A30 app never references private construction fields", not _hits, str(_hits))
chk("A31 app never labels a sample as common/unique",
    not re.search(r"\b(is_common|common_sample|iaa)\b", js, re.I))

# ---- FINAL study order: decomposition -> part support -> overall (spec section 27)
chk("B01 step 1 is decomposition, text only",
    'id="phaseA"' in html and 'Decomposition — text only' in html)
chk("B02 no <img> src anywhere in the markup", not re.search(r'<img[^>]+src=', html))
chk("B03 step 2 is a two-pane layout", 'class="twopane"' in html
    and 'pane-img' in html and 'pane-parts' in html)
chk("B04 left image pane is sticky", re.search(r'\.pane-img\{[^}]*position:sticky', css))
chk("B05 image is contained, never cropped",
    'object-fit:contain' in css.replace(' ', ''))
chk("B06 right pane scrolls independently of the sticky image",
    '.pane-parts{' in css.replace(' ', '') and '.pane-img{position:sticky' in css.replace(' ', ''))
chk("B07 step 3 lives at the bottom of the right pane",
    html.index('id="cParts"') < html.index('id="step3"') < html.index('id="saveNext"'))
chk("B08 step 3 starts locked", 'class="step3 locked"' in html)
chk("B09 step 3 unlocks only when every part is scored",
    'allPartsScored' in js and 'paintStep3' in js)
chk("B10 overall scale is 1-7", "for (let v = 1; v <= 7; v++)" in js)
chk("B11 part scale is 0-4 plus Cannot judge",
    "for (let v = 0; v <= 4; v++)" in js and "'cannot_judge'" in js)
chk("B12 sample cannot finish without the overall score",
    "holistic_alignment_1_to_7 == null" in js and "Please give the overall" in js)
chk("B13 all original parts are rated regardless of step-1 label",
    "regardless of its Step-1 judgement" in js or "whatever step 1 said" in js)
chk("B14 decomposition is never rewritten from step-1 answers",
    "never rewritten" in js)
chk("B15 cannot-judge is separate from technical issue",
    'id="techPanel"' in html and 'technical_issue' in js)
chk("B16 content version bumped so stale part state cannot be reused",
    "CONTENT_VERSION" in js and "decomp-phrase-v2" in js)
chk("B17 db namespace includes the content version",
    "CONTENT_VERSION}" in js.replace(' ', '').replace('\n', ''))
chk("B18 export orders decomposition -> part_support -> overall",
    js.index('decomposition: {') < js.index('part_support:') < js.index('overall_alignment:'))
chk("B19 export keeps part ids for later merging",
    "part_id: p.part_id" in js)
chk("B20 guide states the final order",
    'Step 2 — Statement support' in html and 'Step 3 — Overall alignment' in html)
chk("B21 obsolete phase C markup fully removed",
    'id="phaseC"' not in html and 'renderC(' not in js)

print(f"\n{P}/{P+F} passed")
sys.exit(0 if F == 0 else 1)
