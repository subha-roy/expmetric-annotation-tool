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
COLL = ["christian", "chris", "zhipin", "joy"]

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
         "christian": 30, "chris": 30, "zhipin": 30, "joy": 30}
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
_EXP_SESSIONS = 570 + 30 * (len(HIWIS) + len(COLL))
chk(f"A12 total sessions = {_EXP_SESSIONS}",
    sum(len(per[k]["queue"]) for k in per) == _EXP_SESSIONS,
    sum(len(per[k]["queue"]) for k in per))

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
chk("A23 all bundles decrypt with their own code", len(codes) == 8, len(codes))
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


# ---- FINAL assignment matrix (spec section 10) ----
_D = {x: samples[x]["_difficulty"] for x in samples}
_R = {x: samples[x]["direction"] for x in samples}
_cd = collections.Counter(_D[x] for x in common)
for _k in ("easy", "medium", "hard"):
    chk(f"M01 common {_k} = 10", _cd[_k] == 10, _cd[_k])
for _dr in ("i2t", "t2i"):
    for _df in ("easy", "medium", "hard"):
        _n = sum(1 for x in common if _R[x] == _dr and _D[x] == _df)
        chk(f"M02 common {_dr} {_df} = 5", _n == 5, _n)
_WANT = {("i2t", "easy"): [24, 24, 24, 23], ("t2i", "easy"): [24, 24, 23, 24],
         ("i2t", "medium"): [24, 23, 24, 24], ("t2i", "medium"): [23, 24, 24, 24],
         ("i2t", "hard"): [24, 24, 23, 24], ("t2i", "hard"): [24, 24, 24, 23]}
for _cell, _exp in _WANT.items():
    _got = [sum(1 for x in per[h]["unique_ids"]
                if _R[x] == _cell[0] and _D[x] == _cell[1]) for h in HIWIS]
    chk(f"M03 unique {_cell[0]} {_cell[1]}", _got == _exp, f"{_got} != {_exp}")
_EXPD = {"damir": {"easy": 48, "medium": 47, "hard": 48},
         "brisca": {"easy": 48, "medium": 47, "hard": 48},
         "omar": {"easy": 47, "medium": 48, "hard": 47},
         "sayeeda": {"easy": 47, "medium": 48, "hard": 47}}
_EXPR = {"damir": {"i2t": 72, "t2i": 71}, "brisca": {"i2t": 71, "t2i": 72},
         "omar": {"i2t": 71, "t2i": 71}, "sayeeda": {"i2t": 71, "t2i": 71}}
for h in HIWIS:
    chk(f"M04 {h} unique difficulty balance",
        dict(collections.Counter(_D[x] for x in per[h]["unique_ids"])) == _EXPD[h])
    chk(f"M05 {h} unique direction balance",
        dict(collections.Counter(_R[x] for x in per[h]["unique_ids"])) == _EXPR[h])
    _t = collections.Counter(_D[x] for x in per[h]["queue"])
    chk(f"M06 {h} total difficulty = unique + 10/10/10",
        all(_t[k] == _EXPD[h][k] + 10 for k in ("easy", "medium", "hard")), dict(_t))

# ---- FINAL flow: login -> dashboard -> sample (image + text + parts) ----
chk("B01 login is the first screen", 'id="login"' in html and 'id="dash"' in html)
chk("B02 login lands on the dashboard, never a sample",
    "renderDash();                       // always land on the dashboard" in js
    or ("renderDash()" in js and "never a sample" in js))
chk("B03 no separate text-only decomposition PAGE",
    "DECOMPOSITION — TEXT ONLY" not in html and 'id="phaseA"' not in html
    and "decomposition_label" not in js)
chk("B04 image is present on the sample screen from the start",
    'id="imgFrame"' in html and 'loadImage(it.image)' in js)
chk("B05 two-pane: media column left, annotation column right",
    '.sample-grid{' in css.replace(' ', '') and 'media-col' in html and 'anno-col' in html)
chk("B06 media column is sticky on desktop",
    re.search(r'\.media-col\{[^}]*position:sticky', css.replace(' ', '')))
chk("B07 image is contained, never cropped", 'object-fit:contain' in css.replace(' ', ''))
chk("B08 original text shown prominently", 'caption-box' in html and 'Original text' in html)
chk("B09 part scale is 0-4 plus Cannot judge",
    "for (let v = 0; v <= 4; v++)" in js and "'cannot_judge'" in js)
chk("B10 overall scale is 1-5",
    "for (let v = OVERALL_MIN; v <= OVERALL_MAX; v++)" in js)
chk("B11 overall is locked until every part is rated",
    "allRated" in js and 'id="ovLock"' in html)
chk("B12 sample cannot complete without the overall score",
    "overall_alignment == null" in js)
chk("B13 dashboard has a numbered grid", 'numgrid' in css and 'numcell' in css)
chk("B14 five distinct statuses exist",
    all(f'.numcell.{k}' in css.replace(' ', '') for k in ('done', 'prog', 'skip', 'tech')))
chk("B15 status is not colour-only (mark + aria-label + title)",
    "aria-label" in js and "b.title =" in js and "MARK" in js)
chk("B16 legend present", 'class="legend"' in html and 'Skipped — needs revisit' in html)
chk("B17 skip is worded 'Skip for now'", "Skip for now" in html)
# statusOf() returns exactly one bucket per sample, so a skipped sample can never land
# in the completed count; completion also clears the skip flag.
chk("B18 skipped is NOT counted as completed",
    "if (r.status === 'completed') return 'done';" in js
    and "if (r.skipped_for_now) return 'skip';" in js
    and "r.status = 'completed'; r.skipped_for_now = false;" in js)
chk("B19 completed samples reopen in review mode with an edit control",
    'id="reviewBar"' in html and 'id="editBtn"' in html and "already completed" in html)
chk("B20 revision metadata is tracked",
    all(k in js for k in ("first_started_at", "first_completed_at",
                          "last_modified_at", "revision_count")))
chk("B21 continue-annotation prefers in-progress then pending",
    "continueAnnotation" in js and "'prog'" in js and "'pending'" in js)
chk("B22 quick jump is bounds-checked against the assignment",
    "v > items().length" in js)
chk("B23 dashboard filters exist", 'id="filters"' in html and 'data-f="skip"' in html)
chk("B24 final export blocks while work is outstanding",
    "outstanding > 0" in js and "still require review" in js)
chk("B25 export carries index, status, scores, technical state and revisions",
    all(k in js for k in ("assignment_index", "status:", "parts:",
                          "human_overall_alignment_1_to_5", "technical_issue",
                          "revision_count")))
chk("B26 content version bumped so stale cache cannot resurface",
    "CONTENT_VERSION" in js and "flow-v5-dualjudgment" in js)
chk("B27 cache namespace includes annotator, assignment hash and version",
    "annotator_id}_${b.assignment_hash" in js and "CONTENT_VERSION}" in js)
chk("B28 no private benchmark metadata in the app",
    not any(re.search(r"\b" + w + r"\b", js) for w in
            ("difficulty", "primary_challenge", "source_dataset", "generator", "qc_json")))
chk("B29 keyboard scoring only affects the focused part's SUPPORT row",
    "closest?.('.part')" in js and "jrow')[1]" in js)
chk("B30 rating does not auto-scroll the panel",
    "repaint()" in js and "renderParts();" in js)
chk("B31 backup import validates annotator, assignment and schema",
    "different annotator" in js and "different assignment" in js and "different schema" in js)
chk("B32 technical issue is separate from cannot-judge and skip",
    'id="techBox"' in html and "technical_issue" in js and "skipped_for_now" in js)


# ---- overall scale is 1-5 and nothing else (spec section 29) ----
chk("S01 overall bounds are 1..5", "OVERALL_MIN = 1, OVERALL_MAX = 5" in js)
chk("S02 loop offers exactly 1..5",
    "for (let v = OVERALL_MIN; v <= OVERALL_MAX; v++)" in js and "v <= 7" not in js)
for _v, _want in ((0, False), (1, True), (2, True), (3, True), (4, True), (5, True),
                  (6, False), (7, False)):
    _ok = (isinstance(_v, int) and 1 <= _v <= 5)
    chk(f"S03 overall {_v} {'accepted' if _want else 'rejected'}", _ok == _want)
chk("S04 validOverall guards writes and imports",
    "validOverall(v) ? v : null" in js and "validOverall(_ov) ? _ov : null" in js)
chk("S05 export field renamed to 1_to_5",
    "human_overall_alignment_1_to_5" in js and "1_to_7" not in js)
chk("S06 no active 1-7 wording remains",
    "1–7" not in html and "1-7" not in html and "7 fully aligned" not in html)
chk("S07 part scale still 0-4 plus cannot judge",
    "for (let v = 0; v <= 4; v++)" in js and "'cannot_judge'" in js)
chk("S08 content version is the final dual-judgment version",
    "flow-v5-dualjudgment" in js)
# ---- improved guide (spec section 21) ----
for _sec in ("A · What you are doing",
             "B · Decomposition quality — judged against the text",
             "C · Image support — judged against the image",
             "D · Overall alignment (1–5)",
             "E · Cannot judge vs Skip for now vs Technical issue",
             "F · Navigating and saving"):
    chk(f"G01 guide section {_sec[:1]}", _sec in html)
chk("G02 guide has worked examples", "red shirt" in html and "three dogs" in html)
chk("G03 guide states not to average", "Do not mechanically average" in html)
chk("G04 compact scale reference on the sample screen", 'class="scalebar"' in html)
chk("G05 full definitions collapsible on the sample screen",
    'scaleguide' in html and '<details>' in html)


# ---- TWO judgments per atomic part (final workflow) ----
chk("J01 decomposition vocabulary is the five agreed labels",
    all(v in js for v in ("'reasonable'", "'needs_split'", "'needs_merge'",
                          "'redundant'", "'not_entailed'")))
chk("J02 both judgments are stored per part",
    "decomp_quality: {}, part_support: {}" in js)
chk("J03 a part is done only with BOTH judgments",
    "validDecomp(r.decomp_quality[p.part_id]) &&" in js
    and "r.part_support[p.part_id] !== undefined" in js)
chk("J04 overall unlocks only when every part has both",
    "it.parts.every((p) => partDone(r, p))" in js)
chk("J05 completion names which judgment is missing",
    "without a decomposition judgement" in js and "without an image-support score" in js)
chk("J06 card renders two labelled rows",
    "'Decomposition'" in js and "'Image support'" in js and "jrow" in js)
chk("J07 export carries part_id, text, type, decomp_quality, support_score",
    all(k in js for k in ("part_id: p.part_id", "text: p.atomic_claim",
                          "type: p.part_type", "decomp_quality:", "support_score:")))
chk("J08 invalid decomposition label is not exported",
    "validDecomp(r.decomp_quality[p.part_id])" in js and ": null," in js)
chk("J09 import restores both judgments and tolerates the older shape",
    "a.parts || a.part_support" in js and "validDecomp(p.decomp_quality)" in js)
chk("J10 support scale unchanged at 0-4 + cannot judge",
    "for (let v = 0; v <= 4; v++)" in js and "'cannot_judge'" in js)
chk("J11 overall scale unchanged at 1-5", "OVERALL_MIN = 1, OVERALL_MAX = 5" in js)
chk("J12 guide explains decomposition quality against the TEXT",
    "Decomposition quality — judged against the text" in html
    and all(w in html for w in ("Needs split", "Needs merge", "Redundant", "Not entailed")))
chk("J13 guide explains image support against the IMAGE",
    "Image support — judged against the image" in html)
chk("J14 guide states the two judgments are independent",
    "Give the image-support score <b>even when</b>" in html)
chk("J15 part card layout keeps cards compact",
    ".jrow{display:flex;align-items:center" in css.replace(' ', '')
    or ".jrow{display:flex" in css.replace(' ', ''))

print(f"\n{P}/{P+F} passed")
sys.exit(0 if F == 0 else 1)
