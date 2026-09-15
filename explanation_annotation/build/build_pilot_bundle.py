"""Build the PILOT account's bundle: the 10 timed pilot samples only, independent of the
(not-yet-frozen) 75-sample candidate assignment and its blinding map. Writes to separate
files (data/bundle_pilot.json, data/pilot_index.json, private/pilot_credentials.md) so it
never touches or depends on the candidate-assignment artifacts.
"""
from __future__ import annotations
import base64, hashlib, json, os, random, secrets, string, time
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ITER = 600_000
ALPHABET = string.ascii_lowercase + string.digits
APP = Path(__file__).resolve().parents[1]
MANIFEST_DIR = Path("/home/hpc/v141be/v141be14/projects/proj2_exp_metric/evaluation/explanation_annotation/manifests")
SEED = 20260915
LABELS = ["A", "B", "C", "D"]
SYSTEMS = ["visexmem_9b", "gpt_decomposed", "expert", "viescore_official"]
EVIDENCE_SYSTEMS = {"visexmem_9b"}


def code(n=5):
    return "-".join("".join(secrets.choice(ALPHABET) for _ in range(n)) for _ in range(4))


def encrypt(payload, password):
    salt = secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITER, dklen=32)
    iv = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(iv, json.dumps(payload, separators=(",", ":")).encode(), None)
    b64 = lambda b: base64.b64encode(b).decode()
    return {"kdf": "PBKDF2-HMAC-SHA256", "iterations": ITER, "cipher": "AES-GCM-256",
            "salt": b64(salt), "iv": b64(iv), "ciphertext": b64(ct)}


def sha_json(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def order_for(sample_id, salt):
    h = hashlib.sha256(f"{SEED}:{salt}:{sample_id}".encode()).hexdigest()
    rng = random.Random(int(h[:16], 16))
    order = list(SYSTEMS)
    rng.shuffle(order)
    return order


def main():
    pilot = json.loads((MANIFEST_DIR / "pilot_pool_10.json").read_text())
    sids = pilot["sample_ids"]

    rng = random.Random(SEED + 777)
    queue = list(sids)
    rng.shuffle(queue)

    items = []
    for i, sid in enumerate(queue):
        s = pilot["samples"][sid]
        order = order_for(sid, "pilot")
        explanations_by_label = {}
        for j, lab in enumerate(LABELS):
            sysname = order[j]
            sysrec = s[sysname]
            entry = {"blocks": sysrec.get("task_a_blocks") or [],
                    "text": sysrec.get("task_a_text"), "word_count": sysrec.get("word_count")}
            if sysname in EVIDENCE_SYSTEMS:
                entry["evidence"] = sysrec.get("task_b_evidence", [])
                entry["box_coord_system"] = sysrec.get("box_coord_system")
            explanations_by_label[lab] = entry
        items.append({
            "sample_id": sid, "order": i, "text": s["text"],
            "image": f'images/{Path(s["image_path"]).name}',
            "image_native_width": s.get("image_native_width"),
            "image_native_height": s.get("image_native_height"),
            "is_common30": False,
            "explanations": explanations_by_label,
        })

    schema_version = "explanation-annotation-pilot-1.0.0"
    app_version = "2.0.0"
    manifest_hash = sha_json({"sample_ids": sorted(sids), "seed": pilot["seed"], "kind": "pilot_10"})
    pw = code()
    payload = {"annotator_id": "pilot", "annotator_name": "Pilot (timed workload test)",
               "annotator_role": "pilot_test", "schema_version": schema_version,
               "app_version": app_version, "manifest_hash": manifest_hash,
               "assignment_hash": sha_json(queue), "assignment_size": len(items), "items": items}
    enc = encrypt(payload, pw)

    os.makedirs(APP / "data", exist_ok=True)
    (APP / "data" / "bundle_pilot.json").write_text(json.dumps(enc))
    (APP / "data" / "pilot_index.json").write_text(json.dumps({
        "schema_version": schema_version, "app_version": app_version, "manifest_hash": manifest_hash,
        "annotators": {"pilot": {"name": payload["annotator_name"], "bundle": "data/bundle_pilot.json",
                                 "assignment_hash": payload["assignment_hash"],
                                 "assignment_size": len(items)}}}, indent=2))

    os.makedirs(APP / "private", exist_ok=True)
    cred_path = APP / "private" / "pilot_credentials.md"
    with open(cred_path, "w") as f:
        f.write("# VisExMEM explanation-quality PILOT -- disposable access code (PRIVATE)\n\n")
        f.write(f"Generated {time.strftime('%Y-%m-%d %H:%M')}. Throwaway code for the timed "
                "workload pilot only. Do not commit this file.\n\n")
        f.write("| Name | Username | Access code | Samples | Role |\n")
        f.write("|---|---|---|---|---|\n")
        f.write(f"| {payload['annotator_name']} | `pilot` | `{pw}` | {len(items)} | pilot_test |\n")
    os.chmod(cred_path, 0o600)

    print(json.dumps({"account": "pilot", "n_items": len(items),
                      "credentials": str(cred_path) + " (chmod 600)",
                      "pilot_sample_order": queue}, indent=2))


if __name__ == "__main__":
    main()
