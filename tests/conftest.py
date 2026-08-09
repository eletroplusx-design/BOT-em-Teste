import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def sample_df():
    return pd.DataFrame(
        {
            "open": [60000, 60100, 60200, 60300, 60400],
            "high": [60100, 60200, 60300, 60400, 60500],
            "low": [59900, 60000, 60100, 60200, 60300],
            "close": [60050, 60150, 60250, 60350, 60450],
            "volume": [100, 110, 120, 130, 140],
            "timestamp": pd.date_range("2026-01-01", periods=5, freq="h"),
        }
    )


@pytest.fixture
def sample_btc_data():
    rows = 1200
    closes = []
    for idx in range(rows):
        bloco = idx % 40
        if bloco < 20:
            closes.append(50000 + bloco * 15)
        else:
            closes.append(50300 - (bloco - 20) * 15)
    base = pd.DataFrame(
        {
            "open_time": pd.date_range("2025-01-01", periods=rows, freq="h", tz="UTC"),
            "close_time": pd.date_range("2025-01-01", periods=rows, freq="h", tz="UTC"),
            "open": [valor - 5 for valor in closes],
            "high": [valor + 15 for valor in closes],
            "low": [valor - 20 for valor in closes],
            "close": closes,
            "volume": [1000 + (idx % 50) * 10 for idx in range(rows)],
        }
    )
    base.attrs["fonte_dados"] = "BINANCE"
    return base


@pytest.fixture
def trend_df():
    rows = 220
    closes = []
    for idx in range(rows):
        bloco = idx % 20
        if bloco < 10:
            closes.append(100 + bloco * 2)
        else:
            closes.append(120 - (bloco - 10) * 2)
    base = pd.DataFrame(
        {
            "open": [valor - 1 for valor in closes],
            "high": [valor + 1 for valor in closes],
            "low": [valor - 2 for valor in closes],
            "close": closes,
            "volume": [1000 + i for i in range(rows)],
            "timestamp": pd.date_range("2026-01-01", periods=rows, freq="h"),
        }
    )
    return base


@pytest.fixture
def temp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path


@pytest.fixture
def mock_binance_exchange_info():
    return {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "filters": [
                    {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001", "maxQty": "1000"},
                    {"filterType": "PRICE_FILTER", "tickSize": "0.01", "minPrice": "0.01", "maxPrice": "1000000"},
                    {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                ],
            }
        ]
    }


@pytest.fixture(scope="session")
def canonical_artifacts_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from market_data import offline_research_canonical_evidence_fixture as phase44

    root = tmp_path_factory.mktemp("phase48-49-canonical-artifacts")
    phase44.build_canonical_offline_research_evidence_fixture(root)
    return root


@pytest.fixture(scope="session")
def canonical_verification(canonical_artifacts_root: Path):
    from market_data import offline_research_canonical_evidence_fixture as phase44

    return phase44.verify_canonical_offline_research_evidence_fixture(canonical_artifacts_root)


@pytest.fixture(scope="session")
def canonical_runtime_bundle(canonical_artifacts_root: Path, canonical_verification):
    from market_data import offline_research_execution_authorization as phase45
    from market_data import offline_research_execution_envelope as phase46
    from market_data import offline_research_neutral_executor as phase47

    verification = canonical_verification
    plan = verification.execution_plan_registry.plans[0]

    authorization_registry_file = canonical_artifacts_root / "offline-research-execution-authorization-registry.json"
    authorization = phase45.build_offline_research_execution_authorization(
        plan=plan,
        evidence=verification,
        issued_at_utc=datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc),
        source_commit_sha=plan.source_commit_sha,
        source_branch=plan.source_branch,
    )
    phase45.register_offline_research_execution_authorization(
        registry_file=authorization_registry_file,
        authorization=authorization,
        updated_at_utc=datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc),
    )

    envelope = phase46.build_offline_research_execution_envelope(
        plan=plan,
        evidence=verification,
        authorization=authorization,
        authorization_registry_file=authorization_registry_file,
        plan_registry_file=verification.execution_plan_registry.registry_file,
        random_seed=7,
        created_at_utc=datetime(2026, 8, 1, 12, 0, 1, tzinfo=timezone.utc),
        source_commit_sha=plan.source_commit_sha,
        source_branch=plan.source_branch,
    )

    request = phase47.build_neutral_execution_request(
        envelope=envelope,
        fixture_directory=verification.fixture.fixture_directory,
        output_directory=canonical_artifacts_root / "neutral-output",
        registry_file=canonical_artifacts_root
        / "neutral-output"
        / phase47.OFFLINE_RESEARCH_NEUTRAL_EXECUTION_REGISTRY_FILENAME,
        created_at_utc=datetime(2026, 8, 1, 12, 0, 2, tzinfo=timezone.utc),
        random_seed=7,
    )
    result = phase47.execute_neutral_offline(
        request,
        started_at_utc=datetime(2026, 8, 1, 12, 0, 3, tzinfo=timezone.utc),
        finished_at_utc=datetime(2026, 8, 1, 12, 0, 4, tzinfo=timezone.utc),
        elapsed_monotonic_ns=1234,
    )

    return {
        "verification": verification,
        "authorization": authorization,
        "envelope": envelope,
        "request": request,
        "result": result,
    }
