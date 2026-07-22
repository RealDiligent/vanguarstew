# Plan 076 — leaderboard ranking

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1941

Maps the [spec](./spec.md) onto `benchmark/leaderboard.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_076_leaderboard.py` |
| ------------ | -------------------------------------------- |
| Score extraction and unscored separation | `test_headline_score_extraction_single_and_generalization`, `test_unscored_placeholder_and_missing_score_separated` |
| Ordering and competition ranking | `test_best_first_stable_tie_order`, `test_competition_ranks_skip_after_tie`, `test_delta_from_best_zero_for_leader_negative_for_rest` |
| Ranking row shape | `test_row_key_set_exact` |
| Numeric semantics | `test_is_number_rejects_bool_nonfinite_and_oversized_int`, `test_round_three_decimals_or_none` |
| Components extraction | `test_components_read_headline_partition`, `test_components_top_level_when_partition_incomplete`, `test_components_degrade_to_none`, `test_non_dict_artifact_yields_fresh_all_none_components` |
| Container and pair guards | `test_non_list_entries_warned_and_empty`, `test_none_entries_silent`, `test_malformed_pair_skipped_with_indexed_warning`, `test_skipped_entry_counts_nowhere` |
| Summary shape | `test_summary_key_set_and_counts`, `test_empty_and_all_unscored_summary` |
| Leaderboard headline | `test_headline_no_scored_literal`, `test_headline_leader_only_literal`, `test_headline_runners_and_unscored_literal`, `test_headline_non_list_unscored_counts_zero`, `test_headline_missing_best_degrades` |
| Pure evaluation | `test_rank_does_not_mutate_entries_or_artifacts` |

## Verification strategy

One contract-test group per EARS section, mirroring the merged sibling specs (059–062 gates, 068
order-share, 075 repo-set readiness). Expected headline strings and warning texts are pinned as
**literal** values rather than rebuilt from the module's own formatting, so a silent wording
change is caught. Boundary cases carry the contract weight: the 1-2-2-4 tie skip, tie rows keeping
input order, the tuned-partition rule requiring **both** partitions to be dicts, and the
`repr`-truncated pair-guard warning. Fixture artifacts are built inline (no file I/O), keeping the
tests deterministic and offline. Integration coverage (the CLI and its load-error paths) stays in
`tests/test_leaderboard.py`.
