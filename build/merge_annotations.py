"""Ingest, validate and merge returned annotation JSON files.

Collection hygiene only -- this deliberately computes no agreement statistics. It tells
you what came back, whether it is trustworthy, and what is still missing.
"""
from __future__ import annotations
import argparse, collections, glob, json, os, sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="directory of returned *.json files")
    ap.add_argument("--app", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    lock = json.load(open(f"{a.app}/ASSIGNMENT_LOCK.json"))
    audit = json.load(open(f"{a.app}/private/assignment_audit.json"))
    expected = {k: set(v["queue"]) for k, v in audit["per_annotator"].items()}
    common = set(audit["common_sample_ids"])

    files = sorted(glob.glob(f"{a.dir}/*.json"))
    seen, problems, merged = {}, [], []
    for f in files:
        try:
            d = json.load(open(f))
        except Exception as e:
            problems.append({"file": os.path.basename(f), "error": f"unparseable: {e}"})
            continue
        aid = d.get("annotator_id")
        base = os.path.basename(f)
        if aid not in expected:
            problems.append({"file": base, "error": f"unknown annotator {aid!r}"}); continue
        if d.get("schema_version") != lock["schema_version"]:
            problems.append({"file": base, "error": "schema_version mismatch"})
        if d.get("assignment_hash") != lock["assignment_hashes"][aid]:
            problems.append({"file": base, "error": "assignment_hash mismatch"})
        if d.get("benchmark_manifest_hash") != lock["benchmark_manifest_hash"]:
            problems.append({"file": base, "error": "benchmark_manifest_hash mismatch"})
        if aid in seen:
            prev = seen[aid]
            keep = f if d.get("export_timestamp", "") > prev[1].get("export_timestamp", "") else prev[0]
            problems.append({"file": base,
                             "error": f"duplicate submission for {aid}; keeping {os.path.basename(keep)}"})
            if keep != f:
                continue
        seen[aid] = (f, d)

        got = {x["sample_id"] for x in d.get("annotations", [])}
        miss = expected[aid] - got
        extra = got - expected[aid]
        if miss:
            problems.append({"file": base, "error": f"{len(miss)} expected samples absent"})
        if extra:
            problems.append({"file": base, "error": f"{len(extra)} unexpected samples"})

        for s in d.get("annotations", []):
            for p in s.get("decomposition", []):
                merged.append({
                    "annotator_id": aid, "annotator_role": d.get("annotator_role"),
                    "sample_id": s["sample_id"], "part_id": p["part_id"],
                    "part_index": p.get("part_index"),
                    "decomposition_label": p.get("decomposition_label"),
                    "human_atomic_support_0_to_4": p.get("human_atomic_support_0_to_4"),
                    "atomic_cannot_judge": p.get("atomic_cannot_judge"),
                    "human_overall_alignment_1_to_7": s.get("human_overall_alignment_1_to_7"),
                    "missing_visual_information": s.get("missing_visual_information"),
                    "technical_issue": s.get("technical_issue"),
                    "is_common_iaa_sample": s["sample_id"] in common,
                })

    completion = {k: {"expected": len(expected[k]),
                      "received": (len(seen[k][1].get("annotations", [])) if k in seen else 0),
                      "completed_count": (seen[k][1].get("completed_count") if k in seen else 0),
                      "returned": k in seen}
                  for k in expected}
    rep = {"files_seen": len(files), "annotators_returned": sorted(seen),
           "annotators_missing": sorted(set(expected) - set(seen)),
           "completion": completion,
           "common_iaa_sample_ids": sorted(common),
           "common_iaa_rows": sum(1 for m in merged if m["is_common_iaa_sample"]),
           "merged_rows": len(merged),
           "annotators_per_common_sample": dict(collections.Counter(
               m["sample_id"] for m in merged if m["is_common_iaa_sample"]).most_common(3)),
           "problems": problems}
    out = a.out or f"{a.dir}/merged"
    os.makedirs(out, exist_ok=True)
    json.dump(merged, open(f"{out}/merged_annotations.json", "w"), indent=1)
    json.dump(rep, open(f"{out}/merge_report.json", "w"), indent=2)
    print(json.dumps({k: v for k, v in rep.items()
                      if k != "common_iaa_sample_ids"}, indent=2))
    if problems:
        print(f"\n{len(problems)} problem(s) -- see {out}/merge_report.json")
    sys.exit(0)


if __name__ == "__main__":
    main()
