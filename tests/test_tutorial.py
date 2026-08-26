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
    "ex_1": "A man works on a red bicycle in a workshop with tools hanging on a "
            "green pegboard.",
    "ex_2": "A black dog lies on a patterned sofa beside several pillows, with a "
            "red ball near its front paws.",
    "ex_3": "A Shiba Inu wearing a red beret and a blue turtleneck sits in front "
            "of a green wooden wall.",
    "ex_4": "A woman in a red shirt is holding a blue umbrella beside a brown dog, "
            "while standing on a wet sidewalk in front of a yellow bus.",
}
EXPECTED_OVERALL = {"ex_1": 5, "ex_2": 3, "ex_3": 2, "ex_4": 4}
EXPECTED_LABEL = {"ex_1": "High alignment", "ex_2": "Partial alignment",
                  "ex_3": "Weak alignment", "ex_4": "Decomposition quality"}
# the frozen reference answers, transcribed independently of the builder
EXPECTED_PARTS = {
    "ex_1": [("object", "man", 4), ("object", "bicycle", 4),
             ("attribute", "red bicycle", 4), ("object", "workshop", 4),
             ("object", "tools", 4), ("object", "pegboard", 4),
             ("attribute", "green pegboard", 4),
             ("action", "man works on a red bicycle", 4),
             ("spatial", "man in a workshop", 4),
             ("relation", "tools hanging on a green pegboard", 4)],
    "ex_2": [("object", "dog", 4), ("attribute", "black dog", 0),
             ("object", "sofa", 4), ("attribute", "patterned sofa", 4),
             ("object", "pillows", 4), ("count", "several pillows", 4),
             ("object", "ball", 0), ("attribute", "red ball", 0),
             ("object", "front paws", "Cannot judge"),
             ("action", "dog lies on a patterned sofa", 4),
             ("spatial", "dog beside several pillows", 4),
             ("spatial", "red ball near the dog's front paws", 0)],
    "ex_3": [("object", "Shiba Inu", 4), ("object", "beret", 4),
             ("attribute", "red beret", 0), ("object", "turtleneck", 4),
             ("attribute", "blue turtleneck", 0), ("object", "wall", 4),
             ("attribute", "green wall", 0), ("attribute", "wooden wall", 0),
             ("relation", "Shiba Inu wearing a red beret", 2),
             ("relation", "Shiba Inu wearing a blue turtleneck", 2),
             ("action", "Shiba Inu sits", "Cannot judge"),
             ("spatial", "Shiba Inu in front of a wall", 4)],
    "ex_4": [("object", "woman", 4), ("attribute", "red shirt", 4),
             ("attribute", "blue umbrella", 4), ("attribute", "brown dog", 4),
             ("attribute", "wet sidewalk", 4), ("object", "bus", 4),
             ("attribute", "yellow bus", 0),
             ("relation", "woman holding a blue umbrella", 4),
             ("spatial", "woman beside a brown dog", 4),
             ("relation", "woman standing on a wet sidewalk", 4),
             ("spatial", "woman in front of a yellow bus", 2),
             ("relation", "woman in a red shirt holding a blue umbrella beside a "
              "brown dog", 4),
             ("action", "holding", 4), ("attribute", "shirt that is red", 4),
             ("action", "smiling woman", 4)],
}
# ex_4 exists to show the two judgements are independent, so its labels vary
EXPECTED_DECOMP = {
    "ex_4": ["Reasonable"] * 11 + ["Needs split", "Needs merge", "Redundant",
                                   "Not entailed"],
}
EXPECTED_ORIGIN = {"ex_1": "real", "ex_2": "real", "ex_3": "synthetic",
                   "ex_4": "real"}
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

    def test_exactly_four_examples_in_order(self):
        self.assertEqual([e["example_id"] for e in self.ex],
                         ["ex_1", "ex_2", "ex_3", "ex_4"])

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

    def test_every_example_has_an_overall_rationale(self):
        for e in self.ex:
            self.assertTrue(e["overall_note"].strip())

    def test_provenance_is_honest_about_who_annotated(self):
        """These are curated reference answers, not a live model's output. The app must
        not tell annotators a model produced them."""
        for e in self.ex:
            self.assertEqual(e["annotated_by"], "VisExMEM research team")
            self.assertIn("GPT-5.6-Sol", e["annotation_provenance"])

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

    def test_overall_scores_are_exactly_the_frozen_values(self):
        for e in self.ex:
            self.assertEqual(e["overall_alignment"], EXPECTED_OVERALL[e["example_id"]],
                             f"{e['example_id']} overall changed")

    def test_alignment_labels_are_the_frozen_ones(self):
        for e in self.ex:
            self.assertEqual(e["alignment_label"], EXPECTED_LABEL[e["example_id"]])

    def test_parts_are_exactly_the_frozen_reference_answers(self):
        for e in self.ex:
            got = [(p["type"], p["text"], p["support_score"]) for p in e["parts"]]
            self.assertEqual(got, EXPECTED_PARTS[e["example_id"]],
                             f"{e['example_id']} parts drifted from the frozen answers")

    def test_decomposition_labels_are_the_frozen_ones(self):
        for e in self.ex:
            got = [p["decomp_quality"] for p in e["parts"]]
            want = EXPECTED_DECOMP.get(e["example_id"], ["Reasonable"] * len(got))
            self.assertEqual(got, want,
                             f"{e['example_id']} decomposition labels changed")

    def test_ex_4_demonstrates_independent_judgements(self):
        """Its whole purpose: every decomposition label paired with a high support
        score, plus a Reasonable part the image contradicts."""
        e = next(x for x in self.ex if x["example_id"] == "ex_4")
        pairs = {(p["decomp_quality"], p["support_score"]) for p in e["parts"]}
        for lab in ("Needs split", "Needs merge", "Redundant", "Not entailed"):
            self.assertIn((lab, 4), pairs, f"ex_4 must pair {lab} with support 4")
        self.assertIn(("Reasonable", 0), pairs,
                      "ex_4 must pair Reasonable with support 0")

    def test_reasons_are_present_where_the_spec_gave_one(self):
        want = {("ex_4", "p7"), ("ex_4", "p11"), ("ex_4", "p12"),
                ("ex_4", "p13"), ("ex_4", "p14"), ("ex_4", "p15")}
        for e in self.ex:
            for p in e["parts"]:
                if (e["example_id"], p["part_id"]) in want:
                    self.assertTrue(p["support_note"].strip(),
                                    f"{e['example_id']}/{p['part_id']} lost its reason")

    def test_cannot_judge_parts_carry_their_explanation(self):
        cj = [(e["example_id"], p) for e in self.ex for p in e["parts"]
              if p["support_score"] == "Cannot judge"]
        self.assertEqual(len(cj), 2, "expected exactly two Cannot judge parts")
        for eid, p in cj:
            self.assertTrue(p["support_note"].strip(),
                            f"{eid}/{p['part_id']} needs its reason")

    def test_examples_are_marked_read_only(self):
        for e in self.ex:
            self.assertTrue(e["read_only"])

    def test_guideline_version_recorded(self):
        for e in self.ex:
            self.assertEqual(e["annotation_guideline_version"],
                             "visexmem-human-guideline-1.0")

    def test_display_names_are_human_facing(self):
        self.assertEqual([e["display_name"] for e in self.ex],
                         ["Example 1", "Example 2", "Example 3", "Example 4"])


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

    def test_login_lands_on_the_dashboard_not_the_examples(self):
        """Signing in must show the home dashboard. The worked examples are opt-in."""
        i = self.js.index("async function start(bundle)")
        j = self.js.index("function wire()", i)
        block = self.js[i:j]
        self.assertIn("renderDash()", block)
        self.assertNotIn("openTutorial(", block,
                         "sign-in must not open the worked examples automatically")

    def test_examples_are_reachable_only_on_demand(self):
        """Every openTutorial call must hang off an explicit user action."""
        for el in ("tutAgain", "menuTut", "guideTutLink"):
            self.assertIn(f"$('{el}')", self.js)
        self.assertIn("b.addEventListener('click', () => openTutorial(i));", self.js)

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


class TestWorkedExamplesUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(APP, "app.js")) as f:
            cls.js = f.read()
        with open(os.path.join(APP, "index.html")) as f:
            cls.html = f.read()
        with open(os.path.join(APP, "styles.css")) as f:
            cls.css = f.read()

    def test_dashboard_has_a_worked_examples_section(self):
        self.assertIn('id="workedHome"', self.html)
        self.assertIn("Worked examples", self.html)
        self.assertIn("Review these examples before starting the annotation task",
                      self.html)

    def test_three_cards_are_built_from_the_manifest(self):
        self.assertIn("function renderWorkedCards()", self.js)
        self.assertIn('id="whCards"', self.html)
        # cards must come from the data, never be hard-coded in markup
        self.assertNotIn("Example 1 —", self.html)
        self.assertIn("alignment_label", self.js)

    def test_cards_are_rendered_on_every_dashboard_paint(self):
        i = self.js.index("function renderDash()")
        self.assertIn("renderWorkedCards()", self.js[i:i + 400])

    def test_navigation_controls_exist(self):
        for el, label in (("tutPrev", "Previous example"),
                          ("tutNext", "Next example"),
                          ("tutExit", "Back to dashboard")):
            self.assertIn(f'id="{el}"', self.html)
            self.assertIn(label, self.html)
            self.assertIn(f"$('{el}')", self.js)

    def test_examples_are_presented_as_read_only(self):
        self.assertIn("cannot be changed", self.html)
        self.assertIn("reference answers", self.html.lower())
        # the fixed chips must be inert
        self.assertIn(".opt.tutfixed", self.css)
        self.assertIn("pointer-events:none", self.css)

    def test_tutorial_chips_are_never_clickable(self):
        i = self.js.index("function tutChip(")
        j = self.js.index("function renderTutorial(", i)
        self.assertNotIn("addEventListener", self.js[i:j],
                         "reference answers must not be interactive")

    def test_guide_links_to_the_worked_examples(self):
        self.assertIn("View worked examples", self.html)
        self.assertIn('id="guideTutLink"', self.html)

    def test_guide_keeps_the_two_required_clarifications(self):
        flat = " ".join(self.html.split())
        self.assertIn("Score the complete atomic statement, including attributes, "
                      "counts, bindings, roles, and relations.", flat)
        self.assertIn("A clearly missing or incorrect major object, count, action, "
                      "participant, or relation is a meaningful mismatch", flat)

    def test_guide_scales_are_unchanged(self):
        flat = " ".join(self.html.split())
        for lab in ("Reasonable", "Needs split", "Needs merge", "Redundant",
                    "Not entailed"):
            self.assertIn(lab, flat)
        for lab in ("Not aligned", "Weakly aligned", "Partially aligned",
                    "Well aligned", "Fully aligned"):
            self.assertIn(lab, flat)
        self.assertIn("Cannot judge", flat)


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
