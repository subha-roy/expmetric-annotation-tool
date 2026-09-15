"""Encrypted per-annotator bundles for the explanation-quality study. Same crypto scheme
as the original AGITA annotation app (app/build/build_bundles.py): AES-256-GCM, key from
a disposable access code via PBKDF2-HMAC-SHA256 (600k iterations, per-annotator salt).
Not server-side auth -- a static site cannot authenticate -- but publishing the bundles
reveals nothing without the code, and each annotator can only open their own assignment.

Each bundle embeds, per assigned sample, the 4 blinded-label (A/B/C/D) explanation texts
and (only for the label whose underlying system is VisExMEM-9B -- the sole PRIMARY
Task-B system per the methodology review; GPT's self-reported boxes are computed and kept
in explanations_120.json for a possible secondary/appendix analysis but are deliberately
NOT read here) the Task-B evidence-claim data. The label->system mapping itself is NEVER
written into the bundle or anywhere client-visible -- it lives only in
private/blinding_map.json.

NOTE: this script builds bundles for the CANDIDATE 75-sample/annotator assignment, which
per explicit instruction is NOT to be frozen or distributed yet -- do not run this against
real HiWi credentials until a final per-annotator sample count is approved from the pilot.
"""
from __future__ import annotations
import argparse, base64, hashlib, json, os, secrets, string, sys, time
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ITER = 600_000
ALPHABET = string.ascii_lowercase + string.digits
APP = Path(__file__).resolve().parents[1]
MANIFEST_DIR = Path("/home/hpc/v141be/v141be14/projects/proj2_exp_metric/evaluation/explanation_annotation/manifests")
LABELS = ["A", "B", "C", "D"]
# PRIMARY evidence system only -- GPT's self-reported boxes are methodologically
# different (not part of an evidence-conditioned scoring pipeline) and are excluded from
# the primary annotation interface; they remain available in explanations_120.json under
# gpt_decomposed.task_b_evidence_secondary_only for a possible appendix analysis only.
EVIDENCE_SYSTEMS = {"visexmem_9b"}


def code(n=5):
    return "-".join("".join(secrets.choice(ALPHABET) for _ in range(n)) for _ in range(4))


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
ROLES = {"damir": "hiwi", "brisca": "hiwi", "omar": "hiwi", "sayeeda": "hiwi",
        "annotator": "test_account"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image-base", default="images")
    a = ap.parse_args()

    assignment = json.loads((MANIFEST_DIR / "annotator_assignment.json").read_text())
    blinding = json.loads((APP / "private" / "blinding_map.json").read_text())
    explanations = json.loads((MANIFEST_DIR / "explanations_120.json").read_text())
    manifest120 = json.loads((MANIFEST_DIR / "sample_manifest_120.json").read_text())
    sample_meta = {s["sample_id"]: s for s in manifest120["samples"]}

    schema_version = "explanation-annotation-1.0.0"
    app_version = "1.0.0"
    manifest_hash = sha_json({"sample_ids": sorted(sample_meta), "seed": manifest120["seed"]})

    os.makedirs(APP / "data", exist_ok=True)
    creds, index = [], {}
    for account, rec in assignment["per_account"].items():
        pw = code()
        queue = rec["queue"]
        items = []
        for i, sid in enumerate(queue):
            meta = sample_meta[sid]
            exp = explanations[sid]
            label_map = blinding["mapping"][account][sid]  # {"A": "expert", ...}
            explanations_by_label = {}
            for lab in LABELS:
                sysname = label_map[lab]
                sysrec = exp[sysname]
                entry = {"blocks": sysrec.get("task_a_blocks") or [],
                        "text": sysrec.get("task_a_text"), "word_count": sysrec.get("word_count")}
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
                "is_common30": sid in set(assignment["common_samples"]),
                "explanations": explanations_by_label,
            })
        payload = {"annotator_id": account, "annotator_name": NAMES[account],
                   "annotator_role": ROLES[account],
                   "schema_version": schema_version, "app_version": app_version,
                   "manifest_hash": manifest_hash,
                   "assignment_hash": sha_json(queue),
                   "assignment_size": len(items), "items": items}
        enc = encrypt(payload, pw)
        (APP / "data" / f"bundle_{account}.json").write_text(json.dumps(enc))
        index[account] = {"name": NAMES[account], "bundle": f"data/bundle_{account}.json",
                          "assignment_hash": sha_json(queue), "assignment_size": len(items)}
        creds.append((NAMES[account], account, pw, len(items), ROLES[account]))

    (APP / "data" / "index.json").write_text(json.dumps({
        "schema_version": schema_version, "app_version": app_version,
        "manifest_hash": manifest_hash, "annotators": index}, indent=2))

    os.makedirs(APP / "private", exist_ok=True)
    cred_path = APP / "private" / "credentials.md"
    with open(cred_path, "w") as f:
        f.write("# VisExMEM explanation-quality annotation -- disposable access codes (PRIVATE)\n\n")
        f.write(f"Generated {time.strftime('%Y-%m-%d %H:%M')}. Throwaway codes for this task only, "
                "not anyone's real password. Do not commit this file.\n\n")
        f.write("| Name | Username | Access code | Samples | Role |\n")
        f.write("|---|---|---|---|---|\n")
        for n, u, p, k, r in creds:
            f.write(f"| {n} | `{u}` | `{p}` | {k} | {r} |\n")
    os.chmod(cred_path, 0o600)

    print(json.dumps({"bundles": len(index),
                      "sizes": {k: v["assignment_size"] for k, v in index.items()},
                      "credentials": str(cred_path) + " (chmod 600)"}, indent=2))


if __name__ == "__main__":
    main()
