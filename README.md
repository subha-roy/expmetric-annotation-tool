# VisExMEM Human Annotation

A static annotation site (no server, no database, no tracking). Each annotator signs in
with a username and a disposable access code, which decrypts only their own assignment
bundle in the browser.

## For annotators

1. Open the URL you were sent and sign in with **your own** username and access code.
2. Work through your samples. Each sample has three steps, in order:
   - **Step 1 — Decomposition (text only).** Judge whether each statement is a
     reasonable decomposition of the text. The image is deliberately hidden.
   - **Step 2 — Statement support.** The image appears on the left and stays in place
     while you scroll the statements on the right. Rate how strongly the image supports
     each statement (0–4), or *Cannot judge*.
   - **Step 3 — Overall alignment.** After every statement is rated, one overall 1–7
     judgement of how well the complete image and text match appears at the bottom.
3. Your answers **save automatically in your browser**. You can close the tab and come
   back to the same place.
4. Please use the **same browser and the same device** throughout, and do not clear site
   data for this site until you have exported your final file.
5. You can press **Download backup** at any time for a safety copy.
6. When everything is finished, press **Export final annotations** and email the JSON
   file back.

*Cannot judge* means the image genuinely does not let you decide — it is not a way to
skip a hard item. If something is technically broken (image will not load, text is
garbled, duplicate), use **Report a technical issue** instead.

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
