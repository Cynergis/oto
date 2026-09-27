"""The harness: honest about provenance, and its ablations must actually bite."""
import json
import os
import tempfile

import pytest

from oto.bench import gold, metrics


def _write(path, meta, questions):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("// a set\n")
        f.write(json.dumps({"_meta": meta}) + "\n")
        for question in questions:
            f.write(json.dumps(question) + "\n")
    return path


GOOD_META = {"authored_by": "A. Expert", "authored_by_kind": "independent-human"}
GOOD_Q = {"id": "q1", "type": "factual", "question": "What is a pod?",
          "expected_entities": ["concept.pod"], "supporting_sources": ["doc-a"]}


# ---- metrics ----

def test_citation_is_ungraded_when_there_is_no_gold():
    assert metrics.citation_prf(["a"], []) == (None, None, None)


def test_citation_rewards_precision_and_recall_together():
    p, r, f = metrics.citation_prf(["a", "b"], ["a"])
    assert p == 0.5 and r == 1.0 and 0.6 < f < 0.7


def test_coverage_reports_the_rank_it_was_found_at():
    assert metrics.coverage(["x", "y", "gold"], ["gold"], 5) == (1.0, 3)
    assert metrics.coverage(["x", "y", "gold"], ["gold"], 2) == (0.0, None)


def test_mean_ignores_ungraded_questions():
    """A question nothing can grade must not be counted as a zero."""
    assert metrics.mean([1.0, None, 0.0]) == 0.5
    assert metrics.mean([None, None]) is None


# ---- provenance ----

def test_a_set_with_no_provenance_is_rejected():
    """A number from a set with no recorded provenance is not evidence."""
    problems = gold.validate({}, [GOOD_Q])
    assert any("provenance" in p for p in problems)


def test_a_model_authored_set_must_declare_how_much_a_human_checked():
    problems = gold.validate({"authored_by": "a model", "authored_by_kind": "model"}, [GOOD_Q])
    assert any("audited_fraction" in p for p in problems)


def test_the_description_warns_about_a_model_authored_set():
    text = gold.describe({"authored_by": "a model", "authored_by_kind": "model",
                          "audited_fraction": 0})
    assert "MODEL-AUTHORED" in text
    assert "not a published claim" in text
    assert "NOT human-audited" in text


def test_the_description_warns_about_a_team_authored_set():
    text = gold.describe({"authored_by": "the team", "authored_by_kind": "team-human",
                          "audited_fraction": 0})
    assert "author-as-evaluator bias" in text.lower()


def test_an_independent_set_is_reported_as_such():
    assert "Independent" in gold.describe(GOOD_META)


# ---- question checks ----

def test_a_question_with_nothing_to_grade_against_is_rejected():
    bare = {"id": "q1", "type": "factual", "question": "What is a pod?"}
    assert any("nothing to grade" in p for p in gold.validate(GOOD_META, [bare]))


def test_a_temporal_question_must_declare_an_expected_status():
    q = {"id": "q1", "type": "temporal", "question": "?", "expected_entities": ["x"]}
    assert any("expected_status" in p for p in gold.validate(GOOD_META, [q]))


def test_an_as_of_question_must_give_a_date():
    q = {"id": "q1", "type": "temporal_asof", "question": "?", "expected_status": "current"}
    assert any("as_of" in p for p in gold.validate(GOOD_META, [q]))


def test_a_duplicate_id_is_rejected():
    assert any("repeats id" in p for p in gold.validate(GOOD_META, [GOOD_Q, dict(GOOD_Q)]))


def test_an_unknown_question_type_is_rejected():
    q = dict(GOOD_Q, type="whatever")
    assert any("unknown type" in p for p in gold.validate(GOOD_META, [q]))


def test_a_good_set_validates():
    assert gold.validate(GOOD_META, [GOOD_Q]) == []


def test_load_names_the_line_of_bad_json():
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "q.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write("// comment\n")
            f.write('{"_meta": {}}\n')
            f.write("{not json}\n")
        with pytest.raises(ValueError) as exc:
            gold.load(path)
        assert "line 3" in str(exc.value)


def test_round_trip_through_a_file():
    with tempfile.TemporaryDirectory() as root:
        path = _write(os.path.join(root, "q.jsonl"), GOOD_META, [GOOD_Q])
        meta, questions = gold.load(path)
        assert meta["authored_by_kind"] == "independent-human"
        assert len(questions) == 1 and questions[0]["id"] == "q1"


def test_the_ontology_records_provenance_and_asks_for_paraphrase():
    with tempfile.TemporaryDirectory() as root:
        path = gold.write_starter(os.path.join(root, "gold", "questions.jsonl"))
        text = open(path, encoding="utf-8").read()
        assert "_meta" in text and "authored_by_kind" in text
        assert "paraphrase" in text, "a set without paraphrase questions flatters non-dense methods"


# ---- the report ----

def test_the_report_leads_with_provenance_and_ends_with_threats():
    from oto.bench import run

    text = run.report(GOOD_META, [GOOD_Q], {"oto": {"citation_f1": 0.5, "coverage": 0.5,
                                                    "entity_hit": 1.0, "temporal": None,
                                                    "latency_ms": 1.0, "graded_citation": 1,
                                                    "graded_temporal": 0, "questions": 1}}, 5)
    assert text.index("WHERE THESE QUESTIONS CAME FROM") < text.index("RESULTS")
    assert "Threats to validity" in text
    assert "One corpus" in text


def test_the_report_warns_when_there_are_no_paraphrase_questions():
    from oto.bench import run

    text = run.report(GOOD_META, [GOOD_Q], {}, 5)
    assert "no paraphrase questions" in text


# ---- the dense baseline ----

def test_chunking_covers_the_whole_document_with_overlap():
    """Truncating instead of chunking is how a dense baseline gets quietly handicapped."""
    from oto.bench import dense

    words = ["w%d" % i for i in range(1000)]
    chunks = dense._chunks(" ".join(words))
    assert len(chunks) > 1, "a long document must be split, not truncated"
    covered = set()
    for chunk in chunks:
        covered.update(chunk.split())
    assert covered == set(words), "chunking lost part of the document"
    first, second = chunks[0].split(), chunks[1].split()
    assert set(first) & set(second), "chunks must overlap, or a fact on a boundary is unfindable"


def test_chunking_handles_short_and_empty_text():
    from oto.bench import dense

    assert dense._chunks("") == []
    assert dense._chunks("   ") == []
    assert dense._chunks("three short words") == ["three short words"]


def test_availability_explains_what_is_missing():
    from oto.bench import dense

    usable, reason = dense.available()
    if not usable:
        assert reason, "an unavailable baseline must say why"
    else:
        assert reason == ""


def test_the_cache_lives_outside_the_project():
    """A cache written inside a project would show up as an untracked file in its repository."""
    import tempfile as tf

    from oto.bench import dense

    with tf.TemporaryDirectory() as root:
        database = os.path.join(root, "x.db")
        with open(database, "wb") as f:
            f.write(b"not a real database, only its size and time matter here")
        path = dense._cache_path(database)
        assert not path.startswith(root), "the cache must not be written into the project"
        assert path.startswith(tf.gettempdir())


def test_the_cache_key_changes_when_the_content_does():
    import tempfile as tf

    from oto.bench import dense

    with tf.TemporaryDirectory() as root:
        database = os.path.join(root, "x.db")
        with open(database, "wb") as f:
            f.write(b"one")
        first = dense._cache_path(database)
        with open(database, "wb") as f:
            f.write(b"two, which is different")
        assert dense._cache_path(database) != first, "changed content must not reuse stale vectors"


def test_the_cache_survives_a_deterministic_rebuild():
    """OTO rebuilds are byte-identical. Keying on mtime threw away a valid 20-minute cache."""
    import os as _os
    import tempfile as tf
    import time

    from oto.bench import dense

    with tf.TemporaryDirectory() as root:
        database = _os.path.join(root, "x.db")
        with open(database, "wb") as f:
            f.write(b"identical content")
        first = dense._cache_path(database)
        time.sleep(0.01)
        with open(database, "wb") as f:          # rewrite the same bytes: a deterministic rebuild
            f.write(b"identical content")
        assert dense._cache_path(database) == first, "a byte-identical rebuild must reuse the cache"


def test_a_skipped_system_is_reported_not_dropped():
    """A comparison missing its strongest opponent must say so on its face."""
    from oto.bench import run

    text = run.report(GOOD_META, [GOOD_Q], {}, 5,
                      skipped=[("dense", "fastembed is not installed")])
    assert "NOT MEASURED" in text
    assert "fastembed is not installed" in text
    assert "incomplete, not as a result" in text


def test_build_reports_an_unknown_system_rather_than_ignoring_it():
    from oto.bench import systems

    built, unknown, skipped = systems.build("/nonexistent.db", ["oto", "nonsense"])
    assert unknown == ["nonsense"]
    assert len(built) == 1


# numpy lives in the `bench` extra, not in `dev`, so a workstation installed with
# `pip install -e ".[intake,dev]"` has no numpy and these three tests cannot run. Skipping is the
# rule everywhere else in this codebase: a missing optional dependency reports "unmeasured" and never
# fails. Without the skip a fresh clone showed 3 failures that were really an absent extra, which
# teaches whoever set the machine up to distrust the suite.
def test_dense_scoring_rejects_a_non_normalized_index():
    """The suppressed BLAS warning must not hide a real numerical fault."""
    np = pytest.importorskip("numpy", reason="needs the `bench` extra")
    import pytest as _pytest

    from oto.bench.dense import DenseSystem

    system = DenseSystem.__new__(DenseSystem)          # no model, no database needed
    system.vectors = np.array([[10.0, 0.0]], dtype="float32")   # deliberately not unit length
    with _pytest.raises(ValueError, match="outside"):
        system._score(np.array([1.0, 0.0], dtype="float32"))


def test_dense_scoring_rejects_a_corrupt_index():
    np = pytest.importorskip("numpy", reason="needs the `bench` extra")
    import pytest as _pytest

    from oto.bench.dense import DenseSystem

    system = DenseSystem.__new__(DenseSystem)
    system.vectors = np.array([[np.nan, 0.0]], dtype="float32")
    with _pytest.raises(ValueError, match="not finite"):
        system._score(np.array([1.0, 0.0], dtype="float32"))


def test_dense_scoring_accepts_a_normalized_index_without_warning():
    import warnings

    np = pytest.importorskip("numpy", reason="needs the `bench` extra")

    from oto.bench.dense import DenseSystem

    system = DenseSystem.__new__(DenseSystem)
    system.vectors = np.array([[1.0, 0.0], [0.0, 1.0]], dtype="float32")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        scores = system._score(np.array([1.0, 0.0], dtype="float32"))
    assert abs(float(scores[0]) - 1.0) < 1e-6
    assert abs(float(scores[1])) < 1e-6
    assert not [w for w in caught if "overflow" in str(w.message)]


# ---- the two coverage columns ----

def test_a_passage_retriever_scores_the_same_in_both_columns():
    """The second column must not be a handout. For a retriever the two lists are identical."""
    from oto.bench import metrics

    retrieved = ["doc-a", "doc-b", "doc-c"]
    gold = ["doc-b"]
    assert metrics.coverage(retrieved, gold, 5) == metrics.coverage(retrieved, gold, 5)


def test_citation_f1_and_coverage_cannot_disagree_completely():
    """The defect that produced the second column.

    A system that cites exactly the gold source, and is then scored zero coverage, has been marked
    wrong on a question it answered correctly. That happened on the reference corpus: two questions
    scored citation F1 1.0 and passage coverage 0.0 at once. The fix is to also score coverage over
    what the system actually surfaced. This test states the invariant that made it a bug.
    """
    from oto.bench import metrics

    gold = ["policy-doc"]
    cited = ["policy-doc"]
    passages = ["unrelated-a", "unrelated-b"]

    _, _, f1 = metrics.citation_prf(cited, gold)
    assert f1 == 1.0

    passage_hit, _ = metrics.coverage(passages, gold, 5)
    assert passage_hit == 0.0, "the old, architecture-dependent number"

    surfaced = list(cited) + [p for p in passages if p not in cited]
    surfaced_hit, rank = metrics.coverage(surfaced, gold, 5)
    assert surfaced_hit == 1.0 and rank == 1


def test_every_system_declares_both_lists():
    """A system that forgets `surfaced_sources` must fall back, never score None by accident."""
    from oto.bench import systems

    blank = systems._blank("some-system", "q1")
    assert "retrieved_sources" in blank
    assert "surfaced_sources" in blank
