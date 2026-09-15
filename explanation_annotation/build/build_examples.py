"""Public practice-example file (unencrypted, like the original app's
examples/tutorial_examples.json) -- 5 samples EXCLUDED from the 120-sample manifest and
from every annotator's real assignment, each system still blinded to A/B/C/D (fixed,
single practice ordering, not tied to any real annotator) with a walkthrough note.
"""
import json, hashlib, random
from pathlib import Path
from task_a_presentation import presentation_fields

MANIFEST_DIR = Path("/home/hpc/v141be/v141be14/projects/proj2_exp_metric/evaluation/explanation_annotation/manifests")
APP = Path(__file__).resolve().parents[1]
SEED = 20260915
SYSTEMS = ["visexmem_9b", "gpt_decomposed", "expert", "viescore_official"]
LABELS = ["A", "B", "C", "D"]
# PRIMARY evidence system only -- see build_bundles.py for why GPT's boxes are excluded.
EVIDENCE_SYSTEMS = {"visexmem_9b"}


def order_for(sample_id):
    h = hashlib.sha256(f"{SEED}:practice:{sample_id}".encode()).hexdigest()
    rng = random.Random(int(h[:16], 16))
    order = list(SYSTEMS)
    rng.shuffle(order)
    return order


pool = json.loads((MANIFEST_DIR / "tutorial_pool_5.json").read_text())
examples = []
for i, sid in enumerate(pool["sample_ids"]):
    s = pool["samples"][sid]
    order = order_for(sid)
    explanations = {}
    for j, lab in enumerate(LABELS):
        sysname = order[j]
        sysrec = s[sysname]
        entry = (presentation_fields(sysrec) if sysname == "visexmem_9b" else
                 {"summary": sysrec.get("task_a_summary"),
                  "blocks": sysrec.get("task_a_blocks") or [],
                  "details_blocks": sysrec.get("task_a_details_blocks") or [],
                  "text": sysrec["task_a_text"],
                  "word_count": sysrec.get("word_count")})
        if sysname in EVIDENCE_SYSTEMS:
            entry["evidence"] = sysrec["task_b_evidence"]
            entry["box_coord_system"] = sysrec.get("box_coord_system", "native_pixels_xyxy")
        explanations[lab] = entry
    examples.append({
        "example_id": f"prac_{i+1}", "display_name": s["display_name"],
        "image": f"images/{Path(s['image_path']).name}",
        "text": s["text"],
        "walkthrough_note": s["walkthrough_note"],
        "explanations": explanations,
    })

out = {"schema": "explanation-annotation-practice-1.0.0", "note":
      "5 worked practice examples, excluded from the real 120-sample study and from "
      "every annotator's assignment. Not counted toward completion.",
      "examples": examples}
outpath = APP / "examples" / "tutorial_examples.json"
outpath.write_text(json.dumps(out, indent=2))
print(f"Wrote {outpath}: {len(examples)} practice examples")
