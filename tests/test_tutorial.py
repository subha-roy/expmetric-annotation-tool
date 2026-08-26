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


class TestExamples(unittest.TestCase):
    def setUp(self):
        self.j = load()
        self.ex = self.j["examples"]

    def test_exactly_three_examples_in_order(self):
        self.assertEqual([e["example_id"] for e in self.ex], ["ex_1", "ex_2", "ex_3"])

    def test_one_of_each_alignment_category(self):
        self.assertEqual([e["intended_alignment"] for e in self.ex],
                         ["high", "partial", "low"])

    def test_overall_scores_are_ordered_and_in_range(self):
        ov = [e["overall_alignment"] for e in self.ex]
        for v in ov:
            self.assertIn(v, range(1, 6))
        self.assertGreater(ov[0], ov[1], "the good example must outscore the medium one")
        self.assertGreater(ov[1], ov[2], "the medium example must outscore the bad one")

    def test_overall_lands_in_its_intended_band(self):
        band = {"high": (5, 5), "partial": (3, 3), "low": (1, 2)}
        for e in self.ex:
            lo, hi = band[e["intended_alignment"]]
            self.assertTrue(lo <= e["overall_alignment"] <= hi,
                            f"{e['example_id']}: overall={e['overall_alignment']} "
                            f"outside {lo}-{hi} for '{e['intended_alignment']}'")

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

    def test_part_count_is_teachable(self):
        for e in self.ex:
            self.assertTrue(3 <= len(e["parts"]) <= 14,
                            f"{e['example_id']}: {len(e['parts'])} parts is too many "
                            "for a first lesson")

    def test_every_judgement_carries_a_reason(self):
        for e in self.ex:
            for p in e["parts"]:
                self.assertTrue(p["decomp_note"].strip(),
                                f"{e['example_id']}/{p['part_id']} decomp_note empty")
                self.assertTrue(p["support_note"].strip(),
                                f"{e['example_id']}/{p['part_id']} support_note empty")
            self.assertTrue(e["overall_note"].strip())

    def test_bad_example_actually_shows_unsupported_content(self):
        bad = self.ex[2]
        zeros = [p for p in bad["parts"]
                 if p["support_score"] != "Cannot judge" and p["support_score"] <= 1]
        self.assertTrue(zeros, "the poorly-aligned example must contain statements the "
                               "image does not support")

    def test_good_example_is_mostly_supported(self):
        good = self.ex[0]
        strong = [p for p in good["parts"]
                  if p["support_score"] != "Cannot judge" and p["support_score"] >= 3]
        self.assertGreaterEqual(len(strong), 0.8 * len(good["parts"]))

    def test_judgement_separation_is_recorded(self):
        for e in self.ex:
            self.assertFalse(e["decomp_quality_call_saw_image"],
                             "decomposition quality must be judged without the image")
            self.assertTrue(e["image_support_call_saw_image"])

    def test_images_exist_and_match_their_hash(self):
        for e in self.ex:
            path = os.path.join(APP, e["image"])
            self.assertTrue(os.path.exists(path), path)
            got = hashlib.sha256(open(path, "rb").read()).hexdigest()
            self.assertEqual(got, e["image_sha256"], f"{e['example_id']} image changed")

    def test_provenance_is_recorded(self):
        for e in self.ex:
            self.assertIn(e["image_origin"], {"real", "synthetic"})
            self.assertTrue(e["image_source"].strip())
            self.assertEqual(e["annotated_by"], "GPT-5.6-Sol")


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
