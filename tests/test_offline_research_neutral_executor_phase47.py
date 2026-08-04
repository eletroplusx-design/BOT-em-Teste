from __future__ import annotations

import inspect
import json
import shutil
import tempfile
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import pytest

import market_data.offline_research_canonical_evidence_fixture as phase44
import market_data.offline_research_execution_authorization as phase45
import market_data.offline_research_execution_envelope as phase46
import market_data.offline_research_neutral_executor as phase47


CANONICAL_ISSUED_AT_UTC = datetime(2026, 8, 1, 12, 0, 0, 123456, tzinfo=timezone.utc)
CANONICAL_INVALIDATION_AT_UTC = datetime(2026, 8, 1, 12, 0, 1, 654321, tzinfo=timezone.utc)
CANONICAL_ENVELOPE_CREATED_AT_UTC = datetime(2026, 8, 1, 12, 0, 2, 0, tzinfo=timezone.utc)
CANONICAL_REQUEST_CREATED_AT_UTC = datetime(2026, 8, 1, 12, 0, 3, 0, tzinfo=timezone.utc)


@lru_cache(maxsize=1)
def _canonical_verification() -> phase44.CanonicalOfflineResearchEvidenceVerification:
    root = Path(tempfile.mkdtemp(prefix="phase47-canonical-fixture-"))
    phase44.build_canonical_offline_research_evidence_fixture(root)
    return phase44.verify_canonical_offline_research_evidence_fixture(root)


def _fresh_verification(root: Path) -> phase44.CanonicalOfflineResearchEvidenceVerification:
    phase44.build_canonical_offline_research_evidence_fixture(root)
    return phase44.verify_canonical_offline_research_evidence_fixture(root)


def _canonical_authorization(
    verification: phase44.CanonicalOfflineResearchEvidenceVerification | None = None,
) -> phase45.OfflineResearchExecutionAuthorization:
    verification = verification or _canonical_verification()
    plan = verification.execution_plan_registry.plans[0]
    return phase45.build_offline_research_execution_authorization(
        plan=plan,
        evidence=verification,
        issued_at_utc=CANONICAL_ISSUED_AT_UTC,
        source_commit_sha=plan.source_commit_sha,
        source_branch=plan.source_branch,
    )


def _authorization_registry_file(
    root: Path,
    authorization: phase45.OfflineResearchExecutionAuthorization,
) -> Path:
    registry_file = root / "offline-research-execution-authorization-registry.json"
    phase45.register_offline_research_execution_authorization(
        registry_file=registry_file,
        authorization=authorization,
        updated_at_utc=CANONICAL_ISSUED_AT_UTC,
    )
    return registry_file


def _build_envelope(
    root: Path,
    *,
    verification: phase44.CanonicalOfflineResearchEvidenceVerification | None = None,
    authorization: phase45.OfflineResearchExecutionAuthorization | None = None,
) -> phase46.OfflineResearchExecutionEnvelope:
    verification = verification or _canonical_verification()
    authorization = authorization or _canonical_authorization(verification)
    auth_registry_file = _authorization_registry_file(root, authorization)
    return phase46.build_offline_research_execution_envelope(
        plan=verification.execution_plan_registry.plans[0],
        evidence=verification,
        authorization=authorization,
        authorization_registry_file=auth_registry_file,
        plan_registry_file=verification.execution_plan_registry.registry_file,
        random_seed=123,
        created_at_utc=CANONICAL_ENVELOPE_CREATED_AT_UTC,
    )


def _build_request(
    root: Path,
    *,
    verification: phase44.CanonicalOfflineResearchEvidenceVerification | None = None,
    envelope: phase46.OfflineResearchExecutionEnvelope | None = None,
    random_seed: int = 123,
) -> phase47.OfflineResearchNeutralExecutionRequest:
    verification = verification or _canonical_verification()
    envelope = envelope or _build_envelope(root, verification=verification)
    return phase47.build_neutral_execution_request(
        envelope=envelope,
        fixture_directory=verification.fixture.fixture_directory,
        output_directory=root / "neutral-output",
        registry_file=root / "neutral-output" / phase47.OFFLINE_RESEARCH_NEUTRAL_EXECUTION_REGISTRY_FILENAME,
        created_at_utc=CANONICAL_REQUEST_CREATED_AT_UTC,
        random_seed=random_seed,
    )


def _mutated_fixture_copy(src_root: Path, dst_root: Path, *, manifest_hash: str | None = None) -> Path:
    shutil.copytree(src_root, dst_root, dirs_exist_ok=True)
    if manifest_hash is not None:
        manifest_file = dst_root / phase44.CANONICAL_ARTIFACT_ROOT_REL / phase44.okx.OKX_HISTORICAL_MANIFEST_FILENAME
        payload = json.loads(manifest_file.read_text(encoding="utf-8"))
        payload["manifest_hash"] = manifest_hash
        manifest_file.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
    return dst_root


def test_phase47_executes_deterministically_and_persists_append_only(tmp_path):
    verification = _fresh_verification(tmp_path / "fixture")
    envelope = _build_envelope(tmp_path / "auth", verification=verification)
    request = _build_request(tmp_path / "run", verification=verification, envelope=envelope, random_seed=7)
    registry_file = request.registry_file

    first = phase47.execute_neutral_offline(
        request,
        started_at_utc=datetime(2026, 8, 1, 12, 0, 4, tzinfo=timezone.utc),
        finished_at_utc=datetime(2026, 8, 1, 12, 0, 5, tzinfo=timezone.utc),
        elapsed_monotonic_ns=1234,
    )
    first_text = registry_file.read_text(encoding="utf-8")
    second = phase47.execute_neutral_offline(
        request,
        started_at_utc=datetime(2026, 8, 1, 12, 0, 4, tzinfo=timezone.utc),
        finished_at_utc=datetime(2026, 8, 1, 12, 0, 5, tzinfo=timezone.utc),
        elapsed_monotonic_ns=1234,
    )
    loaded = phase47.load_neutral_execution_registry(registry_file)
    verified = phase47.verify_neutral_execution_registry(registry_file)

    assert first == second
    assert first.neutral_execution_id == second.neutral_execution_id
    assert first.result_hash == second.result_hash
    assert first.as_dict() == second.as_dict()
    assert registry_file.read_text(encoding="utf-8") == first_text
    assert loaded.record_count == 1
    assert verified.approved is True
    assert verified.record_count == 1
    assert verified.neutral_execution_ids == (first.neutral_execution_id,)
    assert verified.result_hashes == (first.result_hash,)
    assert first.status == "SUCCEEDED"
    assert first.offline_only is True
    assert first.historical_research_only is True
    assert first.neutral_execution_only is True
    assert first.network_access_used is False
    assert first.exchange_connectivity_used is False
    assert first.paper_trading_used is False
    assert first.live_trading_used is False
    assert first.order_submission_used is False
    assert first.strategy_execution_used is False
    assert first.operational_evidence is False
    assert first.paper_promotion_eligible is False
    assert first.request_hash == request.request_hash
    assert first.input_record_count == len(verification.dataset.candles)
    assert first.expected_record_count == len(verification.dataset.candles)
    assert first.duplicate_record_count == 0
    assert first.missing_record_count == 0
    assert first.first_record_timestamp == verification.dataset.candles[0].open_time.isoformat().replace("+00:00", "Z")
    assert first.last_record_timestamp == verification.dataset.candles[-1].open_time.isoformat().replace("+00:00", "Z")
    assert first.min_timestamp == first.first_record_timestamp
    assert first.max_timestamp == first.last_record_timestamp
    assert first.ordered_records[0] == first.first_record_timestamp
    assert first.ordered_records[-1] == first.last_record_timestamp
    assert first.input_sequence_hash == second.input_sequence_hash
    assert first.neutral_transform_hash == second.neutral_transform_hash
    assert first.result_hash == first.as_dict()["result_hash"]
    assert first.neutral_execution_id == first.as_dict()["neutral_execution_id"]


def test_phase47_request_and_result_are_deeply_immutable(tmp_path):
    verification = _fresh_verification(tmp_path / "fixture")
    envelope = _build_envelope(tmp_path / "auth", verification=verification)
    request = _build_request(tmp_path / "run", verification=verification, envelope=envelope)
    result = phase47.execute_neutral_offline(request)

    with pytest.raises(TypeError):
        request.resource_limits["max_event_count"] = 1
    with pytest.raises(TypeError):
        request.execution_environment["network_access_allowed"] = True
    with pytest.raises(TypeError):
        request.output_policy["overwrite_existing"] = True
    with pytest.raises(TypeError):
        result.resource_limits_snapshot["max_event_count"] = 1
    with pytest.raises(TypeError):
        result.execution_environment_snapshot["offline_only"] = False
    with pytest.raises(TypeError):
        result.output_policy_snapshot["overwrite_existing"] = True
    with pytest.raises(AttributeError):
        result.ordered_records.append("x")  # type: ignore[attr-defined]

    object.__setattr__(request, "random_seed", 99)
    with pytest.raises(phase47.OfflineResearchNeutralExecutionIntegrityError, match="request_hash mismatch"):
        phase47.verify_neutral_execution_request(request)


def test_phase47_rejects_invalid_envelope(tmp_path):
    verification = _fresh_verification(tmp_path / "fixture")
    envelope = _build_envelope(tmp_path / "auth", verification=verification)
    request = _build_request(tmp_path / "run", verification=verification, envelope=envelope)
    object.__setattr__(request.envelope, "envelope_hash", "0" * 64)

    with pytest.raises(phase47.OfflineResearchNeutralExecutionIntegrityError, match="request_hash mismatch"):
        phase47.verify_neutral_execution_request(request)


def test_phase47_rejects_invalid_authorization_snapshot(tmp_path):
    verification = _fresh_verification(tmp_path / "fixture")
    envelope = _build_envelope(tmp_path / "auth", verification=verification)
    request = _build_request(tmp_path / "run", verification=verification, envelope=envelope)
    object.__setattr__(
        request.envelope,
        "authorization_snapshot",
        dict(request.envelope.authorization_snapshot, allow_future_offline_execution=False),
    )

    with pytest.raises(phase47.OfflineResearchNeutralExecutorError, match="authorization must allow future offline execution"):
        phase47.verify_neutral_execution_request(request)


def test_phase47_rejects_fixture_manifest_drift(tmp_path):
    verification = _fresh_verification(tmp_path / "fixture")
    envelope = _build_envelope(tmp_path / "auth", verification=verification)
    mutated_root = tmp_path / "fixture-mismatch"
    _mutated_fixture_copy(
        verification.fixture.fixture_directory,
        mutated_root,
        manifest_hash="0" * 64,
    )
    tampered_request = phase47.build_neutral_execution_request(
        envelope=envelope,
        fixture_directory=mutated_root,
        output_directory=tmp_path / "other-output",
        registry_file=tmp_path / "other-output" / phase47.OFFLINE_RESEARCH_NEUTRAL_EXECUTION_REGISTRY_FILENAME,
        created_at_utc=CANONICAL_REQUEST_CREATED_AT_UTC,
        random_seed=7,
    )

    with pytest.raises(phase47.OfflineResearchNeutralExecutionValidationError, match="manifest_hash"):
        phase47.execute_neutral_offline(tampered_request)


def test_phase47_rejects_resource_limits_and_supports_append_only_chain(tmp_path):
    verification = _fresh_verification(tmp_path / "fixture")
    envelope = _build_envelope(tmp_path / "auth", verification=verification)
    request = _build_request(tmp_path / "run", verification=verification, envelope=envelope)
    object.__setattr__(
        request,
        "resource_limits",
        phase47._freeze_read_only_value(
            {
                "max_runtime_seconds": 1,
                "max_memory_mb": 1,
                "max_output_bytes": 1,
                "max_event_count": 1,
            }
        ),
    )
    object.__setattr__(
        request.envelope,
        "resource_limits",
        phase47._freeze_read_only_value(
            {
                "max_runtime_seconds": 1,
                "max_memory_mb": 1,
                "max_output_bytes": 1,
                "max_event_count": 1,
            }
        ),
    )
    object.__setattr__(request, "request_hash", phase47._hash_payload(request._request_identity_payload()))

    with pytest.raises(phase47.OfflineResearchNeutralExecutionResourceLimitError, match="max_event_count exceeded"):
        phase47.execute_neutral_offline(request)

    chain_envelope = _build_envelope(tmp_path / "auth-chain", verification=verification)
    first_request = _build_request(tmp_path / "chain", verification=verification, envelope=chain_envelope, random_seed=7)
    second_request = _build_request(tmp_path / "chain", verification=verification, envelope=chain_envelope, random_seed=8)
    first = phase47.execute_neutral_offline(first_request)
    second = phase47.execute_neutral_offline(second_request)
    registry = phase47.load_neutral_execution_registry(first_request.registry_file)

    assert registry.record_count == 2
    assert registry.records[0].execution_number == 1
    assert registry.records[1].execution_number == 2
    assert registry.records[1].previous_execution_id == registry.records[0].neutral_execution_id
    assert registry.records[1].previous_execution_hash == registry.records[0].result_hash
    assert first.neutral_execution_id != second.neutral_execution_id
    assert first.result_hash != second.result_hash


def test_phase47_module_stays_neutral_and_does_not_import_strategy_or_operational_clients():
    source = inspect.getsource(phase47)
    assert "baseline_a_okx_btc_usdt_research" not in source
    assert "subprocess" not in source
    assert "threading" not in source
    assert "requests" not in source
    assert "OkxPublicSpotHistoryCandlesProvider" not in source
    assert "KuCoinPublicSpotKlinesProvider" not in source
