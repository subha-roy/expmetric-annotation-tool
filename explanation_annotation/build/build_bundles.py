"""Encrypted bundles for the final four-HiWi explanation-quality assignment.

Same crypto scheme
as the original AGITA annotation app (app/build/build_bundles.py): AES-256-GCM, key from
a disposable access code via PBKDF2-HMAC-SHA256 (600k iterations, per-annotator salt).
Not server-side auth -- a static site cannot authenticate -- but publishing the bundles
reveals nothing without the code, and each annotator can only open their own assignment.

Each bundle embeds, per assigned sample, the 4 blinded-label (A/B/C/D) explanation texts
and (only for the label whose underlying system is VisExMEM-9B -- the sole PRIMARY
Task-B system per the methodology review; GPT's self-reported boxes are computed and kept
in explanations_170.json for a possible secondary/appendix analysis but are deliberately
NOT read here) the Task-B evidence-claim data. The label->system mapping itself is NEVER
written into the bundle or anywhere client-visible -- it lives only in
private/blinding_map.json.

Only the four real HiWi bundles are rebuilt. Existing credentials and the independent
test/pilot bundles are preserved.
"""
from __future__ import annotations
import argparse, base64, hashlib, json, os, re, secrets
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from task_a_presentation import presentation_fields

ITER = 600_000
APP = Path(__file__).resolve().parents[1]
MANIFEST_DIR = Path("/home/hpc/v141be/v141be14/projects/proj2_exp_metric/evaluation/explanation_annotation/manifests")
LABELS = ["A", "B", "C", "D"]
# PRIMARY evidence system only -- GPT's self-reported boxes are methodologically
# different (not part of an evidence-conditioned scoring pipeline) and are excluded from
# the primary annotation interface; they remain available in explanations_170.json under
# gpt_decomposed.task_b_evidence_secondary_only for a possible appendix analysis only.
EVIDENCE_SYSTEMS = {"visexmem_9b"}


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image-base", default="images")
    a = ap.parse_args()

    assignment = json.loads((MANIFEST_DIR / "annotator_assignment_170.json").read_text())
    blinding = json.loads((APP / "private" / "blinding_map.json").read_text())
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
             if key not in HIWIS}
    for account in HIWIS:
        rec = assignment["per_account"][account]
        pw = passwords[account]
        queue = rec["queue"]
        if len(queue) != 100:
            raise AssertionError(f"{account} does not have 100 final samples")
        items = []
        for i, sid in enumerate(queue):
            meta = sample_meta[sid]
            exp = explanations[sid]
            label_map = blinding["mapping"][account][sid]  # {"A": "expert", ...}
            explanations_by_label = {}
            for lab in LABELS:
                sysname = label_map[lab]
                sysrec = exp[sysname]
                entry = (presentation_fields(sysrec) if sysname == "visexmem_9b" else
                         {"blocks": sysrec.get("task_a_blocks") or [],
                          "text": sysrec.get("task_a_text"),
                          "word_count": sysrec.get("word_count")})
                if sysname in EVIDENCE_SYSTEMS:
                    entry["evidence"] = sysrec.get("task_b_evidence", [])
                    entry["box_coord_system"] = sysrec.get("box_coord_system")
                explanations_by_label[lab] = entry
            items.append({
                "sample_id": sid, "order": i,
                "text": meta["text"],
                "image": f'{a.image_base}/{os.path.basename(meta["image_path"])}',
                "image_native_width": exp.get("image_native_width"),
                "image_native_height": exp.get("image_native_height"),
                "explanations": explanations_by_label,
            })
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

    index_path.write_text(json.dumps({
        "schema_version": schema_version, "app_version": app_version,
        "manifest_hash": manifest_hash, "annotators": index}, indent=2))
    print(json.dumps({"rebuilt_real_bundles": list(HIWIS),
                      "sizes": {key: index[key]["assignment_size"] for key in HIWIS},
                      "credentials_regenerated": False,
                      "test_bundle_unchanged": True,
                      "pilot_bundle_unchanged": True}, indent=2))


if __name__ == "__main__":
    main()
