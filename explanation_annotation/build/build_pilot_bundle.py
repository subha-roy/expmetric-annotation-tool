"""Build the PILOT account's bundle: the 10 timed pilot samples only, independent of the
final real-HiWi assignment and its blinding map. Writes to data/bundle_pilot.json and
data/pilot_index.json only -- the existing pilot access code in private/pilot_credentials.md
is reused verbatim and never rewritten -- so it never touches or depends on the
candidate-assignment artifacts.

BASELINE STUDY (current): VisExMEM-9B is excluded, same as the real-HiWi bundles. Only
GPT-5.6 Sol Decomposed, EXPERT, and VIEScore-official are shown, and Task-B evidence is
GPT's own frozen self-reported boxes (never regenerated) -- see build_bundles.py's
docstring for the full rationale.
"""
from __future__ import annotations
import hashlib, json, os, random
from pathlib import Path
from build_bundles import credentials, encrypt

ITER = 600_000
APP = Path(__file__).resolve().parents[1]
MANIFEST_DIR = Path("/home/hpc/v141be/v141be14/projects/proj2_exp_metric/evaluation/explanation_annotation/manifests")
SEED = 20260915
LABELS = ["A", "B", "C"]
SYSTEMS = ["gpt_decomposed", "expert", "viescore_official"]
EVIDENCE_SYSTEMS = {"gpt_decomposed"}
EVIDENCE_SOURCE_LABEL = "GPT self-reported visual evidence"


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
                     "text": sysrec.get("task_a_text"),
                     "word_count": sysrec.get("word_count")}
            if sysname in EVIDENCE_SYSTEMS:
                entry["evidence"] = sysrec.get("task_b_evidence_secondary_only", [])
                entry["evidence_source"] = EVIDENCE_SOURCE_LABEL
                entry["box_coord_system"] = sysrec.get("box_coord_system")
            explanations_by_label[lab] = entry
        items.append({
            "sample_id": sid, "order": i, "text": s["text"],
            "image": f'images/{Path(s["image_path"]).name}',
            "image_native_width": s.get("image_native_width"),
            "image_native_height": s.get("image_native_height"),
            "explanations": explanations_by_label,
        })

    schema_version = "explanation-annotation-pilot-1.0.0"
    app_version = "2.1.0"
    manifest_hash = sha_json({"sample_ids": sorted(sids), "seed": pilot["seed"], "kind": "pilot_10"})
    cred_path = APP / "private" / "pilot_credentials.md"
    pw = credentials(cred_path)["pilot"]  # reuse the existing code -- never regenerated
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

    print(json.dumps({"account": "pilot", "n_items": len(items),
                      "credentials_regenerated": False,
                      "systems": SYSTEMS,
                      "visexmem_excluded": True,
                      "pilot_sample_order": queue}, indent=2))


if __name__ == "__main__":
    main()
