"""Tutorial integration tests.

Two things must hold: the three worked examples are internally valid and independent of
the 600 benchmark samples, and the tutorial is *inert* -- it cannot touch a real
annotation record, the dashboard counts, or the export.
"""
from __future__ import annotations
import hashlib, json, os, re, sys, unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(APP))

TUT_JSON = os.path.join(APP, "examples", "tutorial_examples.json")
DECOMP = {"Reasonable", "Needs split", "Needs merge", "Redundant", "Not entailed"}
PART_TYPES = {"object", "attribute", "count", "action", "relation", "spatial",
              "negation", "text", "other"}


def load():
    with open(TUT_JSON) as f:
        return json.load(f)


EXPECTED_CAPTIONS = {
    "ex_1": "A man works on a red bicycle at a workbench in a workshop with tools "
            "hanging on a green pegboard.",
    "ex_2": "A brown dog lies on a patterned sofa beside several pillows, with a "
            "red ball near its front paws.",
    "ex_3": "A Shiba Inu wearing a red beret and a blue turtleneck sits in front "
            "of a gray brick wall.",
}
EXPECTED_ORIGIN = {"ex_1": "real", "ex_2": "real", "ex_3": "synthetic"}
# a phrase-level unit is not a proposition
SENTENCE_STYLE = [
    re.compile(r"^\s*there\s+(is|are)\b", re.I),
    re.compile(r"^\s*(the|a|an)\b.*\b(is|are|has|have)\b.*\.\s*$", re.I),
    re.compile(r"\.\s*$"),
]


class TestExamples(unittest.TestCase):
    def setUp(self):
        self.j = load()
        self.ex = self.j["examples"]

    def test_exactly_three_examples_in_order(self):
        self.assertEqual([e["example_id"] for e in self.ex], ["ex_1", "ex_2", "ex_3"])

    def test_captions_are_verbatim_from_the_specification(self):
        for e in self.ex:
            self.assertEqual(" ".join(e["text"].split()),
                             " ".join(EXPECTED_CAPTIONS[e["example_id"]].split()),
                             f"{e['example_id']} caption was altered")

    def test_image_origin_matches_the_specification(self):
        for e in self.ex:
            self.assertEqual(e["image_origin"], EXPECTED_ORIGIN[e["example_id"]])

    def test_overall_scores_are_in_range(self):
        for e in self.ex:
            self.assertIn(e["overall_alignment"], range(1, 6),
                          f"{e['example_id']} overall out of 1-5")

    def test_every_part_is_fully_annotated(self):
        for e in self.ex:
            self.assertTrue(e["parts"], f"{e['example_id']} has no parts")
            for p in e["parts"]:
                self.assertIn(p["type"], PART_TYPES)
                self.assertTrue(p["text"].strip())
                self.assertIn(p["decomp_quality"], DECOMP)
                s = p["support_score"]
                self.assertTrue(s == "Cannot judge" or s in range(0, 5),
                                f"{e['example_id']}/{p['part_id']}: bad support {s!r}")

    def test_part_ids_unique_and_sequential(self):
        for e in self.ex:
            self.assertEqual([p["part_id"] for p in e["parts"]],
                             [f"p{i+1}" for i in range(len(e["parts"]))])

    def test_parts_are_phrase_level_not_propositions(self):
        for e in self.ex:
            for p in e["parts"]:
                for rx in SENTENCE_STYLE:
                    self.assertIsNone(rx.search(p["text"]),
                                      f"{e['example_id']}/{p['part_id']} is "
                                      f"proposition-style: {p['text']!r}")

    def test_decomposition_covers_the_caption_vocabulary(self):
        """Every content word of the caption should surface in some atomic part."""
        stop = {"a", "an", "the", "of", "on", "in", "at", "with", "and", "its", "front",
                "near", "beside", "several", "to", "from", "that"}
        for e in self.ex:
            words = {w.strip(".,").lower() for w in e["text"].split()} - stop
            covered = " ".join(p["text"].lower() for p in e["parts"])
            missing = [w for w in words if w and w not in covered]
            self.assertEqual(missing, [],
                             f"{e['example_id']}: caption words absent from the "
                             f"decomposition: {missing}")

    def test_every_judgement_carries_a_reason(self):
        for e in self.ex:
            for p in e["parts"]:
                self.assertTrue(p["support_note"].strip(),
                                f"{e['example_id']}/{p['part_id']} support_note empty")
            self.assertTrue(e["overall_note"].strip())

    def test_judgement_separation_is_recorded(self):
        for e in self.ex:
            self.assertFalse(e["decomp_quality_call_saw_image"],
                             "decomposition quality must be judged without the image")
            self.assertTrue(e["image_support_call_saw_image"])

    def test_images_exist_and_match_their_hash(self):
        for e in self.ex:
            path = os.path.join(APP, e["image"])
            self.assertTrue(os.path.exists(path), path)
            with open(path, "rb") as f:
                got = hashlib.sha256(f.read()).hexdigest()
            self.assertEqual(got, e["image_sha256"], f"{e['example_id']} image changed")

    def test_images_are_decodable(self):
        from PIL import Image
        for e in self.ex:
            with Image.open(os.path.join(APP, e["image"])) as im:
                im.verify()

    def test_model_identifier_is_the_project_one(self):
        for e in self.ex:
            self.assertEqual(e["annotated_by"], "GPT-5.6-Sol")
            self.assertEqual(e["annotation_model"], "openai/gpt-5.6-sol")
            self.assertEqual(e["annotation_guideline_version"],
                             "visexmem-human-guideline-1.0")

    def test_display_names_are_human_facing(self):
        self.assertEqual([e["display_name"] for e in self.ex],
                         ["Example 1", "Example 2", "Example 3"])


class TestIndependenceFromBenchmark(unittest.TestCase):
    """A tutorial example must never be one of the 600 samples people are annotating."""

    @classmethod
    def setUpClass(cls):
        cls.sha, cls.txt = None, None
        try:
            import pyarrow.parquet as pq
            from benchmark.common.config import FROZEN
        except Exception:
            return
        sha, txt = set(), set()
        for mf, tcol in (("image_to_text_manifest.parquet", "caption"),
                         ("text_to_image_manifest.parquet", "evaluation_text")):
            path = os.path.join(FROZEN, mf)
            if not os.path.exists(path):
                return
            for r in pq.read_table(path).to_pylist():
                sha.add(r["image_sha256"])
                txt.add(" ".join(str(r.get(tcol, "")).lower().split()))
        cls.sha, cls.txt = sha, txt

    def test_no_shared_image_or_text(self):
        if self.sha is None:
            self.skipTest("frozen benchmark manifests not reachable from this checkout")
        self.assertEqual(len(self.sha), 600, "expected the frozen 600")
        for e in load()["examples"]:
            self.assertNotIn(e["image_sha256"], self.sha,
                             f"{e['example_id']} reuses a benchmark image")
            norm = " ".join(e["text"].lower().split())
            self.assertNotIn(norm, self.txt,
                             f"{e['example_id']} reuses a benchmark text")

    def test_no_near_duplicate_text_with_benchmark(self):
        if self.txt is None:
            self.skipTest("frozen benchmark manifests not reachable from this checkout")
        for e in load()["examples"]:
            toks = set(" ".join(e["text"].lower().split()).split())
            for t in self.txt:
                o = set(t.split())
                if toks and o:
                    self.assertLess(len(toks & o) / len(toks | o), 0.8,
                                    f"{e['example_id']} text near-duplicates a benchmark text")

    def test_tutorial_images_are_distinct_from_each_other(self):
        ex = load()["examples"]
        self.assertEqual(len({e["image_sha256"] for e in ex}), len(ex))


class TestAppIsolation(unittest.TestCase):
    """The tutorial must not leak into stored annotations, counts, or the export."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(APP, "app.js")) as f:
            cls.js = f.read()
        with open(os.path.join(APP, "index.html")) as f:
            cls.html = f.read()

    def tut_block(self):
        i = self.js.index("let TUT = ")
        j = self.js.index("/* ---------------- actions ---------------- */", i)
        return self.js[i:j]

    def test_tutorial_never_persists(self):
        blk = self.tut_block()
        for forbidden in ("persist(", "idbPut(", "S.ann", "completeSample(", "rec()"):
            self.assertNotIn(forbidden, blk,
                             f"tutorial code must not call {forbidden}")

    def test_export_ignores_the_tutorial(self):
        i = self.js.index("function buildExport()")
        j = self.js.index("function download(", i)
        self.assertNotIn("TUT", self.js[i:j])
        self.assertNotIn("tutorial", self.js[i:j].lower())

    def test_counts_ignore_the_tutorial(self):
        i = self.js.index("function counts()")
        j = self.js.index("const LABEL", i)
        self.assertNotIn("TUT", self.js[i:j])

    def test_tutorial_is_reachable_three_ways(self):
        for el in ("tutAgain", "menuTut", "guideTutLink"):
            self.assertIn(f'id="{el}"', self.html, f"missing entry point #{el}")
            self.assertIn(f"$('{el}')", self.js, f"#{el} is not wired up")

    def test_tutorial_shown_once_on_first_login(self):
        self.assertIn("tutSeenKey()", self.js)
        i = self.js.index("async function start(bundle)")
        j = self.js.index("function wire()", i)
        self.assertIn("openTutorial(0)", self.js[i:j],
                      "first login should open the worked examples")

    def test_dashboard_hides_the_tutorial_view(self):
        i = self.js.index("function renderDash()")
        self.assertIn("$('tutorial').classList.add('hidden')", self.js[i:i + 400])

    def test_guide_covers_sections_a_to_g(self):
        for letter in "ABCDEFG":
            self.assertRegex(self.html, rf"<h4>{letter} ·",
                             f"guide section {letter} missing")

    def test_guide_states_the_extra_object_rule(self):
        self.assertRegex(
            re.sub(r"\s+", " ", self.html),
            r"Extra objects or details that the text does not mention should not "
            r"automatically reduce the score",
            "the guide must say extra unmentioned content does not lower the score")


class TestProgressAndAssignmentsUntouched(unittest.TestCase):
    """Viewing the tutorial must leave every annotator at 0/N and every assignment
    byte-identical to the frozen lock."""

    # pinned from ASSIGNMENT_LOCK.json at the time the tutorial was added
    EXPECTED_TOTALS = {"damir": 173, "brisca": 173, "omar": 172, "sayeeda": 172,
                       "christian": 30, "chris": 30, "zhipin": 30, "joy": 30}
    EXPECTED_HASHES = {
        "damir": "99a1880240d065f313bca3ba5a23ec51c9c7f0bb17b69a0adf04d74565b4b17d",
        "brisca": "57d0eb9331eea5fbafcc543bbf3d4bd563266808ab66a4cb4dc4f2dc846a891c",
        "omar": "dcaaa1f21200b6d26e9d370e8a41a4993d8155f9f2b65acb242f0472511ebb24",
        "sayeeda": "bd6a4363256bac8bb1d1ccd78a43e4be12009212f1d947c36f25b46d9ab10b6d",
        "christian": "8ac5e903913b811feb74d3178aabd0d39e5f1be1ebb39a4ce6905f97089ceabe",
        "chris": "9db7baa38e7954d31f12e861cd8681b74a6bc68a081b1574d4696e53bf8309cf",
        "zhipin": "8ac94737c09681f375f514771809531a10cfa08c6658350ec165eab424a4a546",
        "joy": "49565854dc2a69ab9786362b6fc53736f5851cd77d6481d6893752468903b521",
    }

    def setUp(self):
        with open(os.path.join(APP, "ASSIGNMENT_LOCK.json")) as f:
            self.lock = json.load(f)

    def test_assignment_totals_unchanged(self):
        got = {k: v["total"] for k, v in self.lock["counts"].items()}
        self.assertEqual(got, self.EXPECTED_TOTALS)

    def test_assignment_hashes_unchanged(self):
        self.assertEqual(self.lock["assignment_hashes"], self.EXPECTED_HASHES,
                         "an assignment changed -- the tutorial must not touch these")

    def test_tutorial_ids_cannot_collide_with_sample_ids(self):
        for e in load()["examples"]:
            self.assertFalse(e["example_id"].startswith("vxb_"),
                             "tutorial ids live in their own namespace")

    def test_bundles_do_not_carry_tutorial_content(self):
        d = os.path.join(APP, "data")
        for fn in sorted(os.listdir(d)):
            if not fn.startswith("bundle_"):
                continue
            with open(os.path.join(d, fn)) as f:
                blob = f.read()
            for marker in ("ex_1", "ex_2", "ex_3", "tutorial", "Shiba"):
                self.assertNotIn(marker, blob, f"{fn} leaks tutorial content")

    def test_export_record_shape_has_no_tutorial_field(self):
        with open(os.path.join(APP, "app.js")) as f:
            js = f.read()
        i = js.index("function buildExport()")
        j = js.index("function download(", i)
        block = js[i:j]
        for marker in ("TUT", "tutorial", "example_id"):
            self.assertNotIn(marker, block,
                             f"export must not carry {marker}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
