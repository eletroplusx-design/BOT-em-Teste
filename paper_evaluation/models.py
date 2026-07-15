from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping, Sequence

from domain.serialization import serialize_value

from .artifacts import paper_evaluation_hash
from .errors import (
    PaperEvaluationDecisionError,
    PaperEvaluationEvidenceError,
    PaperEvaluationManifestError,
    PaperEvaluationMetricsError,
    PaperEvaluationPolicyError,
)
from ._operational import _OPERATIONAL_BATCH_TOKEN, OperationalCohortContract


def _require_timezone_aware(dt: datetime, field_name: str) -> datetime:
    if not isinstance(dt, datetime):
        raise PaperEvaluationEvidenceError(f"{field_name} must be a datetime.")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise PaperEvaluationEvidenceError(f"{field_name} must be timezone-aware.")
    return dt.astimezone(timezone.utc)


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise PaperEvaluationEvidenceError(f"{field_name} must be a boolean.")
    return bool(value)


def _require_str(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise PaperEvaluationEvidenceError(f"{field_name} must be a string.")
    result = value.strip()
    if not result and not allow_empty:
        raise PaperEvaluationEvidenceError(f"{field_name} must be a non-empty string.")
    return result


def _require_int(value: Any, field_name: str, *, allow_zero: bool = True) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise PaperEvaluationEvidenceError(f"{field_name} must be an integer.")
    if allow_zero and value < 0:
        raise PaperEvaluationEvidenceError(f"{field_name} cannot be negative.")
    if not allow_zero and value <= 0:
        raise PaperEvaluationEvidenceError(f"{field_name} must be greater than zero.")
    return int(value)


def _require_decimal(value: Any, field_name: str, *, allow_zero: bool = True, allow_negative: bool = False) -> Decimal:
    if isinstance(value, Decimal):
        result = value
    else:
        try:
            result = Decimal(str(value))
        except Exception as exc:
            raise PaperEvaluationEvidenceError(f"{field_name} must be numeric.") from exc
    if not result.is_finite():
        raise PaperEvaluationEvidenceError(f"{field_name} must be finite.")
    if not allow_negative:
        if allow_zero:
            if result < 0:
                raise PaperEvaluationEvidenceError(f"{field_name} cannot be negative.")
        elif result <= 0:
            raise PaperEvaluationEvidenceError(f"{field_name} must be greater than zero.")
    return result


def _require_hash(value: Any, field_name: str) -> str:
    result = _require_str(value, field_name)
    if len(result) < 8:
        raise PaperEvaluationEvidenceError(f"{field_name} is invalid.")
    return result


def _normalize_decimal_mapping(value: Mapping[str, Any], field_name: str) -> dict[str, Decimal]:
    normalized: dict[str, Decimal] = {}
    for key, item in dict(value).items():
        key_text = str(key).strip()
        if not key_text:
            raise PaperEvaluationEvidenceError(f"{field_name} keys cannot be empty.")
        decimal = _require_decimal(item, f"{field_name}[{key_text}]")
        normalized[key_text] = decimal
    return normalized


def _normalize_regimes(regimes: Sequence[str] | None) -> tuple[str, ...]:
    if regimes is None:
        return ()
    normalized: list[str] = []
    for regime in regimes:
        value = str(regime).strip().upper()
        if not value:
            raise PaperEvaluationPolicyError("required_regimes cannot contain empty values.")
        if value not in normalized:
            normalized.append(value)
    return tuple(normalized)


class PaperEvaluationStatus(str, Enum):
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    REJECTED = "REJECTED"
    APPROVED_FOR_EXTENDED_PAPER = "APPROVED_FOR_EXTENDED_PAPER"


@dataclass(frozen=True, slots=True)
class PaperSessionSnapshotEvidence:
    snapshot_hash: str
    sequence: int
    timestamp_utc: datetime
    session_id: str
    session_started_utc: datetime
    session_state: str
    data_fresh: bool
    paper_capital_used: Decimal
    risk_per_trade_percent: Decimal
    session_drawdown_percent: Decimal
    current_loss_streak: int
    open_positions: int
    executed_trades: int
    observed_costs: dict[str, Any]
    attempted_live: bool
    internal_error: str | None = None
    result_status: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_hash", _require_hash(self.snapshot_hash, "snapshot_hash"))
        object.__setattr__(self, "sequence", _require_int(self.sequence, "sequence", allow_zero=False))
        object.__setattr__(self, "timestamp_utc", _require_timezone_aware(self.timestamp_utc, "timestamp_utc"))
        object.__setattr__(self, "session_id", _require_str(self.session_id, "session_id"))
        object.__setattr__(self, "session_started_utc", _require_timezone_aware(self.session_started_utc, "session_started_utc"))
        if self.session_started_utc > self.timestamp_utc:
            raise PaperEvaluationEvidenceError("session_started_utc cannot be after timestamp_utc.")
        session_state = str(self.session_state).strip().upper()
        if session_state not in {"CREATED", "RUNNING", "SUSPENDED", "COMPLETED", "FAILED"}:
            raise PaperEvaluationEvidenceError("session_state is invalid.")
        object.__setattr__(self, "session_state", session_state)
        object.__setattr__(self, "data_fresh", _require_bool(self.data_fresh, "data_fresh"))
        object.__setattr__(self, "paper_capital_used", _require_decimal(self.paper_capital_used, "paper_capital_used"))
        object.__setattr__(self, "risk_per_trade_percent", _require_decimal(self.risk_per_trade_percent, "risk_per_trade_percent"))
        object.__setattr__(self, "session_drawdown_percent", _require_decimal(self.session_drawdown_percent, "session_drawdown_percent"))
        object.__setattr__(self, "current_loss_streak", _require_int(self.current_loss_streak, "current_loss_streak", allow_zero=True))
        object.__setattr__(self, "open_positions", _require_int(self.open_positions, "open_positions", allow_zero=True))
        object.__setattr__(self, "executed_trades", _require_int(self.executed_trades, "executed_trades", allow_zero=True))
        object.__setattr__(self, "observed_costs", _normalize_decimal_mapping(self.observed_costs, "observed_costs"))
        object.__setattr__(self, "attempted_live", _require_bool(self.attempted_live, "attempted_live"))
        if self.internal_error is not None:
            object.__setattr__(self, "internal_error", str(self.internal_error).strip())
        if self.result_status is not None:
            object.__setattr__(self, "result_status", str(self.result_status).strip().upper())

    def as_hash_payload(self) -> dict[str, Any]:
        return {
            "snapshot_hash": self.snapshot_hash,
            "sequence": self.sequence,
            "timestamp_utc": self.timestamp_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "session_id": self.session_id,
            "session_started_utc": self.session_started_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "session_state": self.session_state,
            "data_fresh": self.data_fresh,
            "paper_capital_used": self.paper_capital_used,
            "risk_per_trade_percent": self.risk_per_trade_percent,
            "session_drawdown_percent": self.session_drawdown_percent,
            "current_loss_streak": self.current_loss_streak,
            "open_positions": self.open_positions,
            "executed_trades": self.executed_trades,
            "observed_costs": self.observed_costs,
            "attempted_live": self.attempted_live,
            "internal_error": self.internal_error,
            "result_status": self.result_status,
        }

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload())


@dataclass(frozen=True, slots=True)
class PaperSessionEventEvidence:
    event_id: str
    sequence: int
    event_type: str
    timestamp_utc: datetime
    session_id: str
    previous_hash: str
    content_hash: str
    event_hash: str
    result: str
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _require_hash(self.event_id, "event_id"))
        object.__setattr__(self, "sequence", _require_int(self.sequence, "sequence", allow_zero=False))
        object.__setattr__(self, "event_type", _require_str(self.event_type, "event_type"))
        object.__setattr__(self, "timestamp_utc", _require_timezone_aware(self.timestamp_utc, "timestamp_utc"))
        object.__setattr__(self, "session_id", _require_str(self.session_id, "session_id"))
        object.__setattr__(self, "previous_hash", _require_str(self.previous_hash, "previous_hash", allow_empty=True))
        object.__setattr__(self, "content_hash", _require_hash(self.content_hash, "content_hash"))
        object.__setattr__(self, "event_hash", _require_hash(self.event_hash, "event_hash"))
        object.__setattr__(self, "result", _require_str(self.result, "result"))
        object.__setattr__(self, "payload", dict(self.payload))

    def as_hash_payload(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "timestamp_utc": self.timestamp_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "session_id": self.session_id,
            "previous_hash": self.previous_hash,
            "content_hash": self.content_hash,
            "event_hash": self.event_hash,
            "result": self.result,
            "payload": self.payload,
        }

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload())


@dataclass(frozen=True, slots=True)
class PaperFillEvidence:
    trade_id: int
    session_id: str
    fill_side: str
    timestamp_utc: datetime
    price: Decimal
    quantity: Decimal
    fee: Decimal
    spread_cost: Decimal
    slippage_cost: Decimal
    is_real: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "trade_id", _require_int(self.trade_id, "trade_id", allow_zero=False))
        object.__setattr__(self, "session_id", _require_str(self.session_id, "session_id"))
        fill_side = _require_str(self.fill_side, "fill_side").upper()
        if fill_side not in {"ENTRY", "EXIT"}:
            raise PaperEvaluationEvidenceError("fill_side is invalid.")
        object.__setattr__(self, "fill_side", fill_side)
        object.__setattr__(self, "timestamp_utc", _require_timezone_aware(self.timestamp_utc, "timestamp_utc"))
        object.__setattr__(self, "price", _require_decimal(self.price, "price", allow_zero=False))
        object.__setattr__(self, "quantity", _require_decimal(self.quantity, "quantity", allow_zero=False))
        object.__setattr__(self, "fee", _require_decimal(self.fee, "fee"))
        object.__setattr__(self, "spread_cost", _require_decimal(self.spread_cost, "spread_cost"))
        object.__setattr__(self, "slippage_cost", _require_decimal(self.slippage_cost, "slippage_cost"))
        object.__setattr__(self, "is_real", _require_bool(self.is_real, "is_real"))
        if self.is_real:
            raise PaperEvaluationEvidenceError("real fills are not allowed in paper evaluation.")

    def as_hash_payload(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "session_id": self.session_id,
            "fill_side": self.fill_side,
            "timestamp_utc": self.timestamp_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "price": self.price,
            "quantity": self.quantity,
            "fee": self.fee,
            "spread_cost": self.spread_cost,
            "slippage_cost": self.slippage_cost,
            "is_real": self.is_real,
        }

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload())


@dataclass(frozen=True, slots=True)
class PaperSessionTradeEvidence:
    trade_id: int
    session_id: str
    symbol: str
    tipo: str
    status: str
    direcao: str
    entrada: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    quantidade: Decimal
    valor_arriscado: Decimal
    preco_base: Decimal | None
    fill_price: Decimal | None
    entry_fee: Decimal | None
    exit_fee: Decimal | None
    entry_spread_cost: Decimal | None
    entry_slippage_cost: Decimal | None
    exit_spread_cost: Decimal | None
    exit_slippage_cost: Decimal | None
    spread_cost: Decimal | None
    slippage_cost: Decimal | None
    pnl_bruto: Decimal | None
    custos_totais: Decimal | None
    pnl_liquido: Decimal | None
    aberto_em: datetime
    fechado_em: datetime | None = None
    saida: Decimal | None = None
    lucro_reais: Decimal | None = None
    lucro_percent: Decimal | None = None
    filtros_aplicados: bool = True
    idempotency_key: str | None = None
    close_idempotency_key: str | None = None
    close_idempotency_hash: str | None = None
    is_real: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "trade_id", _require_int(self.trade_id, "trade_id", allow_zero=False))
        object.__setattr__(self, "session_id", _require_str(self.session_id, "session_id"))
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol"))
        tipo = _require_str(self.tipo, "tipo").lower()
        status = _require_str(self.status, "status").lower()
        direcao = _require_str(self.direcao, "direcao").upper()
        if tipo != "paper":
            raise PaperEvaluationEvidenceError("only paper trades are allowed.")
        if status not in {"open", "closed"}:
            raise PaperEvaluationEvidenceError("trade status is invalid.")
        if direcao not in {"COMPRA", "VENDA"}:
            raise PaperEvaluationEvidenceError("trade direction is invalid.")
        object.__setattr__(self, "tipo", tipo)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "direcao", direcao)
        object.__setattr__(self, "entrada", _require_decimal(self.entrada, "entrada", allow_zero=False))
        object.__setattr__(self, "stop_loss", _require_decimal(self.stop_loss, "stop_loss", allow_zero=False))
        object.__setattr__(self, "take_profit", _require_decimal(self.take_profit, "take_profit", allow_zero=False))
        object.__setattr__(self, "quantidade", _require_decimal(self.quantidade, "quantidade", allow_zero=False))
        object.__setattr__(self, "valor_arriscado", _require_decimal(self.valor_arriscado, "valor_arriscado"))
        object.__setattr__(self, "preco_base", _require_decimal(self.preco_base, "preco_base") if self.preco_base is not None else None)
        object.__setattr__(self, "fill_price", _require_decimal(self.fill_price, "fill_price") if self.fill_price is not None else None)
        object.__setattr__(self, "entry_fee", _require_decimal(self.entry_fee, "entry_fee") if self.entry_fee is not None else None)
        object.__setattr__(self, "exit_fee", _require_decimal(self.exit_fee, "exit_fee") if self.exit_fee is not None else None)
        object.__setattr__(self, "entry_spread_cost", _require_decimal(self.entry_spread_cost, "entry_spread_cost") if self.entry_spread_cost is not None else None)
        object.__setattr__(self, "entry_slippage_cost", _require_decimal(self.entry_slippage_cost, "entry_slippage_cost") if self.entry_slippage_cost is not None else None)
        object.__setattr__(self, "exit_spread_cost", _require_decimal(self.exit_spread_cost, "exit_spread_cost") if self.exit_spread_cost is not None else None)
        object.__setattr__(self, "exit_slippage_cost", _require_decimal(self.exit_slippage_cost, "exit_slippage_cost") if self.exit_slippage_cost is not None else None)
        object.__setattr__(self, "spread_cost", _require_decimal(self.spread_cost, "spread_cost") if self.spread_cost is not None else None)
        object.__setattr__(self, "slippage_cost", _require_decimal(self.slippage_cost, "slippage_cost") if self.slippage_cost is not None else None)
        object.__setattr__(self, "pnl_bruto", _require_decimal(self.pnl_bruto, "pnl_bruto", allow_negative=True) if self.pnl_bruto is not None else None)
        object.__setattr__(self, "custos_totais", _require_decimal(self.custos_totais, "custos_totais") if self.custos_totais is not None else None)
        object.__setattr__(self, "pnl_liquido", _require_decimal(self.pnl_liquido, "pnl_liquido", allow_negative=True) if self.pnl_liquido is not None else None)
        object.__setattr__(self, "aberto_em", _require_timezone_aware(self.aberto_em, "aberto_em"))
        if self.fechado_em is not None:
            fechado_em = _require_timezone_aware(self.fechado_em, "fechado_em")
            if fechado_em < self.aberto_em:
                raise PaperEvaluationEvidenceError("fechado_em cannot be earlier than aberto_em.")
            object.__setattr__(self, "fechado_em", fechado_em)
        if self.saida is not None:
            object.__setattr__(self, "saida", _require_decimal(self.saida, "saida", allow_zero=False))
        if self.lucro_reais is not None:
            object.__setattr__(self, "lucro_reais", _require_decimal(self.lucro_reais, "lucro_reais", allow_negative=True))
        if self.lucro_percent is not None:
            object.__setattr__(self, "lucro_percent", _require_decimal(self.lucro_percent, "lucro_percent", allow_negative=True))
        object.__setattr__(self, "filtros_aplicados", _require_bool(self.filtros_aplicados, "filtros_aplicados"))
        if self.idempotency_key is not None:
            object.__setattr__(self, "idempotency_key", _require_str(self.idempotency_key, "idempotency_key"))
        if self.close_idempotency_key is not None:
            object.__setattr__(self, "close_idempotency_key", _require_str(self.close_idempotency_key, "close_idempotency_key"))
        if self.close_idempotency_hash is not None:
            object.__setattr__(self, "close_idempotency_hash", _require_hash(self.close_idempotency_hash, "close_idempotency_hash"))
        object.__setattr__(self, "is_real", _require_bool(self.is_real, "is_real"))
        if self.is_real:
            raise PaperEvaluationEvidenceError("real trades are not allowed in paper evaluation.")

    def is_closed(self) -> bool:
        return self.status == "closed"

    def as_hash_payload(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "session_id": self.session_id,
            "symbol": self.symbol,
            "tipo": self.tipo,
            "status": self.status,
            "direcao": self.direcao,
            "entrada": self.entrada,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "quantidade": self.quantidade,
            "valor_arriscado": self.valor_arriscado,
            "preco_base": self.preco_base,
            "fill_price": self.fill_price,
            "entry_fee": self.entry_fee,
            "exit_fee": self.exit_fee,
            "entry_spread_cost": self.entry_spread_cost,
            "entry_slippage_cost": self.entry_slippage_cost,
            "exit_spread_cost": self.exit_spread_cost,
            "exit_slippage_cost": self.exit_slippage_cost,
            "spread_cost": self.spread_cost,
            "slippage_cost": self.slippage_cost,
            "pnl_bruto": self.pnl_bruto,
            "custos_totais": self.custos_totais,
            "pnl_liquido": self.pnl_liquido,
            "aberto_em": self.aberto_em.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "fechado_em": self.fechado_em.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if self.fechado_em else None,
            "saida": self.saida,
            "lucro_reais": self.lucro_reais,
            "lucro_percent": self.lucro_percent,
            "filtros_aplicados": self.filtros_aplicados,
            "idempotency_key": self.idempotency_key,
            "close_idempotency_key": self.close_idempotency_key,
            "close_idempotency_hash": self.close_idempotency_hash,
            "is_real": self.is_real,
        }

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload())


@dataclass(frozen=True, slots=True)
class PaperSessionMetrics:
    session_id: str
    capital_initial: Decimal
    capital_final: Decimal
    gross_pnl: Decimal
    total_costs: Decimal
    net_pnl: Decimal
    net_return_percent: Decimal
    total_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate: Decimal
    expectancy: Decimal
    profit_factor: Decimal | None
    payoff: Decimal | None
    drawdown_max_percent: Decimal
    exposure_percent: Decimal
    duration_hours: Decimal
    max_simultaneous_positions: int
    max_loss_streak: int
    max_risk_per_trade_percent: Decimal
    capital_paper_max_used: Decimal
    spread_deviation_bps: Decimal
    slippage_deviation_bps: Decimal
    fee_deviation_percent: Decimal
    snapshot_count: int
    expired_data_cycles: int
    suspension_count: int
    suspension_reasons: tuple[str, ...]
    attempted_live_count: int
    internal_error_count: int
    regime_coverage: tuple[str, ...]
    trade_ids: tuple[int, ...] = ()
    fill_count: int = 0
    gross_profit: Decimal = Decimal("0")
    gross_loss: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _require_str(self.session_id, "session_id"))
        object.__setattr__(self, "capital_initial", _require_decimal(self.capital_initial, "capital_initial"))
        object.__setattr__(self, "capital_final", _require_decimal(self.capital_final, "capital_final"))
        object.__setattr__(self, "gross_pnl", _require_decimal(self.gross_pnl, "gross_pnl", allow_negative=True))
        object.__setattr__(self, "gross_profit", _require_decimal(self.gross_profit, "gross_profit"))
        object.__setattr__(self, "gross_loss", _require_decimal(self.gross_loss, "gross_loss"))
        object.__setattr__(self, "total_costs", _require_decimal(self.total_costs, "total_costs"))
        object.__setattr__(self, "net_pnl", _require_decimal(self.net_pnl, "net_pnl", allow_negative=True))
        object.__setattr__(self, "net_return_percent", _require_decimal(self.net_return_percent, "net_return_percent", allow_negative=True))
        object.__setattr__(self, "total_trades", _require_int(self.total_trades, "total_trades", allow_zero=True))
        object.__setattr__(self, "winning_trades", _require_int(self.winning_trades, "winning_trades", allow_zero=True))
        object.__setattr__(self, "losing_trades", _require_int(self.losing_trades, "losing_trades", allow_zero=True))
        object.__setattr__(self, "breakeven_trades", _require_int(self.breakeven_trades, "breakeven_trades", allow_zero=True))
        object.__setattr__(self, "win_rate", _require_decimal(self.win_rate, "win_rate"))
        object.__setattr__(self, "expectancy", _require_decimal(self.expectancy, "expectancy", allow_negative=True))
        if self.profit_factor is not None:
            object.__setattr__(self, "profit_factor", _require_decimal(self.profit_factor, "profit_factor", allow_zero=True))
        if self.payoff is not None:
            object.__setattr__(self, "payoff", _require_decimal(self.payoff, "payoff", allow_zero=True))
        object.__setattr__(self, "drawdown_max_percent", _require_decimal(self.drawdown_max_percent, "drawdown_max_percent"))
        object.__setattr__(self, "exposure_percent", _require_decimal(self.exposure_percent, "exposure_percent"))
        object.__setattr__(self, "duration_hours", _require_decimal(self.duration_hours, "duration_hours"))
        object.__setattr__(self, "max_simultaneous_positions", _require_int(self.max_simultaneous_positions, "max_simultaneous_positions", allow_zero=True))
        object.__setattr__(self, "max_loss_streak", _require_int(self.max_loss_streak, "max_loss_streak", allow_zero=True))
        object.__setattr__(self, "max_risk_per_trade_percent", _require_decimal(self.max_risk_per_trade_percent, "max_risk_per_trade_percent"))
        object.__setattr__(self, "capital_paper_max_used", _require_decimal(self.capital_paper_max_used, "capital_paper_max_used"))
        object.__setattr__(self, "spread_deviation_bps", _require_decimal(self.spread_deviation_bps, "spread_deviation_bps"))
        object.__setattr__(self, "slippage_deviation_bps", _require_decimal(self.slippage_deviation_bps, "slippage_deviation_bps"))
        object.__setattr__(self, "fee_deviation_percent", _require_decimal(self.fee_deviation_percent, "fee_deviation_percent"))
        object.__setattr__(self, "snapshot_count", _require_int(self.snapshot_count, "snapshot_count", allow_zero=True))
        object.__setattr__(self, "expired_data_cycles", _require_int(self.expired_data_cycles, "expired_data_cycles", allow_zero=True))
        object.__setattr__(self, "suspension_count", _require_int(self.suspension_count, "suspension_count", allow_zero=True))
        object.__setattr__(self, "suspension_reasons", tuple(_require_str(reason, "suspension_reason") for reason in self.suspension_reasons if str(reason).strip()))
        object.__setattr__(self, "attempted_live_count", _require_int(self.attempted_live_count, "attempted_live_count", allow_zero=True))
        object.__setattr__(self, "internal_error_count", _require_int(self.internal_error_count, "internal_error_count", allow_zero=True))
        object.__setattr__(self, "regime_coverage", tuple(str(item).strip().upper() for item in self.regime_coverage if str(item).strip()))
        object.__setattr__(self, "trade_ids", tuple(_require_int(item, "trade_id", allow_zero=False) for item in self.trade_ids))
        object.__setattr__(self, "fill_count", _require_int(self.fill_count, "fill_count", allow_zero=True))
        if self.capital_final != self.capital_initial + self.net_pnl:
            raise PaperEvaluationMetricsError("capital_final must equal capital_initial plus net_pnl.")
        if self.total_trades != self.winning_trades + self.losing_trades + self.breakeven_trades:
            raise PaperEvaluationMetricsError("trade counts are contradictory.")
        if self.gross_profit < 0 or self.gross_loss < 0:
            raise PaperEvaluationMetricsError("gross profit and loss must be non-negative.")
        if self.gross_pnl != self.gross_profit - self.gross_loss:
            raise PaperEvaluationMetricsError("gross_pnl must equal gross_profit minus gross_loss.")
        if self.total_trades == 0:
            if self.profit_factor is not None:
                raise PaperEvaluationMetricsError("profit_factor must be None when there are no trades.")
            if self.win_rate != Decimal("0") or self.expectancy != Decimal("0"):
                raise PaperEvaluationMetricsError("zero-trade metrics must be neutral.")
        if self.total_trades > 0 and self.profit_factor is not None and self.profit_factor < 0:
            raise PaperEvaluationMetricsError("profit_factor cannot be negative.")

    def as_hash_payload(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "capital_initial": self.capital_initial,
            "capital_final": self.capital_final,
            "gross_pnl": self.gross_pnl,
            "gross_profit": self.gross_profit,
            "gross_loss": self.gross_loss,
            "total_costs": self.total_costs,
            "net_pnl": self.net_pnl,
            "net_return_percent": self.net_return_percent,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "breakeven_trades": self.breakeven_trades,
            "win_rate": self.win_rate,
            "expectancy": self.expectancy,
            "profit_factor": self.profit_factor,
            "payoff": self.payoff,
            "drawdown_max_percent": self.drawdown_max_percent,
            "exposure_percent": self.exposure_percent,
            "duration_hours": self.duration_hours,
            "max_simultaneous_positions": self.max_simultaneous_positions,
            "max_loss_streak": self.max_loss_streak,
            "max_risk_per_trade_percent": self.max_risk_per_trade_percent,
            "capital_paper_max_used": self.capital_paper_max_used,
            "spread_deviation_bps": self.spread_deviation_bps,
            "slippage_deviation_bps": self.slippage_deviation_bps,
            "fee_deviation_percent": self.fee_deviation_percent,
            "snapshot_count": self.snapshot_count,
            "expired_data_cycles": self.expired_data_cycles,
            "suspension_count": self.suspension_count,
            "suspension_reasons": self.suspension_reasons,
            "attempted_live_count": self.attempted_live_count,
            "internal_error_count": self.internal_error_count,
            "regime_coverage": self.regime_coverage,
            "trade_ids": self.trade_ids,
            "fill_count": self.fill_count,
        }

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload())


@dataclass(frozen=True, slots=True)
class PaperEvaluationPolicy:
    min_sessions_completed: int = 1
    min_distinct_days: int = 1
    min_trades: int = 1
    min_duration_hours: Decimal = Decimal("1")
    max_drawdown_percent: Decimal = Decimal("25")
    min_profit_factor: Decimal = Decimal("1")
    min_expectancy: Decimal = Decimal("0")
    min_net_return_percent: Decimal = Decimal("0")
    max_total_costs_percent: Decimal = Decimal("10")
    max_suspended_sessions: int = 0
    require_zero_live_attempts: bool = True
    require_audit_chain: bool = True
    require_fresh_data: bool = True
    required_regimes: tuple[str, ...] = ("BULL", "BEAR", "CHOP")
    min_regime_coverage: int = 0
    evaluator_version: str = "v8_paper_evaluation"
    policy_hash: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "min_sessions_completed", _require_int(self.min_sessions_completed, "min_sessions_completed"))
        object.__setattr__(self, "min_distinct_days", _require_int(self.min_distinct_days, "min_distinct_days"))
        object.__setattr__(self, "min_trades", _require_int(self.min_trades, "min_trades", allow_zero=True))
        object.__setattr__(self, "min_duration_hours", _require_decimal(self.min_duration_hours, "min_duration_hours"))
        object.__setattr__(self, "max_drawdown_percent", _require_decimal(self.max_drawdown_percent, "max_drawdown_percent"))
        object.__setattr__(self, "min_profit_factor", _require_decimal(self.min_profit_factor, "min_profit_factor"))
        object.__setattr__(self, "min_expectancy", _require_decimal(self.min_expectancy, "min_expectancy", allow_negative=True))
        object.__setattr__(self, "min_net_return_percent", _require_decimal(self.min_net_return_percent, "min_net_return_percent", allow_negative=True))
        object.__setattr__(self, "max_total_costs_percent", _require_decimal(self.max_total_costs_percent, "max_total_costs_percent"))
        object.__setattr__(self, "max_suspended_sessions", _require_int(self.max_suspended_sessions, "max_suspended_sessions", allow_zero=True))
        if type(self.require_zero_live_attempts) is not bool:
            raise PaperEvaluationPolicyError("require_zero_live_attempts must be a boolean.")
        if type(self.require_audit_chain) is not bool:
            raise PaperEvaluationPolicyError("require_audit_chain must be a boolean.")
        if type(self.require_fresh_data) is not bool:
            raise PaperEvaluationPolicyError("require_fresh_data must be a boolean.")
        object.__setattr__(self, "require_zero_live_attempts", self.require_zero_live_attempts)
        object.__setattr__(self, "require_audit_chain", self.require_audit_chain)
        object.__setattr__(self, "require_fresh_data", self.require_fresh_data)
        object.__setattr__(self, "required_regimes", _normalize_regimes(self.required_regimes))
        object.__setattr__(self, "min_regime_coverage", _require_int(self.min_regime_coverage, "min_regime_coverage", allow_zero=True))
        object.__setattr__(self, "evaluator_version", _require_str(self.evaluator_version, "evaluator_version"))
        if self.policy_hash:
            object.__setattr__(self, "policy_hash", _require_hash(self.policy_hash, "policy_hash"))
        else:
            object.__setattr__(self, "policy_hash", paper_evaluation_hash(self.as_hash_payload(include_hash=False)))

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "min_sessions_completed": self.min_sessions_completed,
            "min_distinct_days": self.min_distinct_days,
            "min_trades": self.min_trades,
            "min_duration_hours": self.min_duration_hours,
            "max_drawdown_percent": self.max_drawdown_percent,
            "min_profit_factor": self.min_profit_factor,
            "min_expectancy": self.min_expectancy,
            "min_net_return_percent": self.min_net_return_percent,
            "max_total_costs_percent": self.max_total_costs_percent,
            "max_suspended_sessions": self.max_suspended_sessions,
            "require_zero_live_attempts": self.require_zero_live_attempts,
            "require_audit_chain": self.require_audit_chain,
            "require_fresh_data": self.require_fresh_data,
            "required_regimes": self.required_regimes,
            "min_regime_coverage": self.min_regime_coverage,
            "evaluator_version": self.evaluator_version,
        }
        if include_hash:
            payload["policy_hash"] = self.policy_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload())


@dataclass(frozen=True, slots=True)
class PaperEvaluationCohort:
    strategy_version: str
    period_start_utc: datetime
    period_end_utc: datetime
    inclusion_rule: str
    created_at_utc: datetime
    session_ids: tuple[str, ...]
    cohort_hash: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "strategy_version", _require_str(self.strategy_version, "strategy_version"))
        object.__setattr__(self, "period_start_utc", _require_timezone_aware(self.period_start_utc, "period_start_utc"))
        object.__setattr__(self, "period_end_utc", _require_timezone_aware(self.period_end_utc, "period_end_utc"))
        object.__setattr__(self, "created_at_utc", _require_timezone_aware(self.created_at_utc, "created_at_utc"))
        if self.period_end_utc < self.period_start_utc:
            raise PaperEvaluationManifestError("period_end_utc cannot be earlier than period_start_utc.")
        if self.created_at_utc > self.period_start_utc:
            raise PaperEvaluationManifestError("created_at_utc cannot be later than period_start_utc.")
        object.__setattr__(self, "inclusion_rule", _require_str(self.inclusion_rule, "inclusion_rule"))
        object.__setattr__(self, "session_ids", tuple(_require_str(session_id, "session_id") for session_id in self.session_ids))
        if len({session_id for session_id in self.session_ids}) != len(self.session_ids):
            raise PaperEvaluationManifestError("session_ids must not contain duplicates.")
        payload = self.as_hash_payload(include_hash=False)
        cohort_hash = self.cohort_hash or paper_evaluation_hash(payload)
        object.__setattr__(self, "cohort_hash", _require_hash(cohort_hash, "cohort_hash"))
        if self.cohort_hash != paper_evaluation_hash(payload):
            raise PaperEvaluationManifestError("cohort hash mismatch.")

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "strategy_version": self.strategy_version,
            "period_start_utc": self.period_start_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "period_end_utc": self.period_end_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "inclusion_rule": self.inclusion_rule,
            "created_at_utc": self.created_at_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "session_ids": self.session_ids,
        }
        if include_hash:
            payload["cohort_hash"] = self.cohort_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload())


@dataclass(frozen=True, slots=True)
class PaperSessionRejection:
    session_id: str
    reason: str
    evidence_hash: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _require_str(self.session_id, "session_id"))
        object.__setattr__(self, "reason", str(self.reason).strip())
        if not self.reason:
            raise PaperEvaluationEvidenceError("reason is required.")
        if self.evidence_hash is not None:
            object.__setattr__(self, "evidence_hash", _require_hash(self.evidence_hash, "evidence_hash"))

    def as_dict(self) -> dict[str, Any]:
        return serialize_value({"session_id": self.session_id, "reason": self.reason, "evidence_hash": self.evidence_hash})


@dataclass(frozen=True, slots=True)
class PaperEvaluationManifest:
    evaluation_id: str
    period_start_utc: datetime
    period_end_utc: datetime
    inclusion_rule: str
    synthetic_test_data: bool
    operational_evidence: bool
    session_ids: tuple[str, ...]
    session_hashes: tuple[tuple[str, str], ...]
    rejected_sessions: tuple[PaperSessionRejection, ...]
    policy_hash: str
    strategy_version: str
    evaluator_version: str
    walk_forward_hash: str | None = None
    session_count: int = 0
    cohort_hash: str | None = None
    manifest_hash: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if self.evaluation_id:
            object.__setattr__(self, "evaluation_id", _require_str(self.evaluation_id, "evaluation_id"))
        else:
            object.__setattr__(self, "evaluation_id", paper_evaluation_hash(self.as_hash_payload(include_hash=False, include_evaluation_id=False)))
        object.__setattr__(self, "period_start_utc", _require_timezone_aware(self.period_start_utc, "period_start_utc"))
        object.__setattr__(self, "period_end_utc", _require_timezone_aware(self.period_end_utc, "period_end_utc"))
        if self.period_end_utc < self.period_start_utc:
            raise PaperEvaluationManifestError("period_end_utc cannot be earlier than period_start_utc.")
        object.__setattr__(self, "inclusion_rule", _require_str(self.inclusion_rule, "inclusion_rule"))
        if type(self.synthetic_test_data) is not bool:
            raise PaperEvaluationManifestError("synthetic_test_data must be a boolean.")
        if type(self.operational_evidence) is not bool:
            raise PaperEvaluationManifestError("operational_evidence must be a boolean.")
        object.__setattr__(self, "synthetic_test_data", self.synthetic_test_data)
        object.__setattr__(self, "operational_evidence", self.operational_evidence)
        if self.cohort_hash is not None:
            object.__setattr__(self, "cohort_hash", _require_hash(self.cohort_hash, "cohort_hash"))
        object.__setattr__(self, "session_ids", tuple(_require_str(session_id, "session_id") for session_id in self.session_ids))
        object.__setattr__(self, "session_hashes", tuple(( _require_str(session_id, "session_id"), _require_hash(session_hash, "session_hash")) for session_id, session_hash in self.session_hashes))
        object.__setattr__(self, "rejected_sessions", tuple(self.rejected_sessions))
        object.__setattr__(self, "policy_hash", _require_hash(self.policy_hash, "policy_hash"))
        object.__setattr__(self, "strategy_version", _require_str(self.strategy_version, "strategy_version"))
        object.__setattr__(self, "evaluator_version", _require_str(self.evaluator_version, "evaluator_version"))
        if self.walk_forward_hash is not None:
            object.__setattr__(self, "walk_forward_hash", _require_hash(self.walk_forward_hash, "walk_forward_hash"))
        object.__setattr__(self, "session_count", _require_int(self.session_count, "session_count", allow_zero=True))
        if self.session_count != len(self.session_ids):
            raise PaperEvaluationManifestError("session_count must match session_ids length.")
        if len({session_id for session_id, _ in self.session_hashes}) != len(self.session_hashes):
            raise PaperEvaluationManifestError("session_hashes must not contain duplicate session_ids.")
        payload = self.as_hash_payload(include_hash=False)
        object.__setattr__(self, "manifest_hash", paper_evaluation_hash(payload) if not self.manifest_hash else _require_hash(self.manifest_hash, "manifest_hash"))
        if self.manifest_hash != paper_evaluation_hash(payload):
            raise PaperEvaluationManifestError("manifest hash mismatch.")

    def as_hash_payload(self, *, include_hash: bool = True, include_evaluation_id: bool = True) -> dict[str, Any]:
        payload = {
            "evaluation_id": self.evaluation_id if include_evaluation_id else None,
            "period_start_utc": self.period_start_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "period_end_utc": self.period_end_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "inclusion_rule": self.inclusion_rule,
            "synthetic_test_data": self.synthetic_test_data,
            "operational_evidence": self.operational_evidence,
            "cohort_hash": self.cohort_hash,
            "session_ids": self.session_ids,
            "session_hashes": self.session_hashes,
            "rejected_sessions": [rejection.as_dict() for rejection in self.rejected_sessions],
            "policy_hash": self.policy_hash,
            "strategy_version": self.strategy_version,
            "evaluator_version": self.evaluator_version,
            "walk_forward_hash": self.walk_forward_hash,
            "session_count": self.session_count,
        }
        if include_hash:
            payload["manifest_hash"] = self.manifest_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload())


@dataclass(frozen=True, slots=True)
class PaperEvaluationDecision:
    status: PaperEvaluationStatus
    policy_hash: str
    evidence_hash: str
    manifest_hash: str
    reasons: tuple[str, ...]
    evaluated_at_utc: datetime
    evaluator_version: str
    decision_hash: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", PaperEvaluationStatus(self.status))
        object.__setattr__(self, "policy_hash", _require_hash(self.policy_hash, "policy_hash"))
        object.__setattr__(self, "evidence_hash", _require_hash(self.evidence_hash, "evidence_hash"))
        object.__setattr__(self, "manifest_hash", _require_hash(self.manifest_hash, "manifest_hash"))
        object.__setattr__(self, "reasons", tuple(str(reason).strip() for reason in self.reasons if str(reason).strip()))
        object.__setattr__(self, "evaluated_at_utc", _require_timezone_aware(self.evaluated_at_utc, "evaluated_at_utc"))
        object.__setattr__(self, "evaluator_version", _require_str(self.evaluator_version, "evaluator_version"))
        payload = self.as_hash_payload(include_hash=False)
        decision_hash = self.decision_hash or paper_evaluation_hash(payload)
        object.__setattr__(self, "decision_hash", _require_hash(decision_hash, "decision_hash"))
        if self.decision_hash != paper_evaluation_hash(payload):
            raise PaperEvaluationDecisionError("decision hash mismatch.")

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "status": self.status.value,
            "policy_hash": self.policy_hash,
            "evidence_hash": self.evidence_hash,
            "manifest_hash": self.manifest_hash,
            "reasons": self.reasons,
            "evaluated_at_utc": self.evaluated_at_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "evaluator_version": self.evaluator_version,
        }
        if include_hash:
            payload["decision_hash"] = self.decision_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload())


@dataclass(frozen=True, slots=True)
class PaperSessionEvidence:
    session_id: str
    session_state: str
    session_started_utc: datetime
    session_updated_utc: datetime
    session_finished_utc: datetime | None
    decision_hash: str
    evidence_hash: str
    paper_limits_hash: str
    strategy_version: str
    symbol: str
    interval: str
    paper_only: bool
    contract_hash: str
    paper_limits: dict[str, Any]
    configuration: dict[str, Any]
    execution_contract: dict[str, Any]
    snapshots: tuple[PaperSessionSnapshotEvidence, ...]
    events: tuple[PaperSessionEventEvidence, ...]
    trades: tuple[PaperSessionTradeEvidence, ...]
    fills: tuple[PaperFillEvidence, ...]
    audit_chain_valid: bool
    attempted_live_count: int
    internal_error_count: int
    expired_data_cycles: int
    suspension_reasons: tuple[str, ...]
    regime_coverage: tuple[str, ...]
    observed_costs: dict[str, Decimal]
    session_hash: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _require_str(self.session_id, "session_id"))
        state = str(self.session_state).strip().upper()
        if state not in {"CREATED", "RUNNING", "SUSPENDED", "COMPLETED", "FAILED"}:
            raise PaperEvaluationEvidenceError("session_state is invalid.")
        object.__setattr__(self, "session_state", state)
        object.__setattr__(self, "session_started_utc", _require_timezone_aware(self.session_started_utc, "session_started_utc"))
        object.__setattr__(self, "session_updated_utc", _require_timezone_aware(self.session_updated_utc, "session_updated_utc"))
        if self.session_finished_utc is not None:
            finished = _require_timezone_aware(self.session_finished_utc, "session_finished_utc")
            if finished < self.session_started_utc:
                raise PaperEvaluationEvidenceError("session_finished_utc cannot be earlier than session_started_utc.")
            object.__setattr__(self, "session_finished_utc", finished)
        object.__setattr__(self, "decision_hash", _require_hash(self.decision_hash, "decision_hash"))
        object.__setattr__(self, "evidence_hash", _require_hash(self.evidence_hash, "evidence_hash"))
        object.__setattr__(self, "paper_limits_hash", _require_hash(self.paper_limits_hash, "paper_limits_hash"))
        object.__setattr__(self, "strategy_version", _require_str(self.strategy_version, "strategy_version"))
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol"))
        object.__setattr__(self, "interval", _require_str(self.interval, "interval"))
        object.__setattr__(self, "paper_only", _require_bool(self.paper_only, "paper_only"))
        if not self.paper_only:
            raise PaperEvaluationEvidenceError("paper_only must be true.")
        object.__setattr__(self, "contract_hash", _require_hash(self.contract_hash, "contract_hash"))
        object.__setattr__(self, "paper_limits", dict(self.paper_limits))
        object.__setattr__(self, "configuration", dict(self.configuration))
        object.__setattr__(self, "execution_contract", dict(self.execution_contract))
        object.__setattr__(self, "snapshots", tuple(self.snapshots))
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "trades", tuple(self.trades))
        object.__setattr__(self, "fills", tuple(self.fills))
        object.__setattr__(self, "audit_chain_valid", _require_bool(self.audit_chain_valid, "audit_chain_valid"))
        object.__setattr__(self, "attempted_live_count", _require_int(self.attempted_live_count, "attempted_live_count", allow_zero=True))
        object.__setattr__(self, "internal_error_count", _require_int(self.internal_error_count, "internal_error_count", allow_zero=True))
        object.__setattr__(self, "expired_data_cycles", _require_int(self.expired_data_cycles, "expired_data_cycles", allow_zero=True))
        object.__setattr__(self, "suspension_reasons", tuple(str(reason).strip() for reason in self.suspension_reasons if str(reason).strip()))
        object.__setattr__(self, "regime_coverage", tuple(str(item).strip().upper() for item in self.regime_coverage if str(item).strip()))
        object.__setattr__(self, "observed_costs", _normalize_decimal_mapping(self.observed_costs, "observed_costs"))
        if any(trade.session_id != self.session_id for trade in self.trades):
            raise PaperEvaluationEvidenceError("trade session mismatch.")
        if any(fill.session_id != self.session_id for fill in self.fills):
            raise PaperEvaluationEvidenceError("fill session mismatch.")
        if any(snapshot.session_id != self.session_id for snapshot in self.snapshots):
            raise PaperEvaluationEvidenceError("snapshot session mismatch.")
        if any(event.session_id != self.session_id for event in self.events):
            raise PaperEvaluationEvidenceError("event session mismatch.")
        if any(trade.is_real for trade in self.trades):
            raise PaperEvaluationEvidenceError("real trades are not allowed.")
        if any(fill.is_real for fill in self.fills):
            raise PaperEvaluationEvidenceError("real fills are not allowed.")
        payload = self.as_hash_payload(include_hash=False)
        session_hash = self.session_hash or paper_evaluation_hash(payload)
        object.__setattr__(self, "session_hash", _require_hash(session_hash, "session_hash"))
        if self.session_hash != paper_evaluation_hash(payload):
            raise PaperEvaluationEvidenceError("session hash mismatch.")

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "session_id": self.session_id,
            "session_state": self.session_state,
            "session_started_utc": self.session_started_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "session_updated_utc": self.session_updated_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "session_finished_utc": self.session_finished_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if self.session_finished_utc else None,
            "decision_hash": self.decision_hash,
            "evidence_hash": self.evidence_hash,
            "paper_limits_hash": self.paper_limits_hash,
            "strategy_version": self.strategy_version,
            "symbol": self.symbol,
            "interval": self.interval,
            "paper_only": self.paper_only,
            "contract_hash": self.contract_hash,
            "paper_limits": self.paper_limits,
            "configuration": self.configuration,
            "execution_contract": self.execution_contract,
            "snapshots": [snapshot.as_dict() for snapshot in self.snapshots],
            "events": [event.as_dict() for event in self.events],
            "trades": [trade.as_dict() for trade in self.trades],
            "fills": [fill.as_dict() for fill in self.fills],
            "audit_chain_valid": self.audit_chain_valid,
            "attempted_live_count": self.attempted_live_count,
            "internal_error_count": self.internal_error_count,
            "expired_data_cycles": self.expired_data_cycles,
            "suspension_reasons": self.suspension_reasons,
            "regime_coverage": self.regime_coverage,
            "observed_costs": self.observed_costs,
        }
        if include_hash:
            payload["session_hash"] = self.session_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload())
@dataclass(frozen=True, slots=True)
class _OperationalEvidenceBatch:
    contract: OperationalCohortContract
    cohort: PaperEvaluationCohort
    evidences: tuple[PaperSessionEvidence, ...]
    rejections: tuple[PaperSessionRejection, ...]
    batch_hash: str = field(default="", compare=False)
    _token: Any | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.contract, OperationalCohortContract):
            raise PaperEvaluationEvidenceError("contract must be an OperationalCohortContract instance.")
        if not isinstance(self.cohort, PaperEvaluationCohort):
            raise PaperEvaluationEvidenceError("cohort must be a PaperEvaluationCohort instance.")
        if self._token is not _OPERATIONAL_BATCH_TOKEN:
            raise PaperEvaluationEvidenceError("operational evidence batch token is invalid.")
        object.__setattr__(self, "evidences", tuple(self.evidences))
        object.__setattr__(self, "rejections", tuple(self.rejections))
        if any(not isinstance(evidence, PaperSessionEvidence) for evidence in self.evidences):
            raise PaperEvaluationEvidenceError("evidences must contain PaperSessionEvidence instances.")
        if any(not isinstance(rejection, PaperSessionRejection) for rejection in self.rejections):
            raise PaperEvaluationEvidenceError("rejections must contain PaperSessionRejection instances.")
        if len({evidence.session_id for evidence in self.evidences}) != len(self.evidences):
            raise PaperEvaluationEvidenceError("evidences must not contain duplicate session ids.")
        observed_ids = {evidence.session_id for evidence in self.evidences} | {rejection.session_id for rejection in self.rejections}
        if self.cohort.session_ids and observed_ids != set(self.cohort.session_ids):
            raise PaperEvaluationEvidenceError("batch session ids must match the cohort.")
        payload = self.as_hash_payload(include_hash=False)
        batch_hash = self.batch_hash or paper_evaluation_hash(payload)
        object.__setattr__(self, "batch_hash", _require_hash(batch_hash, "batch_hash"))
        if self.batch_hash != paper_evaluation_hash(payload):
            raise PaperEvaluationEvidenceError("operational batch hash mismatch.")

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "contract": self.contract.as_dict(),
            "cohort": self.cohort.as_dict(),
            "evidences": [evidence.as_dict() for evidence in self.evidences],
            "rejections": [rejection.as_dict() for rejection in self.rejections],
        }
        if include_hash:
            payload["batch_hash"] = self.batch_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload())


@dataclass(frozen=True, slots=True)
class PaperEvaluationReport:
    manifest: PaperEvaluationManifest
    policy: PaperEvaluationPolicy
    decision: PaperEvaluationDecision
    evaluation_id: str
    inclusion_rule: str
    synthetic_test_data: bool
    operational_evidence: bool
    accepted_sessions: tuple[PaperSessionEvidence, ...]
    rejected_sessions: tuple[PaperSessionRejection, ...]
    session_metrics: tuple[PaperSessionMetrics, ...]
    aggregate_metrics: PaperSessionMetrics
    walk_forward_comparison: dict[str, Any]
    residual_risks: tuple[str, ...]
    created_at_utc: datetime
    report_hash: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, PaperEvaluationManifest):
            raise PaperEvaluationManifestError("manifest must be a PaperEvaluationManifest instance.")
        if not isinstance(self.policy, PaperEvaluationPolicy):
            raise PaperEvaluationPolicyError("policy must be a PaperEvaluationPolicy instance.")
        if not isinstance(self.decision, PaperEvaluationDecision):
            raise PaperEvaluationDecisionError("decision must be a PaperEvaluationDecision instance.")
        object.__setattr__(self, "evaluation_id", _require_str(self.evaluation_id, "evaluation_id"))
        object.__setattr__(self, "inclusion_rule", _require_str(self.inclusion_rule, "inclusion_rule"))
        if type(self.synthetic_test_data) is not bool:
            raise PaperEvaluationManifestError("synthetic_test_data must be a boolean.")
        if type(self.operational_evidence) is not bool:
            raise PaperEvaluationManifestError("operational_evidence must be a boolean.")
        object.__setattr__(self, "synthetic_test_data", self.synthetic_test_data)
        object.__setattr__(self, "operational_evidence", self.operational_evidence)
        object.__setattr__(self, "accepted_sessions", tuple(self.accepted_sessions))
        object.__setattr__(self, "rejected_sessions", tuple(self.rejected_sessions))
        object.__setattr__(self, "session_metrics", tuple(self.session_metrics))
        object.__setattr__(self, "residual_risks", tuple(str(risk).strip() for risk in self.residual_risks if str(risk).strip()))
        object.__setattr__(self, "walk_forward_comparison", dict(self.walk_forward_comparison))
        object.__setattr__(self, "created_at_utc", _require_timezone_aware(self.created_at_utc, "created_at_utc"))
        payload = self.as_hash_payload(include_hash=False)
        report_hash = self.report_hash or paper_evaluation_hash(payload)
        object.__setattr__(self, "report_hash", _require_hash(report_hash, "report_hash"))
        if self.report_hash != paper_evaluation_hash(payload):
            raise PaperEvaluationManifestError("report hash mismatch.")

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "manifest": self.manifest.as_dict(),
            "policy": self.policy.as_dict(),
            "decision": self.decision.as_dict(),
            "evaluation_id": self.evaluation_id,
            "inclusion_rule": self.inclusion_rule,
            "synthetic_test_data": self.synthetic_test_data,
            "operational_evidence": self.operational_evidence,
            "accepted_sessions": [session.as_dict() for session in self.accepted_sessions],
            "rejected_sessions": [rejection.as_dict() for rejection in self.rejected_sessions],
            "session_metrics": [metric.as_dict() for metric in self.session_metrics],
            "aggregate_metrics": self.aggregate_metrics.as_dict(),
            "walk_forward_comparison": self.walk_forward_comparison,
            "residual_risks": self.residual_risks,
            "created_at_utc": self.created_at_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        if include_hash:
            payload["report_hash"] = self.report_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload())
