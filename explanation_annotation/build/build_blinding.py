"""Deterministic per-(sample, annotator) blinding: assigns the 4 systems to labels
A/B/C/D independently for every (sample_id, account) pair, so no annotator ever sees a
consistent cross-sample ordering that could leak method identity. The mapping is PRIVATE
-- it is baked into each annotator's own encrypted bundle at build time (as already-
labelled content) and is never shipped anywhere as an explicit label->system table.
"""
import json, hashlib, random
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
MANIFEST_DIR = Path("/home/hpc/v141be/v141be14/projects/proj2_exp_metric/evaluation/explanation_annotation/manifests")
SEED = 20260915
SYSTEMS = ["visexmem_9b", "gpt_decomposed", "expert", "viescore_official"]
LABELS = ["A", "B", "C", "D"]


def order_for(sample_id, account):
    h = hashlib.sha256(f"{SEED}:{sample_id}:{account}".encode()).hexdigest()
    rng = random.Random(int(h[:16], 16))
    order = list(SYSTEMS)
    rng.shuffle(order)
    return order  # order[i] = system shown as LABELS[i]


def main():
    assignment = json.loads((MANIFEST_DIR / "annotator_assignment_170.json").read_text())
    out_path = APP / "private" / "blinding_map.json"
    previous = json.loads(out_path.read_text()) if out_path.exists() else {"mapping": {}}
    real_accounts = set(assignment["per_account"])
    # Preserve non-study test mappings verbatim; replace only the four real assignments.
    mapping = {account: value for account, value in previous.get("mapping", {}).items()
               if account not in real_accounts}
    for account, rec in assignment["per_account"].items():
        mapping[account] = {}
        for sid in rec["queue"]:
            order = order_for(sid, account)
            mapping[account][sid] = {LABELS[i]: order[i] for i in range(4)}

    out_path.write_text(json.dumps({"seed": SEED, "labels": LABELS, "systems": SYSTEMS,
                                    "mapping": mapping}, indent=2))
    print(f"Wrote {out_path}")

    # sanity: every account's label->system counts should be ~balanced across its queue
    for account, sample_map in mapping.items():
        from collections import Counter
        c = Counter()
        for lab_map in sample_map.values():
            for lab, sysname in lab_map.items():
                c[(lab, sysname)] += 1
        n = len(sample_map)
        print(f"{account}: {n} samples, label/system pair counts (expect ~{n/4:.1f} each):")
        for lab in LABELS:
            row = {sysname: c[(lab, sysname)] for sysname in SYSTEMS}
            print(f"  {lab}: {row}")


if __name__ == "__main__":
    main()
