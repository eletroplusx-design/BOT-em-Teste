from __future__ import annotations

import json

import pytest

from historical_multitimeframe_experiments import (
    HistoricalMultiTimeframeExperimentConflictError,
    HistoricalMultiTimeframeExperimentIntegrityError,
    HistoricalMultiTimeframeExperimentPromotionError,
    HistoricalMultiTimeframeExperimentValidationError,
    HistoricalMultiTimeframeReplay,
    build_historical_multitimeframe_experiment_plan,
    build_historical_multitimeframe_replay,
    load_historical_multitimeframe_experiment_report,
    reject_historical_multitimeframe_promotion,
    run_historical_multitimeframe_experiment,
    save_historical_multitimeframe_experiment_report,
    status_historical_multitimeframe_experiment_report,
    verify_historical_multitimeframe_experiment_report,
)
from market_data import build_historical_multitimeframe_bundle
from tests.test_historical_multitimeframe_phase12b import BASE_15M_START, _kucoin_dataset, _mutated_dataset


def _runner(snapshot):
    assert snapshot.base_point.candle.close_time == snapshot.decision_time_utc
    assert all(point.candle.close_time <= snapshot.decision_time_utc for point in snapshot.supporting_points)
    return {"decision_time": snapshot.decision_time_utc, "base_close": snapshot.base_point.candle.close}


def _runner_factory():
    return _runner


def _other_runner_factory():
    return _runner


def _replay(tmp_path):
    _, base = _kucoin_dataset(tmp_path, interval="15m", start=BASE_15M_START, count=20)
    # Use the established Phase 12B warmup layout for the supporting datasets.
    from datetime import timedelta
    _, one_hour = _kucoin_dataset(tmp_path, interval="1h", start=BASE_15M_START - timedelta(hours=1), count=7)
    _, four_hour = _kucoin_dataset(tmp_path, interval="4h", start=BASE_15M_START - timedelta(hours=4), count=4)
    return build_historical_multitimeframe_replay(build_historical_multitimeframe_bundle(base, one_hour, four_hour))


def test_replay_preserves_bundle_provenance_and_is_deterministic(tmp_path):
    replay = _replay(tmp_path)
    rebuilt = build_historical_multitimeframe_replay(replay.bundle)

    assert replay.replay_hash == rebuilt.replay_hash
    assert replay.provenance.bundle_hash == replay.bundle.bundle_hash
    assert replay.provenance.alignment_policy_hash
    assert len(replay.snapshots) == len(replay.bundle.base_dataset.candles)
    assert all(point.candle.close_time <= snapshot.decision_time_utc for snapshot in replay.snapshots for point in snapshot.supporting_points)


def test_replay_rejects_tampered_snapshot_and_divergent_bundle(tmp_path):
    replay = _replay(tmp_path)
    with pytest.raises(HistoricalMultiTimeframeExperimentValidationError, match="snapshots diverge"):
        HistoricalMultiTimeframeReplay(bundle=replay.bundle, snapshots=replay.snapshots[:-1], provenance=replay.provenance)

    mutated = _mutated_dataset(replay.bundle.supporting_datasets[0], mutate_index=0)
    divergent = build_historical_multitimeframe_bundle(replay.bundle.base_dataset, mutated, replay.bundle.supporting_datasets[1])
    with pytest.raises(HistoricalMultiTimeframeExperimentValidationError, match="provenance diverges"):
        HistoricalMultiTimeframeReplay(bundle=divergent, snapshots=replay.snapshots, provenance=replay.provenance)


def test_future_candles_do_not_change_historical_snapshot_semantics(tmp_path):
    replay = _replay(tmp_path)
    historical = replay.snapshots[4]
    mutated_support = _mutated_dataset(replay.bundle.supporting_datasets[0], mutate_index=-1, open_delta=50)
    changed_bundle = build_historical_multitimeframe_bundle(replay.bundle.base_dataset, mutated_support, replay.bundle.supporting_datasets[1])
    changed = build_historical_multitimeframe_replay(changed_bundle)

    assert historical.base_point == changed.snapshots[4].base_point
    assert tuple(point.candle for point in historical.supporting_points) == tuple(point.candle for point in changed.snapshots[4].supporting_points)
    assert replay.replay_hash != changed.replay_hash


def test_plan_fingerprints_the_factory_and_runner_gets_no_future_candle(tmp_path):
    replay = _replay(tmp_path)
    plan = build_historical_multitimeframe_experiment_plan(replay, runner_factory=_runner_factory, seed=7)
    report = run_historical_multitimeframe_experiment(replay, runner_factory=_runner_factory, seed=7, plan=plan)

    assert report.plan.plan_hash == plan.plan_hash
    assert report.plan.runner_factory_fingerprint.identity.endswith(":_runner_factory")
    assert len(report.results) == len(replay.snapshots)
    with pytest.raises(HistoricalMultiTimeframeExperimentValidationError, match="plan hash mismatch"):
        type(plan)(replay=replay, runner_factory_fingerprint=plan.runner_factory_fingerprint, seed=7, plan_hash="0" * 64)
    with pytest.raises(HistoricalMultiTimeframeExperimentValidationError, match="fingerprinted runner factory"):
        run_historical_multitimeframe_experiment(replay, runner_factory=_other_runner_factory, plan=plan)


def test_report_is_write_once_hostile_and_never_promotion_evidence(tmp_path):
    report = run_historical_multitimeframe_experiment(_replay(tmp_path), runner_factory=_runner_factory)
    path = tmp_path / "reports" / "mtf.json"
    assert save_historical_multitimeframe_experiment_report(path, report).report_hash == report.report_hash
    assert save_historical_multitimeframe_experiment_report(path, report).report_hash == report.report_hash
    assert verify_historical_multitimeframe_experiment_report(path)["verified"] is True
    assert status_historical_multitimeframe_experiment_report(path)["base_interval"] == "15m"
    with pytest.raises(HistoricalMultiTimeframeExperimentPromotionError):
        reject_historical_multitimeframe_promotion(report)

    changed = run_historical_multitimeframe_experiment(_replay(tmp_path), runner_factory=_other_runner_factory)
    with pytest.raises(HistoricalMultiTimeframeExperimentConflictError):
        save_historical_multitimeframe_experiment_report(path, changed)


def test_loader_rejects_payload_and_provenance_tampering(tmp_path):
    report = run_historical_multitimeframe_experiment(_replay(tmp_path), runner_factory=_runner_factory)
    path = tmp_path / "mtf.json"
    save_historical_multitimeframe_experiment_report(path, report)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["replay"]["provenance"]["bundle_hash"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(HistoricalMultiTimeframeExperimentIntegrityError):
        load_historical_multitimeframe_experiment_report(path)


def test_research_only_invariants_are_fail_closed(tmp_path):
    replay = _replay(tmp_path)
    with pytest.raises(HistoricalMultiTimeframeExperimentValidationError, match="classification"):
        build_historical_multitimeframe_experiment_plan(replay, runner_factory=_runner_factory, execution_config={"classification": "operational"}).__class__(
            replay=replay,
            runner_factory_fingerprint=build_historical_multitimeframe_experiment_plan(replay, runner_factory=_runner_factory).runner_factory_fingerprint,
            classification="operational",
        )
