"""Deterministic annotator assignment for the 600-sample VisExMEM human benchmark.

Reads the FROZEN benchmark and never modifies it. Produces:
  * 30 common inter-annotator-agreement samples, stratified 5 per
    direction x difficulty cell;
  * four pairwise-disjoint HiWi partitions of the remaining 570;
  * three common-only colleague assignments;
  * per-annotator shuffled queues in which the common samples are interspersed and
    NOT identifiable;
  * ASSIGNMENT_LOCK.json.

Difficulty/direction/source/alignment are used here for stratification only. They are
private construction metadata and are never written into an annotator bundle.
"""
from __future__ import annotations
import argparse, collections, hashlib, json, os, random, sys, time

import pyarrow.parquet as pq

BENCH = "/hnvme/workspace/v141be14-VisExMEM/benchmark"
FROZEN = f"{BENCH}/frozen"
ANNO = f"{BENCH}/annotation"
SEED = 20260826
SCHEMA_VERSION = "visexmem-annotation-1.0.0"

HIWIS = ["damir", "brisca", "omar", "sayeeda"]
COLLEAGUES = ["christian", "chris", "zhipin"]
NAMES = {"damir": "Damir", "brisca": "Brisca", "omar": "Omar", "sayeeda": "Sayeeda",
         "christian": "Christian", "chris": "Chris", "zhipin": "Zhipin"}
COMMON_PER_CELL = 5

# exact per-cell unique allocation, as specified
ALLOC = {
    ("i2t", "easy"):   {"damir": 23, "brisca": 24, "omar": 24, "sayeeda": 24},
    ("i2t", "medium"): {"damir": 24, "brisca": 24, "omar": 23, "sayeeda": 24},
    ("i2t", "hard"):   {"damir": 24, "brisca": 24, "omar": 24, "sayeeda": 23},
    ("t2i", "easy"):   {"damir": 24, "brisca": 23, "omar": 24, "sayeeda": 24},
    ("t2i", "medium"): {"damir": 24, "brisca": 24, "omar": 23, "sayeeda": 24},
    ("t2i", "hard"):   {"damir": 24, "brisca": 24, "omar": 24, "sayeeda": 23},
}


def sha_json(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def load_benchmark():
    """-> (samples, parts_by_sample). `samples` carries PRIVATE fields for stratification."""
    out, parts = {}, collections.defaultdict(list)
    specs = [("i2t", "image_to_text_manifest.parquet", "image_to_text_parts.parquet",
              "caption", "source"),
             ("t2i", "text_to_image_manifest.parquet", "text_to_image_parts.parquet",
              "evaluation_text", "source_dataset")]
    for direction, mf, pf, textcol, srccol in specs:
        for r in pq.read_table(f"{FROZEN}/{mf}").to_pylist():
            out[r["sample_id"]] = {
                "sample_id": r["sample_id"], "direction": direction,
                "text": r[textcol], "image_path": r["image_path"],
                "image_sha256": r["image_sha256"],
                # PRIVATE -- stratification only
                "_difficulty": r["difficulty"], "_alignment": r["alignment"],
                "_source": r[srccol],
                "_challenge": r.get("primary_challenge"),
            }
        for p in pq.read_table(f"{FROZEN}/{pf}").to_pylist():
            parts[p["sample_id"]].append(
                {"part_id": p["part_id"], "part_index": p["part_index"],
                 "part_type": p["part_type"], "atomic_claim": p["atomic_claim"]})
    for k in parts:
        parts[k].sort(key=lambda x: x["part_index"])
    return out, parts


def pick_common(samples, rng):
    """5 per direction x difficulty, spread over alignment so the IAA set is not skewed."""
    common = []
    for d in ("i2t", "t2i"):
        for diff in ("easy", "medium", "hard"):
            cell = [s for s in samples.values()
                    if s["direction"] == d and s["_difficulty"] == diff]
            by_al = collections.defaultdict(list)
            for s in cell:
                by_al[s["_alignment"]].append(s)
            for v in by_al.values():
                rng.shuffle(v)
            chosen, order = [], ["partial", "high", "low"]
            i = 0
            while len(chosen) < COMMON_PER_CELL:
                al = order[i % len(order)]
                if by_al.get(al):
                    chosen.append(by_al[al].pop())
                elif not any(by_al.values()):
                    break
                i += 1
            common += chosen[:COMMON_PER_CELL]
    return sorted(s["sample_id"] for s in common)


def partition_unique(samples, common, rng):
    uniq = {h: [] for h in HIWIS}
    for d in ("i2t", "t2i"):
        for diff in ("easy", "medium", "hard"):
            cell = [s for s in samples.values()
                    if s["direction"] == d and s["_difficulty"] == diff
                    and s["sample_id"] not in common]
            # secondary balance: deal round-robin within alignment groups so each HiWi
            # gets a comparable alignment/source mix without disturbing the exact counts
            cell.sort(key=lambda s: (str(s["_alignment"]), str(s["_source"]),
                                     s["sample_id"]))
            rng.shuffle(cell)
            cell.sort(key=lambda s: str(s["_alignment"]))
            need = dict(ALLOC[(d, diff)])
            order = [h for h in HIWIS]
            rng.shuffle(order)
            i = 0
            for s in cell:
                for _ in range(len(order)):
                    h = order[i % len(order)]
                    i += 1
                    if need[h] > 0:
                        uniq[h].append(s["sample_id"]); need[h] -= 1
                        break
            assert all(v == 0 for v in need.values()), (d, diff, need)
    return uniq


def build_queue(ids_unique, ids_common, seed):
    """Interleave common samples through the queue so they are not identifiable."""
    rng = random.Random(seed)
    u = list(ids_unique); c = list(ids_common)
    rng.shuffle(u); rng.shuffle(c)
    if not u:
        return c
    # place each common sample at a distinct pseudo-random slot
    slots = sorted(rng.sample(range(len(u) + len(c)), len(c)))
    out, ui, ci = [], 0, 0
    for pos in range(len(u) + len(c)):
        if ci < len(c) and pos == slots[ci]:
            out.append(c[ci]); ci += 1
        else:
            out.append(u[ui]); ui += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args()
    rng = random.Random(a.seed)

    samples, parts = load_benchmark()
    assert len(samples) == 600, f"expected 600 benchmark samples, got {len(samples)}"

    common = pick_common(samples, rng)
    assert len(common) == 30 and len(set(common)) == 30, len(common)
    uniq = partition_unique(samples, set(common), rng)

    assign = {}
    for h in HIWIS:
        assign[h] = {"role": "hiwi", "unique": sorted(uniq[h]), "common": common,
                     "queue": build_queue(uniq[h], common, a.seed + hash(h) % 10000)}
    for c in COLLEAGUES:
        assign[c] = {"role": "colleague", "unique": [], "common": common,
                     "queue": build_queue([], common, a.seed + hash(c) % 10000)}

    # ---- integrity
    prob = []
    allu = [i for h in HIWIS for i in assign[h]["unique"]]
    if len(allu) != 570 or len(set(allu)) != 570:
        prob.append(f"unique union is {len(allu)} ({len(set(allu))} distinct), expected 570")
    if set(allu) | set(common) != set(samples):
        prob.append("unique + common does not exhaust the 600 benchmark samples")
    for i in range(len(HIWIS)):
        for j in range(i + 1, len(HIWIS)):
            ov = set(assign[HIWIS[i]]["unique"]) & set(assign[HIWIS[j]]["unique"])
            if ov:
                prob.append(f"{HIWIS[i]}/{HIWIS[j]} overlap: {len(ov)}")
    if any(assign[k]["common"] != common for k in assign):
        prob.append("annotators do not share an identical common set")
    exp = {"damir": 173, "brisca": 173, "omar": 172, "sayeeda": 172,
           "christian": 30, "chris": 30, "zhipin": 30}
    for k, n in exp.items():
        if len(assign[k]["queue"]) != n:
            prob.append(f"{k} queue is {len(assign[k]['queue'])}, expected {n}")
    sessions = sum(len(assign[k]["queue"]) for k in assign)
    if sessions != 780:
        prob.append(f"total sessions {sessions} != 780")
    for k in assign:
        for sid in assign[k]["queue"]:
            if not parts.get(sid):
                prob.append(f"{sid} has no decomposition parts")
                break
    if prob:
        print(json.dumps({"OK": False, "problems": prob}, indent=2)); sys.exit(2)

    os.makedirs(f"{a.out}/private", exist_ok=True)
    manifest_hash = hashlib.sha256(
        open(f"{FROZEN}/image_to_text_manifest.parquet", "rb").read() +
        open(f"{FROZEN}/text_to_image_manifest.parquet", "rb").read()).hexdigest()
    per_hash = {k: sha_json({"queue": assign[k]["queue"], "role": assign[k]["role"]})
                for k in assign}
    lock = {"schema_version": SCHEMA_VERSION, "app_version": "1.0.0",
            "benchmark_manifest_hash": manifest_hash, "assignment_seed": a.seed,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "common_set_hash": sha_json(common),
            "assignment_hashes": per_hash,
            "counts": {k: {"unique": len(assign[k]["unique"]),
                           "common": len(assign[k]["common"]),
                           "total": len(assign[k]["queue"])} for k in assign},
            "total_sessions": sessions, "n_benchmark_samples": len(samples)}
    json.dump(lock, open(f"{a.out}/ASSIGNMENT_LOCK.json", "w"), indent=2)

    audit = {"seed": a.seed, "common_sample_ids": common,
             "per_annotator": {k: {"role": assign[k]["role"],
                                   "unique_ids": assign[k]["unique"],
                                   "queue": assign[k]["queue"]} for k in assign},
             "common_strata": collections.Counter(
                 f'{samples[s]["direction"]}/{samples[s]["_difficulty"]}'
                 for s in common),
             "common_alignment": collections.Counter(
                 samples[s]["_alignment"] for s in common)}
    json.dump(audit, open(f"{a.out}/private/assignment_audit.json", "w"),
              indent=2, default=str)

    json.dump({"samples": samples, "parts": parts},
              open(f"{a.out}/private/benchmark_join.json", "w"), default=str)
    print(json.dumps({"OK": True, "counts": lock["counts"],
                      "total_sessions": sessions,
                      "common_strata": dict(audit["common_strata"]),
                      "common_alignment": dict(audit["common_alignment"]),
                      "lock": f"{a.out}/ASSIGNMENT_LOCK.json"}, indent=2))


if __name__ == "__main__":
    main()
