"""Private researcher summary of the frozen assignment."""
from __future__ import annotations
import collections, json, os

A = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
lock = json.load(open(f"{A}/ASSIGNMENT_LOCK.json"))
audit = json.load(open(f"{A}/private/assignment_audit.json"))
join = json.load(open(f"{A}/private/benchmark_join.json"))
s = join["samples"]
common = set(audit["common_sample_ids"])

rep = {"lock": {k: lock[k] for k in ("assignment_seed", "common_set_hash",
                                     "benchmark_manifest_hash", "generated_at",
                                     "schema_version", "total_sessions")},
       "assignment_hashes": lock["assignment_hashes"], "counts": lock["counts"],
       "common_sample_ids": sorted(common),
       "common_balance": {
           "direction_difficulty": dict(collections.Counter(
               f'{s[x]["direction"]}/{s[x]["_difficulty"]}' for x in common)),
           "alignment": dict(collections.Counter(s[x]["_alignment"] for x in common)),
           "source": dict(collections.Counter(s[x]["_source"] for x in common))},
       "per_annotator": {}}
for k, v in audit["per_annotator"].items():
    q = v["queue"]
    rep["per_annotator"][k] = {
        "role": v["role"], "total": len(q), "unique": len(v["unique_ids"]),
        "direction": dict(collections.Counter(s[x]["direction"] for x in q)),
        "difficulty": dict(collections.Counter(s[x]["_difficulty"] for x in q)),
        "alignment": dict(collections.Counter(s[x]["_alignment"] for x in q)),
        "source": dict(collections.Counter(s[x]["_source"] for x in q)),
        "unique_ids": v["unique_ids"]}
json.dump(rep, open(f"{A}/private/assignment_statistics.json", "w"), indent=2)
print(json.dumps({"per_annotator_balance": {
    k: {"total": v["total"], "direction": v["direction"], "difficulty": v["difficulty"]}
    for k, v in rep["per_annotator"].items()},
    "common_balance": rep["common_balance"]}, indent=2))
