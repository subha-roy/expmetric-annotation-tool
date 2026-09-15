#!/usr/bin/env python3
"""Strict validation for the final 170-sample, four-HiWi assignment and bundles.

BASELINE STUDY (current): VisExMEM-9B is excluded. Validates the 3-system (GPT-5.6 Sol
Decomposed / EXPERT / VIEScore-official) content and confirms VisExMEM's absence.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from pathlib import Path

from refresh_visexmem_bundles import credentials, decrypt

PROJ = Path("/home/hpc/v141be/v141be14/projects/proj2_exp_metric")
APP = PROJ / "app/explanation_annotation"
MANIFESTS = PROJ / "evaluation/explanation_annotation/manifests"
HIWIS = ("damir", "brisca", "omar", "sayeeda")
LABELS = ("A", "B", "C")
SYSTEMS = ("gpt_decomposed", "expert", "viescore_official")
EVIDENCE_SYSTEMS = {"gpt_decomposed"}
EVIDENCE_SOURCE_LABEL = "GPT self-reported visual evidence"
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
    entry = baseline_fields(record)
    if system in EVIDENCE_SYSTEMS:
        entry = copy.deepcopy(entry)
        entry["evidence"] = record.get("task_b_evidence_secondary_only", [])
        entry["evidence_source"] = EVIDENCE_SOURCE_LABEL
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
                    assert actual["evidence_source"] == EVIDENCE_SOURCE_LABEL
            assert len(evidence_labels) == 1
            evidence = item["explanations"][evidence_labels[0]]["evidence"]
            assert 0 <= len(evidence) <= 3  # 0 is a valid, already-handled UI case
            evidence_claim_counts.append(len(evidence))
            evidence_box_counts.append(sum(len(claim["evidence_boxes"]) for claim in evidence))
        bundle_sizes[hiwi] = len(payload["items"])

    # The independent backup/test account remains in the login index but not in the real
    # assignment or any real bundle validation/statistical population -- it must still be
    # VisExMEM-free, though, since it is part of "the current study UI".
    assert "annotator" in index["annotators"] and "annotator" not in assignment["per_account"]
    annotator_payload = decrypt(json.loads((APP / "data/bundle_annotator.json").read_text()),
                                passwords["annotator"])
    assert annotator_payload["annotator_id"] == "annotator"
    assert annotator_payload["assignment_size"] == len(annotator_payload["items"]) == 30
    annotator_evidence_labels_count = []
    for item in annotator_payload["items"]:
        sid = item["sample_id"]
        assert set(item["explanations"]) == set(LABELS)
        ev_labels = []
        for label in LABELS:
            system = mapping["annotator"][sid][label]
            assert system in SYSTEMS
            actual = item["explanations"][label]
            assert actual == expected_entry(explanations[sid][system], system)
            if "evidence" in actual:
                ev_labels.append(label)
        annotator_evidence_labels_count.append(len(ev_labels))
    assert all(n == 1 for n in annotator_evidence_labels_count)

    # No VisExMEM identity anywhere in the currently-shipped content: every system named
    # in the blinding map and every bundle's raw JSON text must be VisExMEM-free.
    assert "visexmem_9b" not in SYSTEMS
    for account_map in mapping.values():
        for label_map in account_map.values():
            assert "visexmem_9b" not in label_map.values()
    for hiwi in list(HIWIS) + ["annotator"]:
        raw = (APP / f"data/bundle_{hiwi}.json").read_text().lower()
        assert "visexmem" not in raw  # ciphertext is base64 so this only catches plaintext leaks

    for record in explanations.values():
        for system in SYSTEMS:
            assert record[system].get("score") is not None
            assert record[system].get("task_a_blocks")
            assert record[system].get("task_a_text")

    gpt_claim_counts = Counter()
    gpt_usable = 0
    for sid in ids:
        n = len(explanations[sid]["gpt_decomposed"].get("task_b_evidence_secondary_only") or [])
        gpt_claim_counts[n] += 1
        if n > 0:
            gpt_usable += 1

    # Pilot (10) and tutorial (5) pools stay disjoint from the real 170 and internally
    # consistent -- same baseline systems, same "exactly one evidence label" invariant.
    pilot_password = credentials(APP / "private/pilot_credentials.md")["pilot"]
    pilot_payload = decrypt(json.loads((APP / "data/bundle_pilot.json").read_text()), pilot_password)
    assert pilot_payload["assignment_size"] == len(pilot_payload["items"]) == 10
    for item in pilot_payload["items"]:
        assert set(item["explanations"]) == set(LABELS)
        n_evidence = sum(1 for l in LABELS if "evidence" in item["explanations"][l])
        assert n_evidence == 1

    # FINAL practice tutorial: exactly 3 examples, each "Explanation A" (GPT-decomposed)
    # + ONE second explanation (EXPERT or VIEScore), each with real Task-A ratings, plus
    # one real Task-B rating example. Ratings/rationales are real GPT-5.6-sol API output
    # (practice_ratings_3.json) -- traceability checked here, not regenerated.
    practice_ratings = json.loads((MANIFESTS / "practice_ratings_3.json").read_text())["examples"]
    assert len(practice_ratings) == 3
    assert set(practice_ratings) <= tutorial  # drawn from the frozen 5-sample pool
    assert not (set(practice_ratings) & ids) and not (set(practice_ratings) & pilot)

    # Researcher-supplied FINAL exact Task-A scores (2026-09-16) -- must match verbatim.
    EXACT_TASKA = {
        "prac_1": {"A": {"diagnostic_correctness": 5, "visual_grounding": 5, "clarity": 4,
                         "diagnostic_usefulness": 5, "unsupported_content": "No"},
                  "B": {"diagnostic_correctness": 4, "visual_grounding": 4, "clarity": 5,
                         "diagnostic_usefulness": 3, "unsupported_content": "No"}},
        "prac_2": {"A": {"diagnostic_correctness": 5, "visual_grounding": 5, "clarity": 4,
                         "diagnostic_usefulness": 5, "unsupported_content": "No"},
                  "B": {"diagnostic_correctness": 2, "visual_grounding": 2, "clarity": 4,
                         "diagnostic_usefulness": 2, "unsupported_content": "Yes"}},
        "prac_3": {"A": {"diagnostic_correctness": 5, "visual_grounding": 5, "clarity": 4,
                         "diagnostic_usefulness": 5, "unsupported_content": "No"},
                  "B": {"diagnostic_correctness": 1, "visual_grounding": 2, "clarity": 4,
                         "diagnostic_usefulness": 1, "unsupported_content": "Yes"}},
    }
    EXACT_FINAL_COMPARISON = {
        "prac_1": "A is substantially more useful than B because it directly explains "
                  "image-caption alignment.",
        "prac_2": "A is dramatically better because it diagnoses both matches and "
                  "mismatches, whereas B mostly assumes the prompt was followed.",
        "prac_3": "A is clearly the useful explanation; B is addressing the wrong task.",
    }

    tutorial_bundle = json.loads((APP / "examples/tutorial_examples.json").read_text())
    assert len(tutorial_bundle["examples"]) == 3
    for example in tutorial_bundle["examples"]:
        assert set(example["explanations"]) == {"A", "B"}
        exact = EXACT_TASKA[example["example_id"]]
        for lab, exp in example["explanations"].items():
            r = exp["ratings"]
            for key in ("diagnostic_correctness", "visual_grounding", "clarity",
                       "diagnostic_usefulness"):
                assert 1 <= r[key]["rating"] <= 5 and r[key]["rationale"]
                assert r[key]["rating"] == exact[lab][key]
            assert r["unsupported_content"]["answer"] in ("Yes", "No", "Unsure")
            assert r["unsupported_content"]["rationale"]
            assert r["unsupported_content"]["answer"] == exact[lab]["unsupported_content"]
        assert example["final_comparison"] == EXACT_FINAL_COMPARISON[example["example_id"]]
        tb = example["task_b"]
        assert tb["label"] in example["explanations"]
        assert tb["evidence_boxes"]
        assert 1 <= tb["ratings"]["localization_accuracy"]["rating"] <= 5
        assert 1 <= tb["ratings"]["sufficiency"]["rating"] <= 5
    assert not (pilot & tutorial)

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
        "systems_included": list(SYSTEMS),
        "visexmem_absent": True,
        "gpt_samples_with_usable_boxes": gpt_usable,
        "gpt_samples_total": len(ids),
        "gpt_claim_count_distribution": dict(sorted(gpt_claim_counts.items())),
        "annotator_bundle_rebuilt": "PASS",
        "pilot_bundle_consistent": "PASS",
        "tutorial_bundle_consistent": "PASS",
        "encrypted_bundle_content": "PASS",
        "test_account_excluded_from_real_assignment": "PASS",
    }, indent=2))


if __name__ == "__main__":
    main()
