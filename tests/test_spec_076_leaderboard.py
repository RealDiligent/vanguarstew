"""Contract tests for Spec 076 — leaderboard ranking (as-built, no behavior change).

Each test group pins one EARS section of ``specs/076-benchmark-leaderboard/spec.md``.
Expected headline strings and warning texts are pinned as literal values so a silent wording
change is caught. Deterministic and offline; fixture artifacts are built inline (no file I/O).
"""

import json
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.leaderboard import (  # noqa: E402
    _EMPTY_COMPONENTS,
    _components,
    _is_number,
    _round,
    leaderboard_headline,
    rank,
)

ROW_KEYS = {
    "rank", "label", "composite_mean", "delta_from_best",
    "judge_mean", "objective_mean",
    "module_recall_mean", "kind_recall_mean", "release_accuracy",
}


def _single(score, parts=None, foresight=None):
    artifact = {"composite_mean": score}
    if parts is not None:
        artifact["composite_parts"] = parts
    if foresight is not None:
        artifact["foresight"] = foresight
    return artifact


def _gen(tuned_score, parts=None, foresight=None):
    tuned = _single(tuned_score, parts, foresight)
    return {"tuned": tuned, "held_out": {"composite_mean": 0.1}}


def _row(summary, label):
    return next(row for row in summary["ranking"] if row["label"] == label)


# --- Score extraction and unscored separation ----------------------------------------------

def test_headline_score_extraction_single_and_generalization():
    summary = rank([("single", _single(0.4)), ("gen", _gen(0.6))])
    assert _row(summary, "single")["composite_mean"] == 0.4
    # A --generalization artifact ranks on its tuned partition, not held_out.
    assert _row(summary, "gen")["composite_mean"] == 0.6
    assert summary["unscored"] == []


def test_unscored_placeholder_and_missing_score_separated():
    entries = [
        ("real", _single(0.5)),
        # An aggregate that scored no repos carries a placeholder 0.0 -- unscored, never ranked.
        ("placeholder", {"composite_mean": 0.0, "scored_repos": 0}),
        ("empty", {}),
        ("not-a-dict", "artifact"),
    ]
    summary = rank(entries)
    assert [row["label"] for row in summary["ranking"]] == ["real"]
    assert summary["unscored"] == ["placeholder", "empty", "not-a-dict"]
    assert summary["scored"] == 1
    assert summary["total"] == 4


# --- Ordering and competition ranking ------------------------------------------------------

def test_best_first_stable_tie_order():
    summary = rank([
        ("mid-first", _single(0.5)),
        ("low", _single(0.2)),
        ("mid-second", _single(0.5)),
        ("high", _single(0.9)),
    ])
    # Highest first; the tied 0.5 entries keep their input order.
    assert [row["label"] for row in summary["ranking"]] == [
        "high", "mid-first", "mid-second", "low",
    ]


def test_competition_ranks_skip_after_tie():
    summary = rank([
        ("a", _single(0.9)),
        ("b", _single(0.5)),
        ("c", _single(0.5)),
        ("d", _single(0.1)),
    ])
    assert [row["rank"] for row in summary["ranking"]] == [1, 2, 2, 4]


def test_delta_from_best_zero_for_leader_negative_for_rest():
    summary = rank([("best", _single(0.75)), ("trail", _single(0.5))])
    assert _row(summary, "best")["delta_from_best"] == 0.0
    assert _row(summary, "trail")["delta_from_best"] == -0.25


# --- Ranking row shape ---------------------------------------------------------------------

def test_row_key_set_exact():
    summary = rank([("only", _single(0.5))])
    assert set(summary["ranking"][0]) == ROW_KEYS


# --- Numeric semantics (_is_number / _round) -----------------------------------------------

def test_is_number_rejects_bool_nonfinite_and_oversized_int():
    assert _is_number(0.5) is True
    assert _is_number(2) is True
    for bad in (True, False, float("nan"), float("inf"), float("-inf"),
                10**400, None, "0.5", [0.5]):
        assert _is_number(bad) is False, bad


def test_round_three_decimals_or_none():
    assert _round(0.123456) == 0.123
    assert _round(2) == 2.0
    for bad in (True, float("nan"), float("inf"), 10**400, None, "x"):
        assert _round(bad) is None, bad


# --- Components extraction (_components) ---------------------------------------------------

def test_components_read_headline_partition():
    parts = {"judge_mean": 0.61234, "objective_mean": 0.4}
    foresight = {"module_recall_mean": 0.5, "kind_recall_mean": 0.25, "release_accuracy": 1.0}
    row = _row(rank([("gen", _gen(0.6, parts, foresight))]), "gen")
    assert row["judge_mean"] == 0.612  # tuned partition's parts, rounded to 3 decimals
    assert row["objective_mean"] == 0.4
    assert row["module_recall_mean"] == 0.5
    assert row["kind_recall_mean"] == 0.25
    assert row["release_accuracy"] == 1.0


def test_components_top_level_when_partition_incomplete():
    # The tuned partition is the headline only when BOTH tuned and held_out are dicts.
    artifact = {"composite_mean": 0.3,
                "composite_parts": {"judge_mean": 0.2, "objective_mean": 0.45},
                "tuned": {"composite_parts": {"judge_mean": 0.9}}}  # no held_out
    assert _components(artifact)["judge_mean"] == 0.2
    assert _components(artifact)["objective_mean"] == 0.45


def test_components_degrade_to_none():
    for artifact in (
        _single(0.5),                                        # parts and foresight absent
        _single(0.5, parts=42, foresight="nope"),            # both malformed
        _single(0.5, parts={"judge_mean": float("nan"),      # non-finite means
                            "objective_mean": float("inf")}),
    ):
        row = _row(rank([("x", artifact)]), "x")
        for key in ("judge_mean", "objective_mean", "module_recall_mean",
                    "kind_recall_mean", "release_accuracy"):
            assert row[key] is None, (artifact, key)


def test_non_dict_artifact_yields_fresh_all_none_components():
    components = _components("not a dict")
    assert components == _EMPTY_COMPONENTS
    assert components is not _EMPTY_COMPONENTS  # a fresh copy, never the shared template


# --- Container and pair guards -------------------------------------------------------------

def test_non_list_entries_warned_and_empty(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.leaderboard"):
        summary = rank(42)
    assert summary["ranking"] == [] and summary["total"] == 0
    assert any("entries is int, not a list" in r.message for r in caplog.records)


def test_none_entries_silent(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.leaderboard"):
        summary = rank(None)
    assert summary["ranking"] == [] and summary["total"] == 0
    assert not caplog.records


def test_malformed_pair_skipped_with_indexed_warning(caplog):
    entries = [("good", _single(0.5)), b"bad", ("too", "many", "items")]
    with caplog.at_level(logging.WARNING, logger="benchmark.leaderboard"):
        summary = rank(entries)
    assert [row["label"] for row in summary["ranking"]] == ["good"]
    messages = [r.message for r in caplog.records]
    assert any("entries[1] is not a (label, artifact) pair" in m and "bytes" in m
               for m in messages)
    assert any("entries[2] is not a (label, artifact) pair" in m for m in messages)


def test_skipped_entry_counts_nowhere():
    summary = rank([("good", _single(0.5)), 42])
    assert summary["unscored"] == []
    assert summary["scored"] == 1
    assert summary["total"] == 1  # the skipped entry is not an unscored candidate


# --- Summary shape -------------------------------------------------------------------------

def test_summary_key_set_and_counts():
    summary = rank([("a", _single(0.5)), ("b", {})])
    assert set(summary) == {"ranking", "best", "unscored", "scored", "total"}
    assert summary["best"] == {"label": "a", "composite_mean": 0.5}
    assert summary["scored"] == 1 and summary["total"] == 2


def test_empty_and_all_unscored_summary():
    for entries in ([], [("a", {}), ("b", None)]):
        summary = rank(entries)
        assert summary["ranking"] == []
        assert summary["best"] is None


# --- Leaderboard headline ------------------------------------------------------------------

def test_headline_no_scored_literal():
    for summary in (None, "x", 42, {}, {"scored": 0}, rank([])):
        assert leaderboard_headline(summary) == "leaderboard: no scored artifacts"


def test_headline_leader_only_literal():
    summary = rank([("solo", _single(0.5))])
    assert leaderboard_headline(summary) == "leaderboard: solo leads at 0.5"


def test_headline_runners_and_unscored_literal():
    summary = rank([("lead", _single(0.9)), ("trail", _single(0.4)), ("broken", {})])
    assert leaderboard_headline(summary) == (
        "leaderboard: lead leads at 0.9 over 1 other(s); 1 unscored"
    )


def test_headline_non_list_unscored_counts_zero(caplog):
    summary = {"scored": 1, "best": {"label": "a", "composite_mean": 0.5}, "unscored": 42}
    with caplog.at_level(logging.WARNING, logger="benchmark.leaderboard"):
        assert leaderboard_headline(summary) == "leaderboard: a leads at 0.5"
    assert any("summary unscored is int, not a list" in r.message for r in caplog.records)


def test_headline_missing_best_degrades():
    # A summary claiming scored entries but missing `best` degrades to None placeholders.
    assert leaderboard_headline({"scored": 1}) == "leaderboard: None leads at None"


# --- Pure evaluation -----------------------------------------------------------------------

def test_rank_does_not_mutate_entries_or_artifacts():
    artifact = _gen(0.6, parts={"judge_mean": 0.5, "objective_mean": 0.7})
    entries = [("gen", artifact), ("broken", {})]
    before = json.dumps(entries, sort_keys=True)
    rank(entries)
    assert json.dumps(entries, sort_keys=True) == before
