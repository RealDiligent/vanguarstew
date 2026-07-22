# Spec 076 — leaderboard ranking

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1941
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/trend.py`](../../benchmark/trend.py) (the `headline_score` extractor
  this ranking binds, Spec 066 in flight), [`benchmark/compare_eval.py`](../../benchmark/compare_eval.py)
  (the two-artifact diff sibling), [`scripts/leaderboard.py`](../../scripts/leaderboard.py)
  (CLI wrapper)

This spec makes the **existing, implicit** leaderboard ranking contract explicit. It describes the
as-built behavior of `benchmark/leaderboard.py`; it introduces **no behavior change**.

## Why

`compare_eval` diffs *two* artifacts and `trend` tracks *one* score over successive runs;
`rank()` is the third N-way operation — *which candidate wins* — and the one the operator actually
publishes. Its guarantees accreted across merged hardening rounds (#532 container/pair guards,
non-finite component degradation mirroring #1397/#1183, the M7 foresight breakdown columns)
without an SDD contract. Making the contract explicit pins the tie semantics, the
unscored-separation invariant (a partial/malformed entry can never silently win or crash the
board), and the exact headline strings, so a silent regression in any of them is caught by
contract tests.

## User stories

1. **As a benchmark operator**, I can rank several candidate artifacts and read competition ranks,
   each row's distance from the best, and the component axes explaining *why* it ranks there.
2. **As a CI maintainer**, I can log a stable `leaderboard_headline()` string alongside the JSON
   summary.
3. **As a reviewer**, malformed-input handling, tie semantics, and every headline branch are
   written down.

## Acceptance criteria (EARS)

### Score extraction and unscored separation

- `rank(entries)` SHALL extract each artifact's comparable score with
  `benchmark.trend.headline_score`: the top-level `composite_mean` for single/multi-repo
  artifacts, the **tuned** partition's `composite_mean` for a `--generalization` artifact.
- WHEN `headline_score` yields `None` (including the `scored_repos: 0` unscored-placeholder
  artifact) THEN the entry's label SHALL be reported in `unscored` and SHALL NOT appear in
  `ranking`.

### Ordering and competition ranking

- Scored entries SHALL be ordered highest score first; equal scores SHALL keep their input order
  (stable ordering by original entry index).
- `rank` values SHALL use standard competition ranking: a row whose score equals the previous
  row's score SHALL share the previous row's rank, and the next distinct score SHALL take its
  1-based position (ranks skip after a tie: 1, 2, 2, 4).
- `delta_from_best` SHALL be `composite_mean - best` rounded to 3 decimals: `0.0` for the leader,
  negative for every other row.

### Ranking row shape

- Every ranking row SHALL carry exactly the keys `rank`, `label`, `composite_mean`,
  `delta_from_best`, `judge_mean`, `objective_mean`, `module_recall_mean`, `kind_recall_mean`,
  `release_accuracy`.
- `composite_mean` SHALL be the extracted headline score; the last five keys SHALL come from the
  components extraction below.

### Numeric semantics (`_is_number` / `_round`)

- Only finite, non-boolean `int`/`float` values SHALL count as numeric; `bool`, `NaN`, `inf`,
  `-inf`, non-numeric types, and an oversized `int` that cannot convert to `float`
  (`OverflowError`) SHALL NOT.
- `_round(value)` SHALL return `round(float(value), 3)` for numeric values and `None` otherwise.

### Components extraction (`_components`)

- The components SHALL be read from the artifact's headline partition: the **`tuned`** partition
  when **both** `tuned` and `held_out` are dicts, the top level otherwise.
- `judge_mean` / `objective_mean` SHALL come from the partition's `composite_parts`;
  `module_recall_mean` / `kind_recall_mean` / `release_accuracy` from the partition's `foresight`;
  each value passed through `_round`.
- WHEN the artifact is not a `dict`, or `composite_parts` / `foresight` is missing or not a
  `dict`, or a mean is non-finite THEN the affected components SHALL degrade to `None`
  (never raise) — and a non-dict artifact SHALL yield a fresh all-`None` dict.

### Container and pair guards

- WHEN `entries` is not a `list` THEN `rank` SHALL treat it as empty; a non-`None` non-list SHALL
  log a warning naming the actual type; `None` SHALL be silent.
- An entry SHALL be accepted only when it is a `list`/`tuple` of length 2; any other entry
  (including `bytes` and wrong-length sequences) SHALL be skipped with a warning naming
  `entries[{index}]`, the entry's type, and its `repr` truncated to 120 characters.
- A skipped entry SHALL appear in neither `ranking` nor `unscored` and SHALL NOT count toward
  `scored` / `total`.

### Summary shape

- Every `rank` result SHALL carry exactly `ranking`, `best`, `unscored`, `scored`, `total`.
- `best` SHALL be `{"label", "composite_mean"}` of the top row, or `None` when nothing scored.
- `scored` SHALL be the ranked-row count; `total` SHALL be `scored` plus the unscored count.
- WHEN `entries` is empty, all-unscored, or entirely skipped THEN `ranking` SHALL be `[]` and
  `best` SHALL be `None` (never raise).

### Leaderboard headline

- WHEN `summary` is not a `dict` or its `scored` is falsy THEN the headline SHALL be exactly:
  `leaderboard: no scored artifacts`.
- OTHERWISE the headline SHALL be
  `leaderboard: {label} leads at {composite_mean}` plus ` over {runners} other(s)` only when
  `scored - 1 > 0`, plus `; {unscored} unscored` only when the unscored count is non-zero.
- WHEN `summary["unscored"]` is not a `list` THEN it SHALL count as zero unscored labels; a
  non-`None` non-list SHALL log a warning; a missing/`None` `best` SHALL degrade to `None`
  placeholders in the headline rather than raising.

### Pure evaluation

- The module SHALL perform no I/O.
- `rank()` SHALL NOT mutate its input entries or artifacts.

## Out of scope

- `headline_score` extraction internals (`benchmark/trend.py`, Spec 066 in flight) — reused, not
  redefined.
- The CLI wrapper `scripts/leaderboard.py` (artifact loading, clean error paths) — covered by
  `tests/test_leaderboard.py`.
- The published feed shape (`scripts/leaderboard_feed.py`), a distinct module.

## Verification

- `tests/test_spec_076_leaderboard.py` exercises each EARS block above: extraction for
  single/multi and generalization artifacts plus the unscored-placeholder separation, stable tie
  ordering and the 1-2-2-4 competition ranks, the exact row and summary key sets, the leader's
  `0.0` / negative `delta_from_best`, `_is_number`/`_round` semantics (bool, `NaN`, `±inf`,
  oversized int), the headline-partition rule and all-`None` degradations, both #532 guards with
  their warning texts, and every headline branch pinned as **literal** strings.
- Broader coverage (shipped CLI, load-error paths) remains in `tests/test_leaderboard.py`.
