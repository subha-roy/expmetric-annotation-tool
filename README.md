# VisExMEM Human Annotation

A static annotation site (no server, no database, no tracking). Each annotator signs in
with a username and a disposable access code, which decrypts only their own assignment
bundle in the browser.

## For annotators

1. Open the URL and sign in with **your own** username and passcode.
2. You land on your **dashboard**: every sample in your assignment as a numbered tile.
   Green = completed, amber = in progress, red = skipped, purple = technical issue,
   grey = not started. Press **Continue annotation** to pick up where you left off, or
   click any number to jump straight to it.
3. In a sample: the **image is on the left and stays put** while you scroll the
   statements on the right. For every statement give **two** judgements: whether it is a good
   decomposition of the text, and how strongly the image supports it (0–4 or
   *Cannot judge*). The overall **1–5** alignment question appears at the bottom once
   every statement is rated. Then press **Save & complete**.
4. **Skip for now** postpones a sample — it stays in your assignment and turns red on the
   dashboard until you finish it.
5. A completed sample can be reopened and revised; press **Edit / redo annotation**.
6. Your work **saves automatically in your browser**. Use the same browser and device,
   and do not clear site data before exporting.
7. Press **Download backup** any time for a safety copy. When everything is finished,
   press **Export final annotations** and email the JSON back.

*Cannot judge* = the image genuinely does not let you decide. *Skip for now* = postpone.
*Report a technical issue* = something is broken. Three different things.

## For the researcher

```
build/build_assignments.py   # deterministic assignment -> ASSIGNMENT_LOCK.json + private/
build/build_bundles.py       # encrypted per-annotator bundles + private/credentials.md
build/assignment_stats.py    # private balance/statistics summary
build/merge_annotations.py   # ingest + validate + merge returned JSON files
tests/test_assignments.py    # 97 integrity tests
```

`private/` (credentials, sample-level audit, image manifest) and `images_bench/` are
gitignored and must never be published.

Access codes are disposable values generated for this task. They are not anyone's real
password, and only their PBKDF2/AES-GCM-encrypted bundles are ever published.
