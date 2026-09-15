"""Public practice-example file (unencrypted, like the original app's
examples/tutorial_examples.json) -- FINAL 3 practice examples, EXCLUDED from the real
manifest and from every annotator's real assignment.

FINAL practice-tutorial version: exactly 3 examples, each showing GPT-5.6 Sol Decomposed
(always "Explanation A") next to ONE second explanation -- EXPERT or VIEScore-official
("Explanation B") -- plus Task-A ratings/rationales, a one-line "final_comparison"
teaching takeaway, and (where available) one GPT-5.6-Sol-Decomposed Task-B evidence-box
example with real ratings/rationale. Everything is copied verbatim from
evaluation/explanation_annotation/manifests/practice_ratings_3.json: Task-A
ratings/rationale + final_comparison are the researcher's final reviewed values
(finalize_practice_ratings.py), superseding the original live GPT-5.6-sol Task-A output
that is still kept in provenance.raw_responses for audit; Task-B ratings are unchanged,
still the original live API output (generate_practice_ratings.py). These are TUTORIAL
labels, never gold/reference annotations, never merged into real study data.

BASELINE STUDY (current): VisExMEM-9B is excluded, same as the real-HiWi bundles -- see
build_bundles.py's docstring for the full rationale.
"""
import json
from pathlib import Path

MANIFEST_DIR = Path("/home/hpc/v141be/v141be14/projects/proj2_exp_metric/evaluation/explanation_annotation/manifests")
APP = Path(__file__).resolve().parents[1]
EVIDENCE_SOURCE_LABEL = "GPT self-reported visual evidence"

# Short, human-authored teaching notes (NOT annotation labels -- those come from the real
# GPT-5.6-sol API output in practice_ratings_3.json). Order matches the categories chosen
# in generate_practice_ratings.py: good / mixed / clearly problematic.
WALKTHROUGH_NOTES = {
    "vxb_i2t_73d60934fb0f3c50":
        "Both explanations here are well grounded and confident -- notice how similar "
        "high ratings look across two very differently WRITTEN explanations. Judge the "
        "content against the image, not the writing style.",
    "VXM_T2I_000111":
        "Explanation A stays cautious about what's actually visible, while Explanation B "
        "confidently asserts specific details (a resolution, a platform, an artist "
        "attribution) that the image alone cannot support -- watch how that drops its "
        "ratings and flags Unsupported Content.",
    "vxb_i2t_2b0bf329407964ce":
        "Explanation B invents a specific visual detail (a watermark) that is not in the "
        "image at all. Compare that to the Task-B example below, where the highlighted "
        "boxes visibly show fewer panels than the claim states -- a good box location can "
        "still be an insufficient one.",
}


def build_task_a_entry(sysrec, ratings):
    return {"blocks": sysrec.get("task_a_blocks") or [],
            "text": sysrec.get("task_a_text"),
            "word_count": sysrec.get("word_count"),
            "ratings": ratings}


def main():
    pool = json.loads((MANIFEST_DIR / "tutorial_pool_5.json").read_text())["samples"]
    ratings_doc = json.loads((MANIFEST_DIR / "practice_ratings_3.json").read_text())
    generated = ratings_doc["examples"]

    examples = []
    for i, (sid, gen) in enumerate(generated.items()):
        s = pool[sid]
        second_sys = gen["second_system"]
        explanations = {
            "A": build_task_a_entry(s["gpt_decomposed"], gen["task_a"]["gpt_decomposed"]),
            "B": build_task_a_entry(s[second_sys], gen["task_a"][second_sys]),
        }
        tb = gen["task_b"]
        examples.append({
            "example_id": f"prac_{i + 1}",
            "display_name": s["display_name"],
            "image": f"images/{Path(s['image_path']).name}",
            "image_native_width": s.get("image_native_width"),
            "image_native_height": s.get("image_native_height"),
            "text": s["text"],
            "walkthrough_note": WALKTHROUGH_NOTES[sid],
            "explanations": explanations,
            "final_comparison": gen.get("final_comparison"),
            "task_b": {
                "label": "A",
                "evidence_source": EVIDENCE_SOURCE_LABEL,
                "claim_text": tb["claim_text"],
                "evidence_boxes": tb["evidence_boxes"],
                "box_coord_system": s["gpt_decomposed"].get("box_coord_system"),
                "ratings": tb["ratings"],
            },
        })

    out = {"schema": "explanation-annotation-practice-2.0.0",
          "note": "3 worked practice examples, excluded from the real 170-sample study "
                  "and from every annotator's assignment. Not counted toward completion. "
                  "Task-A ratings/rationale and the final_comparison line are the "
                  "researcher's final reviewed values; Task-B ratings are the original "
                  "live GPT-5.6-sol API output. Teaching material only -- NOT "
                  "gold/reference annotations.",
          "model_id": ratings_doc["model_id"],
          "examples": examples}
    outpath = APP / "examples" / "tutorial_examples.json"
    outpath.write_text(json.dumps(out, indent=2))
    print(f"Wrote {outpath}: {len(examples)} practice examples")


if __name__ == "__main__":
    main()
