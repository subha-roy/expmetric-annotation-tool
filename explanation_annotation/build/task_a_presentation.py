"""Final Task-A-only VisExMEM wording normalization.

The frozen explanation manifests are intentionally not rewritten. This layer removes
claims about localized evidence before records are shipped to the annotation app; Task B
remains the independent evidence-quality task.
"""
from __future__ import annotations

import copy
import re


_RULES = (
    (re.compile(r"^The localized evidence strongly supports this (.+)\.$"),
     r"This \1 receives strong visual support."),
    (re.compile(r"^The localized evidence provides partial support for this (.+)\.$"),
     r"This \1 receives partial visual support."),
    (re.compile(r"^This (.+) receives weak visual support from the localized evidence\.$"),
     r"This \1 receives weak visual support."),
    (re.compile(r"^The localized evidence does not provide a reliable judgment for this (.+)\.$"),
     r"This \1 does not receive a reliable visual-support judgment."),
)


def neutralize_block(block):
    result = copy.deepcopy(block)
    text = result.get("text") or ""
    for pattern, replacement in _RULES:
        updated, count = pattern.subn(replacement, text)
        if count:
            result["text"] = updated
            break
    if "localized evidence" in (result.get("text") or "").lower():
        raise RuntimeError(f"unhandled Task-A localized-evidence wording: {text!r}")
    return result


def presentation_fields(record):
    summary = record.get("task_a_summary")
    blocks = [neutralize_block(b) for b in record.get("task_a_blocks") or []]
    details = [neutralize_block(b) for b in record.get("task_a_details_blocks") or []]
    segments = [summary]
    segments.extend(f"{b['claim']} {b['text']}" for b in blocks + details)
    text = " ".join(segment for segment in segments if segment)
    word_count = sum(len(segment.split()) for segment in segments if segment)
    return {"summary": summary, "blocks": blocks, "details_blocks": details,
            "text": text, "word_count": word_count}
