#!/usr/bin/env python3
"""Strict validation for the final 170-sample, four-HiWi assignment and bundles."""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from pathlib import Path

from refresh_visexmem_bundles import credentials, decrypt
from task_a_presentation import presentation_fields

PROJ = Path("/home/hpc/v141be/v141be14/projects/proj2_exp_metric")
APP = PROJ / "app/explanation_annotation"
MANIFESTS = PROJ / "evaluation/explanation_annotation/manifests"
HIWIS = ("damir", "brisca", "omar", "sayeeda")
LABELS = ("A", "B", "C", "D")
SYSTEMS = ("visexmem_9b", "gpt_decomposed", "expert", "viescore_official")
CELLS = (
    ("i2t", "easy"), ("t2i", "easy"),
    ("i2t", "medium"), ("t2i", "medium"),
    ("i2t", "hard"), ("t2i", "hard"),
)
PAIR_TARGETS = {
    "damir+brisca": 24, "omar+sayeeda": 24,
    "damir+omar": 23, "damir+sayeeda": 23,
    "brisca+omar": 23, "brisca+sayeeda": 23,
}


def sha_json(value) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def baseline_fields(record: dict) -> dict:
    return {"blocks": record.get("task_a_blocks") or [],
            "text": record.get("task_a_text"),
            "word_count": record.get("word_count")}


def expected_entry(record: dict, system: str) -> dict:
    entry = (presentation_fields(record) if system == "visexmem_9b"
             else baseline_fields(record))
    if system == "visexmem_9b":
        entry = copy.deepcopy(entry)
        entry["evidence"] = record.get("task_b_evidence", [])
        entry["box_coord_system"] = record.get("box_coord_system")
    return entry


def main() -> None:
    manifest = json.loads((MANIFESTS / "sample_manifest_170.json").read_text())
    assignment = json.loads((MANIFESTS / "annotator_assignment_170.json").read_text())
    explanations = json.loads((MANIFESTS / "explanations_170.json").read_text())
    pilot = set(json.loads((MANIFESTS / "pilot_pool_10.json").read_text())["sample_ids"])
    tutorial = set(json.loads((MANIFESTS / "tutorial_pool_5.json").read_text())["sample_ids"])
    valid = set(json.loads((MANIFESTS / "coverage_audit.json").read_text())
                ["common_ok_intersection"])
    mapping = json.loads((APP / "private/blinding_map.json").read_text())["mapping"]
    passwords = credentials(APP / "private/credentials.md")
    index = json.loads((APP / "data/index.json").read_text())

    samples = manifest["samples"]
    by_id = {sample["sample_id"]: sample for sample in samples}
    ids = set(by_id)
    common = set(assignment["common_samples"])
    assert len(samples) == len(ids) == 170
    assert len(common) == 30
    assert not ids & pilot and not ids & tutorial
    assert ids <= valid and set(explanations) == ids
    assert assignment["accounts"] == list(HIWIS)
    assert {key: len(value) for key, value in assignment["pair_blocks"].items()} == PAIR_TARGETS

    memberships = {sid: set() for sid in ids}
    for hiwi in HIWIS:
        for sid in assignment["per_account"][hiwi]["queue"]:
            memberships[sid].add(hiwi)
    assert all(len(memberships[sid]) == (4 if sid in common else 2) for sid in ids)
    for pair_name, values in assignment["pair_blocks"].items():
        expected_pair = set(pair_name.split("+"))
        assert all(memberships[sid] == expected_pair for sid in values)

    manifest_hash = sha_json({"sample_ids": sorted(ids), "seed": manifest["seed"]})
    bundle_sizes, evidence_claim_counts, evidence_box_counts = {}, [], []
    allowed_item_keys = {
        "sample_id", "order", "text", "image", "image_native_width",
        "image_native_height", "explanations",
    }
    for hiwi in HIWIS:
        payload = decrypt(json.loads((APP / f"data/bundle_{hiwi}.json").read_text()),
                          passwords[hiwi])
        queue = assignment["per_account"][hiwi]["queue"]
        assert payload["annotator_id"] == hiwi and payload["annotator_role"] == "hiwi"
        assert payload["assignment_size"] == len(payload["items"]) == len(queue) == 100
        assert payload["assignment_hash"] == sha_json(queue)
        assert payload["manifest_hash"] == manifest_hash
        assert [item["sample_id"] for item in payload["items"]] == queue
        assert index["annotators"][hiwi]["assignment_hash"] == payload["assignment_hash"]
        assert index["annotators"][hiwi]["assignment_size"] == 100

        for position, item in enumerate(payload["items"]):
            sid = item["sample_id"]
            assert item["order"] == position
            assert set(item) == allowed_item_keys
            assert set(item["explanations"]) == set(LABELS)
            assert (APP / item["image"]).is_file()
            evidence_labels = []
            for label in LABELS:
                system = mapping[hiwi][sid][label]
                assert system in SYSTEMS
                actual = item["explanations"][label]
                assert actual == expected_entry(explanations[sid][system], system)
                if "evidence" in actual:
                    evidence_labels.append(label)
            assert len(evidence_labels) == 1
            evidence = item["explanations"][evidence_labels[0]]["evidence"]
            assert 1 <= len(evidence) <= 3
            evidence_claim_counts.append(len(evidence))
            evidence_box_counts.append(sum(len(claim["evidence_boxes"]) for claim in evidence))
        bundle_sizes[hiwi] = len(payload["items"])

    # The independent backup/test account remains in the login index but not in the real
    # assignment or any real bundle validation/statistical population.
    assert "annotator" in index["annotators"] and "annotator" not in assignment["per_account"]

    for record in explanations.values():
        for system in SYSTEMS:
            assert record[system].get("score") is not None
            assert record[system].get("task_a_blocks")
            assert record[system].get("task_a_text")

    cell_counts = Counter((sample["direction"], sample["difficulty"]) for sample in samples)
    common_cells = Counter((by_id[sid]["direction"], by_id[sid]["difficulty"])
                           for sid in common)
    per_hiwi_cells = {}
    per_hiwi_alignment = {}
    for hiwi in HIWIS:
        queue = assignment["per_account"][hiwi]["queue"]
        per_hiwi_cells[hiwi] = dict(Counter(
            f"{by_id[sid]['direction']}/{by_id[sid]['difficulty']}" for sid in queue))
        per_hiwi_alignment[hiwi] = dict(Counter(by_id[sid]["alignment_label"] for sid in queue))

    print(json.dumps({
        "status": "PASS",
        "unique_samples": len(ids),
        "common_samples": len(common),
        "noncommon_samples": len(ids - common),
        "bundle_sizes": bundle_sizes,
        "cell_counts": {f"{d}/{level}": cell_counts[(d, level)] for d, level in CELLS},
        "common_cell_counts": {f"{d}/{level}": common_cells[(d, level)] for d, level in CELLS},
        "pair_counts": PAIR_TARGETS,
        "overall_alignment": dict(Counter(sample["alignment_label"] for sample in samples)),
        "per_hiwi_cells": per_hiwi_cells,
        "per_hiwi_alignment": per_hiwi_alignment,
        "pilot_overlap": 0,
        "tutorial_overlap": 0,
        "task_b_claim_range": [min(evidence_claim_counts), max(evidence_claim_counts)],
        "task_b_box_range": [min(evidence_box_counts), max(evidence_box_counts)],
        "encrypted_bundle_content": "PASS",
        "test_account_excluded_from_real_assignment": "PASS",
    }, indent=2))


if __name__ == "__main__":
    main()
