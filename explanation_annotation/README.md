# VisExMEM Explanation Quality Annotation

A static annotation site (no server, no database, no tracking), same architecture as the
original `app/` AGITA annotation tool: each annotator signs in with a username and a
disposable access code, which decrypts only their own assignment bundle in the browser.

## Accounts and their role in the study — READ BEFORE ANALYZING RESULTS

| Account | Role | In the real study's statistics / IAA? |
|---|---|---|
| `damir`, `brisca`, `omar`, `sayeeda` | the 4 HiWis | **Yes — these four ONLY.** |
| `annotator` | test / pilot / backup account | **No — never.** |
| `pilot` | timed workload pilot (10 samples, separate from the 120) | **No — never.** Used solely to measure per-sample annotation time before the final per-annotator sample count is chosen. |

The real inter-annotator-agreement (IAA) set and the final published statistics are
computed from **damir, brisca, omar, sayeeda only**. `annotator` exists purely as a
spare/demo/backup login and its labels — even if it happens to complete real samples —
must never be merged into the final dataset or counted toward IAA. Any future
`merge_annotations.py`-equivalent script must hard-filter to these 4 usernames before
computing anything, not merely default to "all files found in `annotations/`".

## Blinding

Every sample shows the 4 explanation systems as Explanation A/B/C/D in an order that is
independently re-randomized per (sample, annotator) pair — verified empirically: across
all 330 (account, sample) pairs in the candidate assignment, all 24 possible orderings of
the 4 systems occur (counts 7–23, uniform expectation 13.75), and of the 30 samples common
to every account, **zero** show the same ordering across all 5 accounts. The label→system
key is never written to any file the browser can reach — see
`private/blinding_map.json` (gitignored).

Once Task B (VisExMEM's evidence regions) is revealed for a sample, that sample's Task A
answers become **permanently locked** (not editable, including via "Edit / redo
annotation") — this prevents seeing the evidence boxes from retroactively changing the
already-recorded Task-A judgments.

## Frozen artifacts — do not edit without an explicit, disclosed, versioned change

- Task A/B question wording and 1–5 anchors: frozen in `app.js` (`TASKA_QS`, `TASKB_QS`,
  `UNSUPPORTED_Q`). `CONTENT_VERSION` must be bumped on any wording change.
- The deterministic VisExMEM explanation generator's thresholds: see
  `evaluation/explanation_annotation/manifests/VISEXMEM_EXPLANATION_RULES_FROZEN.md`.
- The 120-sample manifest (`evaluation/explanation_annotation/manifests/sample_manifest_120.json`).

## For the researcher

```
build/build_blinding.py        # per-(sample,annotator) label->system permutation (private)
build/build_examples.py        # public practice-example file
build/build_bundles.py         # candidate 75-sample/annotator bundles -- NOT YET FROZEN,
                                # do not distribute credentials until a final per-annotator
                                # sample count is chosen (see the pilot below)
build/build_pilot_bundle.py    # separate, independent 10-sample TIMED PILOT bundle
```

`evaluation/explanation_annotation/scripts/` holds the upstream generation pipeline
(coverage audit, manifest/assignment builders, the frozen explanation generator).

`private/` (credentials, blinding map) is gitignored and must never be published.
Access codes are disposable values generated for this task, not anyone's real password.
