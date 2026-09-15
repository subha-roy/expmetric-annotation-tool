#!/usr/bin/env python3
"""Refresh only VisExMEM text in shipped bundles while preserving access codes."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from task_a_presentation import presentation_fields

PROJ = Path("/home/hpc/v141be/v141be14/projects/proj2_exp_metric")
APP = Path(__file__).resolve().parents[1]
MANIFESTS = PROJ / "evaluation/explanation_annotation/manifests"
sys.path.insert(0, str(PROJ / "evaluation/explanation_annotation/scripts"))
from generate_explanations import (  # noqa: E402
    VISEXMEM_9B,
    blocks_to_plain_text,
    build_blocks_visexmem,
    build_detail_blocks_visexmem,
    build_summary_visexmem,
    jsonl,
    normalize_visexmem,
)
ITER = 600_000
LABELS = ["A", "B", "C", "D"]
SYSTEMS = ["visexmem_9b", "gpt_decomposed", "expert", "viescore_official"]
SEED = 20260915


def credentials(path):
    found = {}
    pattern = re.compile(r"\|[^|]+\|\s*`([^`]+)`\s*\|\s*`([^`]+)`")
    for line in Path(path).read_text().splitlines():
        match = pattern.search(line)
        if match:
            found[match.group(1)] = match.group(2)
    return found


def decrypt(record, password):
    raw = lambda key: base64.b64decode(record[key])
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), raw("salt"),
                              int(record["iterations"]), dklen=32)
    return json.loads(AESGCM(key).decrypt(raw("iv"), raw("ciphertext"), None))


def encrypt(payload, password):
    salt, iv = os.urandom(16), os.urandom(12)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITER, dklen=32)
    cipher = AESGCM(key).encrypt(iv, json.dumps(payload, separators=(",", ":")).encode(), None)
    enc = lambda value: base64.b64encode(value).decode()
    return {"kdf": "PBKDF2-HMAC-SHA256", "iterations": ITER,
            "cipher": "AES-GCM-256", "salt": enc(salt), "iv": enc(iv),
            "ciphertext": enc(cipher)}


def replacement(record):
    return presentation_fields(record)


def generated_presentation(source, reference):
    parts, score = normalize_visexmem(source)
    blocks = build_blocks_visexmem(parts)
    details = build_detail_blocks_visexmem(parts)
    summary = build_summary_visexmem(score, parts)
    for key, generated in (("task_a_blocks", blocks),
                           ("task_a_details_blocks", details)):
        expected_claims = [b["claim"] for b in reference.get(key) or []]
        if expected_claims != [b["claim"] for b in generated]:
            raise RuntimeError(f"VisExMEM selected claims changed in {key}")
    if reference.get("score") != score or reference.get("task_a_summary") != summary:
        raise RuntimeError("VisExMEM score or summary selection changed")
    all_blocks = blocks + details
    return {
        "task_a_summary": summary,
        "task_a_blocks": blocks,
        "task_a_details_blocks": details,
        "task_a_text": " ".join(x for x in
                                  (summary, blocks_to_plain_text(blocks),
                                   blocks_to_plain_text(details)) if x),
        "word_count": ((len(summary.split()) if summary else 0)
                       + sum(len(b["claim"].split()) + len(b["text"].split())
                             for b in all_blocks)),
    }


def atomic_json(path, value):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(value, separators=(",", ":")))
    os.replace(tmp, path)


def order_for(sample_id, salt):
    seed = int(hashlib.sha256(f"{SEED}:{salt}:{sample_id}".encode()).hexdigest()[:16], 16)
    import random
    order = list(SYSTEMS)
    random.Random(seed).shuffle(order)
    return order


def update_entry(entry, new_record):
    evidence = copy.deepcopy(entry.get("evidence"))
    coord = entry.get("box_coord_system")
    entry.update(replacement(new_record))
    if evidence is not None:
        entry["evidence"] = evidence
    if coord is not None:
        entry["box_coord_system"] = coord


def main():
    explanations = json.loads((MANIFESTS / "explanations_120.json").read_text())
    sources = {r["sample_id"]: r for r in jsonl(VISEXMEM_9B)}
    generated = {}

    def presentation(sid, reference):
        if sid not in generated:
            generated[sid] = generated_presentation(sources[sid], reference)
        return generated[sid]

    blinding = json.loads((APP / "private/blinding_map.json").read_text())["mapping"]
    creds = credentials(APP / "private/credentials.md")
    counts = {}

    for account, password in creds.items():
        path = APP / f"data/bundle_{account}.json"
        encrypted = json.loads(path.read_text())
        payload = decrypt(encrypted, password)
        before = copy.deepcopy(payload)
        for item in payload["items"]:
            sid = item["sample_id"]
            label = next(lab for lab, system in blinding[account][sid].items()
                         if system == "visexmem_9b")
            update_entry(item["explanations"][label],
                         presentation(sid, explanations[sid]["visexmem_9b"]))
        for old_item, new_item in zip(before["items"], payload["items"]):
            sid = old_item["sample_id"]
            label = next(lab for lab, system in blinding[account][sid].items()
                         if system == "visexmem_9b")
            assert {k: v for k, v in old_item.items() if k != "explanations"} == \
                   {k: v for k, v in new_item.items() if k != "explanations"}
            for lab in LABELS:
                if lab != label:
                    assert old_item["explanations"][lab] == new_item["explanations"][lab]
            assert old_item["explanations"][label].get("evidence") == \
                   new_item["explanations"][label].get("evidence")
        atomic_json(path, encrypt(payload, password))
        assert decrypt(json.loads(path.read_text()), password) == payload
        counts[account] = len(payload["items"])

    pilot_records = json.loads((MANIFESTS / "pilot_pool_10.json").read_text())["samples"]
    pilot_password = credentials(APP / "private/pilot_credentials.md")["pilot"]
    pilot_path = APP / "data/bundle_pilot.json"
    pilot_payload = decrypt(json.loads(pilot_path.read_text()), pilot_password)
    pilot_before = copy.deepcopy(pilot_payload)
    for item in pilot_payload["items"]:
        sid = item["sample_id"]
        order = order_for(sid, "pilot")
        label = LABELS[order.index("visexmem_9b")]
        update_entry(item["explanations"][label],
                     presentation(sid, pilot_records[sid]["visexmem_9b"]))
    for old_item, new_item in zip(pilot_before["items"], pilot_payload["items"]):
        sid = old_item["sample_id"]
        label = LABELS[order_for(sid, "pilot").index("visexmem_9b")]
        for lab in LABELS:
            if lab != label:
                assert old_item["explanations"][lab] == new_item["explanations"][lab]
        assert old_item["explanations"][label].get("evidence") == \
               new_item["explanations"][label].get("evidence")
    atomic_json(pilot_path, encrypt(pilot_payload, pilot_password))
    assert decrypt(json.loads(pilot_path.read_text()), pilot_password) == pilot_payload
    counts["pilot"] = len(pilot_payload["items"])

    tutorial_records = json.loads((MANIFESTS / "tutorial_pool_5.json").read_text())["samples"]
    tutorial_path = APP / "examples/tutorial_examples.json"
    tutorial = json.loads(tutorial_path.read_text())
    tutorial_before = copy.deepcopy(tutorial)
    for item in tutorial["examples"]:
        sid = next(s for s, rec in tutorial_records.items()
                   if Path(rec["image_path"]).name == Path(item["image"]).name)
        order = order_for(sid, "practice")
        label = LABELS[order.index("visexmem_9b")]
        update_entry(item["explanations"][label],
                     presentation(sid, tutorial_records[sid]["visexmem_9b"]))
    for old_item, new_item in zip(tutorial_before["examples"], tutorial["examples"]):
        sid = next(s for s, rec in tutorial_records.items()
                   if Path(rec["image_path"]).name == Path(old_item["image"]).name)
        label = LABELS[order_for(sid, "practice").index("visexmem_9b")]
        for lab in LABELS:
            if lab != label:
                assert old_item["explanations"][lab] == new_item["explanations"][lab]
        assert old_item["explanations"][label].get("evidence") == \
               new_item["explanations"][label].get("evidence")
    tutorial_path.write_text(json.dumps(tutorial, indent=2) + "\n")
    counts["tutorial"] = len(tutorial["examples"])
    print(json.dumps({"status": "PASS", "credentials_regenerated": False,
                      "non_visexmem_payloads_unchanged": True,
                      "task_b_evidence_unchanged": True, "updated": counts}, indent=2))


if __name__ == "__main__":
    main()
