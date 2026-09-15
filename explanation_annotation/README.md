# VisExMEM Explanation Quality Annotation

> **Current configuration: BASELINE STUDY.** VisExMEM-9B is deliberately excluded from
> Task A and Task B — it is not being evaluated yet. Only three blinded systems are
> live: GPT-5.6 Sol Decomposed, EXPERT, and VIEScore-official. Task B now rates GPT's own
> self-reported evidence boxes (internally labeled "GPT self-reported visual evidence" —
> never "causal evidence", never equated with VisExMEM's GroundingDINO-based grounding).
> VisExMEM's source files and its original four-system build logic are left untouched for
> a later, separate study; see git history for the four-system version of every file under
> `build/`.

A static annotation site (no server, no database, no tracking), same architecture as the
original `app/` AGITA annotation tool: each annotator signs in with a username and a
disposable access code, which decrypts only their own assignment bundle in the browser.

## Accounts and their role in the study — READ BEFORE ANALYZING RESULTS

| Account | Role | In the real study's statistics / IAA? |
|---|---|---|
| `damir`, `brisca`, `omar`, `sayeeda` | the 4 HiWis | **Yes — these four ONLY.** |
| `annotator` | test / pilot / backup account | **No — never.** |
| `pilot` | timed workload pilot (10 samples, separate from the 120) | **No — never.** Used solely to measure per-sample annotation time before the final per-annotator sample count is chosen. |

Each real HiWi has 100 samples: the same 30 common samples plus 70 samples from the
pairwise assignment. The final study contains 170 unique samples. The real
inter-annotator-agreement (IAA) set and the final published statistics are
computed from **damir, brisca, omar, sayeeda only**. `annotator` exists purely as a
spare/demo/backup login and its labels — even if it happens to complete real samples —
must never be merged into the final dataset or counted toward IAA. Any future
`merge_annotations.py`-equivalent script must hard-filter to these 4 usernames before
computing anything, not merely default to "all files found in `annotations/`".

## Blinding

Every sample shows the 3 explanation systems (baseline: GPT-5.6 Sol Decomposed, EXPERT,
VIEScore-official) as Explanation A/B/C in an order that is independently and
deterministically randomized per (sample, annotator) pair. The label→system key is never
written to any file the browser can reach — see `private/blinding_map.json` (gitignored).

Once Task B (GPT's own self-reported evidence regions — not VisExMEM's) is revealed for a
sample, that sample's Task A answers become **permanently locked** (not editable,
including via "Edit / redo annotation") — this prevents seeing the evidence boxes from
retroactively changing the already-recorded Task-A judgments.

## Frozen artifacts — do not edit without an explicit, disclosed, versioned change

- Task A/B question wording and 1–5 anchors: frozen in `app.js` (`TASKA_QS`, `TASKB_QS`,
  `UNSUPPORTED_Q`). `CONTENT_VERSION` must be bumped on any wording change.
- The deterministic VisExMEM explanation generator's thresholds: see
  `evaluation/explanation_annotation/manifests/VISEXMEM_EXPLANATION_RULES_FROZEN.md`.
  VisExMEM Task A includes a deterministic sample summary and quoted per-claim blocks;
  neither exposes raw support scores or box coordinates. Only representative claims are
  rendered; omitted frozen atomic claims remain in the payload for provenance/debugging.
- The final 170-sample manifest (`evaluation/explanation_annotation/manifests/sample_manifest_170.json`).
- The final four-HiWi assignment (`evaluation/explanation_annotation/manifests/annotator_assignment_170.json`).

## For the researcher

```
build/build_blinding.py        # per-(sample,annotator) label->system permutation (private)
build/build_examples.py        # public practice-example file
build/build_bundles.py         # final 100-sample bundles for the four real HiWIs + annotator
build/build_pilot_bundle.py    # separate, independent 10-sample TIMED PILOT bundle
```

`evaluation/explanation_annotation/scripts/` holds the upstream generation pipeline
(coverage audit, manifest/assignment builders, the frozen explanation generator).

`private/` (credentials, blinding map) is gitignored and must never be published.
Access codes are disposable values generated for this task, not anyone's real password.
