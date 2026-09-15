#!/usr/bin/env python3
"""Validate the frozen timed-pilot bundle and static annotation workflow."""
from __future__ import annotations

import copy
import hashlib
import json
import random
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path

from PIL import Image
from refresh_visexmem_bundles import credentials, decrypt, order_for
from task_a_presentation import presentation_fields

PROJ = Path("/home/hpc/v141be/v141be14/projects/proj2_exp_metric")
APP = PROJ / "app/explanation_annotation"
MANIFESTS = PROJ / "evaluation/explanation_annotation/manifests"
LABELS = ["A", "B", "C", "D"]
SYSTEMS = ["visexmem_9b", "gpt_decomposed", "expert", "viescore_official"]
SEED = 20260915


class VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hidden = 0
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)


def sha_json(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def baseline_fields(record: dict) -> dict:
    return {
        "blocks": record.get("task_a_blocks") or [],
        "text": record.get("task_a_text"),
        "word_count": record.get("word_count"),
    }


def expected_entry(record: dict, system: str) -> dict:
    entry = (presentation_fields(record) if system == "visexmem_9b"
             else baseline_fields(record))
    if system == "visexmem_9b":
        entry = copy.deepcopy(entry)
        entry["evidence"] = record.get("task_b_evidence", [])
        entry["box_coord_system"] = record.get("box_coord_system")
    return entry


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    pilot = json.loads((MANIFESTS / "pilot_pool_10.json").read_text())
    real = json.loads((MANIFESTS / "sample_manifest_170.json").read_text())
    password = credentials(APP / "private/pilot_credentials.md")["pilot"]
    payload = decrypt(json.loads((APP / "data/bundle_pilot.json").read_text()), password)
    app_js = (APP / "app.js").read_text()
    index_html = (APP / "index.html").read_text()

    expected_ids = set(pilot["sample_ids"])
    actual_ids = [item["sample_id"] for item in payload["items"]]
    real_ids = {item["sample_id"] for item in real["samples"]}
    queue = list(pilot["sample_ids"])
    random.Random(SEED + 777).shuffle(queue)

    require(payload["annotator_id"] == "pilot", "not the pilot account")
    require(payload.get("annotator_role") == "pilot_test", "pilot role missing")
    require(payload["assignment_size"] == len(actual_ids) == 10, "pilot must have 10 items")
    require(actual_ids == queue, "pilot order changed")
    require(set(actual_ids) == expected_ids, "pilot sample membership changed")
    require(not (expected_ids & real_ids), "pilot overlaps the real study")
    require(payload["assignment_hash"] == sha_json(queue), "assignment hash mismatch")

    evidence_counts = []
    box_counts = []
    forbidden_item_keys = {
        "difficulty", "direction", "alignment_label", "human_overall_alignment_mean",
        "is_common30", "benchmark", "checkpoint", "model", "system", "score", "q_i",
    }
    allowed_item_keys = {
        "sample_id", "order", "text", "image", "image_native_width",
        "image_native_height", "explanations",
    }
    for index, item in enumerate(payload["items"]):
        sid = item["sample_id"]
        source = pilot["samples"][sid]
        require(item["order"] == index, f"order index changed: {sid}")
        require(set(item) == allowed_item_keys, f"unexpected item metadata: {sid}")
        require(not (set(item) & forbidden_item_keys), f"research metadata leak: {sid}")
        require(set(item["explanations"]) == set(LABELS), f"four labels missing: {sid}")

        order = order_for(sid, "pilot")
        evidence_labels = []
        for label, system in zip(LABELS, order):
            actual = item["explanations"][label]
            expected = expected_entry(source[system], system)
            require(actual == expected, f"frozen explanation/evidence changed: {sid}/{label}")
            if actual.get("evidence") is not None:
                evidence_labels.append(label)
        require(len(evidence_labels) == 1, f"Task B mapping count is not one: {sid}")
        evidence = item["explanations"][evidence_labels[0]]["evidence"]
        require(len(evidence) <= 3, f"more than 3 Task-B claims: {sid}")
        evidence_counts.append(len(evidence))
        box_counts.append(sum(len(claim.get("evidence_boxes") or []) for claim in evidence))

        image_path = APP / item["image"]
        require(image_path.is_file(), f"missing image: {image_path}")
        with Image.open(image_path) as image:
            image.verify()
        with Image.open(image_path) as image:
            require(image.size == (item["image_native_width"], item["image_native_height"]),
                    f"native image dimensions changed: {sid}")

    require("details_blocks" not in re.sub(r"const hasHiddenDetails.*?;", "", app_js),
            "hidden details appear to be rendered")
    require("More details" not in app_js, "More details is present in runtime UI")
    require("localized evidence" not in app_js.lower(), "Task-A causal evidence language in UI")
    require("r.task_a_locked = true" in app_js and "task_a_locked: !!r.task_a_locked" in app_js,
            "Task-A lock is not persisted/exported")
    require("if (ex && ex.task_a_locked)" in app_js and "inc.task_a = JSON.parse" in app_js,
            "backup import can overwrite a local Task-A lock")
    require("const TIMING_MAX_SEGMENT_MS = 30 * 60 * 1000" in app_js,
            "30-minute timing cap missing")
    for field in ("card_ms", "task_a_ms", "task_b_ms", "total_ms", "segments",
                  "dropped_idle_ms", "dropped_idle_segments",
                  "task_a_first_started_at", "task_b_first_started_at"):
        require(field in app_js, f"timing field missing: {field}")
    require("visibilitychange" in app_js and "tab_hidden" in app_js,
            "hidden-tab timing pause missing")
    require("idbPut" in app_js and "idbAll" in app_js and "localStorage.setItem" in app_js,
            "save/resume storage paths missing")

    parser = VisibleText()
    parser.feed(index_html)
    visible = " ".join(parser.text).lower()
    for leaked in ("visexmem", "qwen", "viescore", "gpt", "expert", "agita", "groundingdino"):
        require(leaked not in visible, f"system identity leak in visible HTML: {leaked}")
    html_ids = set(re.findall(r'\bid="([^"]+)"', index_html))
    js_ids = set(re.findall(r"\$\('([^']+)'\)", app_js))
    require(not (js_ids - html_ids), f"JavaScript references missing HTML IDs: {js_ids - html_ids}")
    require("app.js?v=2.1.0" in index_html and "styles.css?v=2.1.0" in index_html,
            "static asset cache version is stale")

    css = (APP / "styles.css").read_text()
    require("max-width:1100px" in css and "position:sticky" in css,
            "desktop layout constraints missing")
    require("@media (max-width:980px)" in css, "responsive layout missing")

    ignored = subprocess.run(
        ["git", "check-ignore", "private/pilot_credentials.md", "private/blinding_map.json"],
        cwd=APP, text=True, capture_output=True, check=False,
    )
    require(ignored.returncode == 0 and len(ignored.stdout.splitlines()) == 2,
            "private credential/mapping files are not gitignored")

    print(json.dumps({
        "status": "PASS",
        "pilot_samples": len(actual_ids),
        "real_study_overlap": 0,
        "assignment_id_hash": payload["assignment_hash"],
        "task_a_labels_per_sample": 4,
        "task_b_claim_counts": evidence_counts,
        "task_b_box_counts": box_counts,
        "max_task_b_claims": max(evidence_counts),
        "checks": {
            "frozen_explanations_and_evidence": "PASS",
            "stable_blinding": "PASS",
            "task_a_lock_persistence": "PASS",
            "save_resume_export": "PASS",
            "timing_and_idle_exclusion": "PASS",
            "metadata_and_ui_blinding": "PASS",
            "html_javascript_wiring": "PASS",
            "images_and_dimensions": "PASS",
            "desktop_responsive_css": "PASS",
            "private_files_gitignored": "PASS",
        },
    }, indent=2))


if __name__ == "__main__":
    main()
