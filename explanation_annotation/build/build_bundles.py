"""Encrypted bundles for the CURRENT BASELINE explanation-quality study.

IMPORTANT: this is the BASELINE study. VisExMEM-9B is deliberately excluded from Task A
and Task B -- it is not being evaluated yet. Only three blinded systems are shown:
GPT-5.6 Sol Decomposed, EXPERT, and VIEScore-official. VisExMEM's source files and its
original four-system build logic are left untouched elsewhere in this repo for a later,
separate study -- see git history (commit adding "four-HiWi" bundles) for that version.

Same crypto scheme as the original AGITA annotation app (app/build/build_bundles.py):
AES-256-GCM, key from a disposable access code via PBKDF2-HMAC-SHA256 (600k iterations,
per-annotator salt). Not server-side auth -- a static site cannot authenticate -- but
publishing the bundles reveals nothing without the code, and each annotator can only open
their own assignment.

Each bundle embeds, per assigned sample, the 3 blinded-label (A/B/C) explanation texts
and (only for the label whose underlying system is GPT-5.6 Sol Decomposed) the Task-B
evidence-claim data pulled from GPT's OWN saved self-reported evidence boxes
(explanations_170.json / gpt_decomposed.task_b_evidence_secondary_only, already frozen --
never regenerated or modified here). This is internally labeled "GPT self-reported visual
evidence" everywhere it is carried (see `evidence_source` below) -- it is NOT causal
evidence and is NOT equivalent to VisExMEM's GroundingDINO-based grounding; it must never
be described as such. The label->system mapping itself is NEVER written into the bundle
or anywhere client-visible -- it lives only in private/blinding_map.json.

The four real HiWi bundles AND the "annotator" test/backup bundle are rebuilt here (the
independent timed-pilot bundle is rebuilt separately by build_pilot_bundle.py). Existing
credentials for every account are reused verbatim -- never regenerated.
"""
from __future__ import annotations
import argparse, base64, hashlib, json, os, re, secrets
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from build_blinding import order_for as blinding_order_for
from refresh_visexmem_bundles import decrypt as decrypt_bundle

ITER = 600_000
APP = Path(__file__).resolve().parents[1]
MANIFEST_DIR = Path("/home/hpc/v141be/v141be14/projects/proj2_exp_metric/evaluation/explanation_annotation/manifests")
LABELS = ["A", "B", "C"]
SYSTEMS = ["gpt_decomposed", "expert", "viescore_official"]
# Baseline study: GPT-5.6 Sol Decomposed is the only system carrying its OWN self-reported
# evidence boxes into Task B. Frozen, never regenerated -- see module docstring.
EVIDENCE_SYSTEMS = {"gpt_decomposed"}
EVIDENCE_SOURCE_LABEL = "GPT self-reported visual evidence"


def encrypt(payload: dict, password: str):
    salt = secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITER, dklen=32)
    iv = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(iv, json.dumps(payload, separators=(",", ":")).encode(), None)
    b64 = lambda b: base64.b64encode(b).decode()
    return {"kdf": "PBKDF2-HMAC-SHA256", "iterations": ITER, "cipher": "AES-GCM-256",
            "salt": b64(salt), "iv": b64(iv), "ciphertext": b64(ct)}


def sha_json(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


NAMES = {"damir": "Damir", "brisca": "Brisca", "omar": "Omar", "sayeeda": "Sayeeda",
        "annotator": "Annotator (test account)"}
HIWIS = ("damir", "brisca", "omar", "sayeeda")


def credentials(path: Path):
    found = {}
    pattern = re.compile(r"\|[^|]+\|\s*`([^`]+)`\s*\|\s*`([^`]+)`")
    for line in path.read_text().splitlines():
        match = pattern.search(line)
        if match:
            found[match.group(1)] = match.group(2)
    return found


def atomic_json(path: Path, value: object):
    temporary = Path(str(path) + ".tmp")
    temporary.write_text(json.dumps(value, separators=(",", ":")))
    os.replace(temporary, path)


def build_entry(sysrec: dict) -> dict:
    """One blinded-label's Task-A content (+ Task-B evidence, when this system carries
    any). Baseline study: all three remaining systems use the same native
    blocks/text/word_count shape -- there is no VisExMEM-specific presentation branch."""
    entry = {"blocks": sysrec.get("task_a_blocks") or [],
             "text": sysrec.get("task_a_text"),
             "word_count": sysrec.get("word_count")}
    return entry


def build_items(queue: list[str], explanations: dict, sample_meta: dict,
                label_map_for: "callable", image_base: str) -> list[dict]:
    items = []
    for i, sid in enumerate(queue):
        meta = sample_meta[sid]
        exp = explanations[sid]
        label_map = label_map_for(sid)  # {"A": "expert", ...}
        explanations_by_label = {}
        for lab in LABELS:
            sysname = label_map[lab]
            sysrec = exp[sysname]
            entry = build_entry(sysrec)
            if sysname in EVIDENCE_SYSTEMS:
                entry["evidence"] = sysrec.get("task_b_evidence_secondary_only", [])
                entry["evidence_source"] = EVIDENCE_SOURCE_LABEL
                entry["box_coord_system"] = sysrec.get("box_coord_system")
            explanations_by_label[lab] = entry
        items.append({
            "sample_id": sid, "order": i,
            "text": meta["text"],
            "image": f'{image_base}/{os.path.basename(meta["image_path"])}',
            "image_native_width": exp.get("image_native_width"),
            "image_native_height": exp.get("image_native_height"),
            "explanations": explanations_by_label,
        })
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image-base", default="images")
    a = ap.parse_args()

    assignment = json.loads((MANIFEST_DIR / "annotator_assignment_170.json").read_text())
    blinding_path = APP / "private" / "blinding_map.json"
    blinding = json.loads(blinding_path.read_text())
    explanations = json.loads((MANIFEST_DIR / "explanations_170.json").read_text())
    manifest = json.loads((MANIFEST_DIR / "sample_manifest_170.json").read_text())
    sample_meta = {s["sample_id"]: s for s in manifest["samples"]}
    passwords = credentials(APP / "private" / "credentials.md")
    if not all(account in passwords for account in HIWIS):
        raise RuntimeError("existing HiWi credentials are incomplete")

    schema_version = "explanation-annotation-2.0.0"
    app_version = "2.1.0"
    manifest_hash = sha_json({"sample_ids": sorted(sample_meta), "seed": manifest["seed"]})

    os.makedirs(APP / "data", exist_ok=True)
    index_path = APP / "data/index.json"
    prior_index = json.loads(index_path.read_text()) if index_path.exists() else {"annotators": {}}
    index = {key: value for key, value in prior_index.get("annotators", {}).items()
             if key not in HIWIS and key != "annotator"}

    for account in HIWIS:
        rec = assignment["per_account"][account]
        pw = passwords[account]
        queue = rec["queue"]
        if len(queue) != 100:
            raise AssertionError(f"{account} does not have 100 final samples")
        items = build_items(queue, explanations, sample_meta,
                            lambda sid, account=account: blinding["mapping"][account][sid],
                            a.image_base)
        payload = {"annotator_id": account, "annotator_name": NAMES[account],
                   "annotator_role": "hiwi",
                   "schema_version": schema_version, "app_version": app_version,
                   "manifest_hash": manifest_hash,
                   "assignment_hash": sha_json(queue),
                   "assignment_size": len(items), "items": items}
        enc = encrypt(payload, pw)
        atomic_json(APP / "data" / f"bundle_{account}.json", enc)
        index[account] = {"name": NAMES[account], "bundle": f"data/bundle_{account}.json",
                          "assignment_hash": sha_json(queue), "assignment_size": len(items)}

    # "annotator" (test/backup, 30 common samples, excluded from all real IAA/statistics)
    # still ships in the current study UI, so its content must be baseline-only too. Its
    # sample queue/order is NOT part of the frozen 170-study assignment -- it is carried
    # forward exactly as already shipped, by decrypting the currently-live bundle, so
    # nothing about which samples it sees or in what order changes here.
    annotator_bundle_path = APP / "data" / "bundle_annotator.json"
    annotator_pw = passwords["annotator"]
    old_annotator_payload = decrypt_bundle(json.loads(annotator_bundle_path.read_text()), annotator_pw)
    annotator_queue = [item["sample_id"] for item in old_annotator_payload["items"]]
    annotator_mapping = {}
    for sid in annotator_queue:
        order = blinding_order_for(sid, "annotator")
        annotator_mapping[sid] = {LABELS[i]: order[i] for i in range(len(LABELS))}
    blinding["mapping"]["annotator"] = annotator_mapping
    blinding["labels"], blinding["systems"] = LABELS, SYSTEMS
    blinding_path.write_text(json.dumps(blinding, indent=2))

    annotator_items = build_items(annotator_queue, explanations, sample_meta,
                                  lambda sid: annotator_mapping[sid], a.image_base)
    annotator_payload = {
        "annotator_id": "annotator", "annotator_name": NAMES["annotator"],
        "annotator_role": old_annotator_payload.get("annotator_role", "test_account"),
        "schema_version": schema_version, "app_version": app_version,
        "manifest_hash": manifest_hash,
        "assignment_hash": sha_json(annotator_queue),
        "assignment_size": len(annotator_items), "items": annotator_items,
    }
    atomic_json(annotator_bundle_path, encrypt(annotator_payload, annotator_pw))
    index["annotator"] = {"name": NAMES["annotator"], "bundle": "data/bundle_annotator.json",
                          "assignment_hash": sha_json(annotator_queue),
                          "assignment_size": len(annotator_items)}

    index_path.write_text(json.dumps({
        "schema_version": schema_version, "app_version": app_version,
        "manifest_hash": manifest_hash, "annotators": index}, indent=2))
    print(json.dumps({"rebuilt_real_bundles": list(HIWIS) + ["annotator"],
                      "sizes": {key: index[key]["assignment_size"]
                               for key in list(HIWIS) + ["annotator"]},
                      "systems": SYSTEMS,
                      "credentials_regenerated": False,
                      "visexmem_excluded": True,
                      "pilot_bundle_rebuilt_separately": True}, indent=2))


if __name__ == "__main__":
    main()
