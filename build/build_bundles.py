"""Encrypted per-annotator assignment bundles + private credential sheet.

Each bundle is AES-256-GCM encrypted with a key derived from the annotator's disposable
access code via PBKDF2-HMAC-SHA256 (600k iterations, per-annotator salt). The browser
decrypts with standard Web Crypto -- no custom cryptography anywhere.

This is NOT server-side authentication and is not claimed to be: a static site cannot
authenticate. What it does provide is that publishing the bundles reveals nothing without
the access code, and that each annotator can only open their own assignment.

Plaintext access codes go ONLY to private/credentials.md, which is gitignored.
"""
from __future__ import annotations
import argparse, base64, hashlib, json, os, secrets, string, sys, time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ITER = 600_000
ALPHABET = string.ascii_lowercase + string.digits


def code(n=5):
    """Disposable access code: 4 groups of 5 -> ~103 bits. Never a real password."""
    return "-".join("".join(secrets.choice(ALPHABET) for _ in range(n)) for _ in range(4))


def encrypt(payload: dict, password: str):
    salt = secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITER, dklen=32)
    iv = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(iv, json.dumps(payload, separators=(",", ":")).encode(), None)
    b64 = lambda b: base64.b64encode(b).decode()
    return {"kdf": "PBKDF2-HMAC-SHA256", "iterations": ITER, "cipher": "AES-GCM-256",
            "salt": b64(salt), "iv": b64(iv), "ciphertext": b64(ct)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--image-base", default="images",
                    help="relative or absolute base the app loads images from")
    a = ap.parse_args()

    lock = json.load(open(f"{a.app}/ASSIGNMENT_LOCK.json"))
    audit = json.load(open(f"{a.app}/private/assignment_audit.json"))
    join = json.load(open(f"{a.app}/private/benchmark_join.json"))
    samples, parts = join["samples"], join["parts"]
    # single source of truth -- duplicating this map is how adding an annotator to
    # build_assignments.py silently broke bundle generation with a KeyError
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from build_assignments import NAMES as names

    os.makedirs(f"{a.app}/data", exist_ok=True)
    creds, index = [], {}
    for user, rec in audit["per_annotator"].items():
        pw = code()
        items = []
        for i, sid in enumerate(rec["queue"]):
            s = samples[sid]
            items.append({
                "sample_id": sid, "order": i,
                # annotator-visible ONLY. No difficulty/direction/source/alignment.
                "text": s["text"],
                "image": f'{a.image_base}/{os.path.basename(s["image_path"])}',
                "parts": [{"part_id": p["part_id"], "part_index": p["part_index"],
                           "part_type": p["part_type"],
                           "atomic_claim": p["atomic_claim"]}
                          for p in parts[sid]],
            })
        payload = {"annotator_id": user, "annotator_name": names[user],
                   "annotator_role": rec["role"],
                   "schema_version": lock["schema_version"],
                   "app_version": lock["app_version"],
                   "benchmark_manifest_hash": lock["benchmark_manifest_hash"],
                   "assignment_hash": lock["assignment_hashes"][user],
                   "assignment_size": len(items), "items": items}
        enc = encrypt(payload, pw)
        json.dump(enc, open(f"{a.app}/data/bundle_{user}.json", "w"))
        index[user] = {"name": names[user], "bundle": f"data/bundle_{user}.json",
                       "assignment_hash": lock["assignment_hashes"][user],
                       "assignment_size": len(items)}
        creds.append((names[user], user, pw, len(items), rec["role"]))

    json.dump({"schema_version": lock["schema_version"],
               "app_version": lock["app_version"],
               "benchmark_manifest_hash": lock["benchmark_manifest_hash"],
               "annotators": index},
              open(f"{a.app}/data/index.json", "w"), indent=2)

    with open(f"{a.app}/private/credentials.md", "w") as f:
        f.write("# VisExMEM annotation -- disposable access codes (PRIVATE)\n\n")
        f.write(f"Generated {time.strftime('%Y-%m-%d %H:%M')}. "
                "These are throwaway codes created for this task only.\n"
                "They are NOT anyone's real password. Do not commit this file.\n\n")
        f.write("| Name | Username | Access code | Samples | Role |\n")
        f.write("|---|---|---|---|---|\n")
        for n, u, p, k, r in creds:
            f.write(f"| {n} | `{u}` | `{p}` | {k} | {r} |\n")
    os.chmod(f"{a.app}/private/credentials.md", 0o600)
    print(json.dumps({"bundles": len(index),
                      "sizes": {k: v["assignment_size"] for k, v in index.items()},
                      "credentials": f"{a.app}/private/credentials.md (chmod 600)",
                      "kdf_iterations": ITER}, indent=2))


if __name__ == "__main__":
    main()
