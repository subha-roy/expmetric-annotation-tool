#!/usr/bin/env python3
"""Apply pilot-only transport metadata cleanup without regenerating credentials."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from refresh_visexmem_bundles import atomic_json, credentials, decrypt, encrypt

APP = Path(__file__).resolve().parents[1]


def normalized(payload: dict) -> dict:
    value = copy.deepcopy(payload)
    value["app_version"] = "2.1.0"
    for item in value["items"]:
        item.pop("is_common30", None)
    return value


def main() -> None:
    password = credentials(APP / "private/pilot_credentials.md")["pilot"]
    bundle_path = APP / "data/bundle_pilot.json"
    before = decrypt(json.loads(bundle_path.read_text()), password)
    after = normalized(before)

    assert before["annotator_id"] == after["annotator_id"] == "pilot"
    assert before["assignment_hash"] == after["assignment_hash"]
    assert before["assignment_size"] == after["assignment_size"] == 10
    assert normalized(before) == after

    atomic_json(bundle_path, encrypt(after, password))
    check = decrypt(json.loads(bundle_path.read_text()), password)
    assert check == after
    print(json.dumps({
        "status": "PASS",
        "pilot_items": len(after["items"]),
        "credentials_regenerated": False,
        "assignment_hash_unchanged": True,
        "scientific_payload_unchanged": True,
        "removed_item_keys": ["is_common30"],
        "app_version": after["app_version"],
    }, indent=2))


if __name__ == "__main__":
    main()
