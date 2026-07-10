import os
from typing import Set

from dotenv import load_dotenv


load_dotenv()


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int_set(value: str | None) -> Set[int]:
    if not value:
        return set()
    itens = set()
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            itens.add(int(item))
        except ValueError:
            return set()
    return itens

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_AUTHORIZED_IDS = _parse_int_set(os.getenv("TELEGRAM_AUTHORIZED_IDS"))

# APIs
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")

# Trading switches
TRADING_ENABLED = _parse_bool(os.getenv("TRADING_ENABLED"), False)
LIVE_TRADING_ENABLED = _parse_bool(os.getenv("LIVE_TRADING_ENABLED"), False)
GLOBAL_KILL_SWITCH = _parse_bool(os.getenv("GLOBAL_KILL_SWITCH"), True)

# Capital e risco
CAPITAL_REAL = 27.0
RISCO_PERCENTUAL_PADRAO = 0.5
ALAVANCAGEM_MAXIMA = 1
CAPITAL_PAPER = 10000.0

# Limites de seguranca
MAX_PERDA_DIARIA_PERCENTUAL = 2.0
MAX_PERDAS_CONSECUTIVAS = 3
MAX_TRADES_POR_DIA = 5
MAX_EXPOSICAO_PERCENTUAL = 80.0

# Operacao e paper
MODO_OPERACAO = "FUTUROS"
PAPER_TRADING_ATIVO = True
KILLZONE_BTC = True
KILLZONE_SOL = True

# Filtros
VOLUME_MINIMO = 1.5
FVG_JANELA = 5
RR_MINIMO = 1.5
DISTANCIA_MIN_PCT = 0.2
DISTANCIA_MAX_PCT = 10.0

# Versao
STRATEGY_VERSION = "v2_risk_safe"


def is_telegram_authorized(chat_id: int | None) -> bool:
    if chat_id is None:
        return False
    if not TELEGRAM_AUTHORIZED_IDS:
        return False
    return int(chat_id) in TELEGRAM_AUTHORIZED_IDS


def live_trading_permitted() -> bool:
    return bool(TRADING_ENABLED and LIVE_TRADING_ENABLED and not GLOBAL_KILL_SWITCH)


def validate_component_config(component: str) -> tuple[bool, list[str]]:
    component = (component or "").strip().lower()
    issues: list[str] = []

    if component in {"telegram", "bot", "bot_telegram"}:
        if not TELEGRAM_BOT_TOKEN:
            issues.append("TELEGRAM_BOT_TOKEN ausente ou invalido.")
        if not TELEGRAM_AUTHORIZED_IDS:
            issues.append("TELEGRAM_AUTHORIZED_IDS ausente; modo seguro ativo.")

    if component in {"ai", "ia", "groq"} and not GROQ_API_KEY:
        issues.append("GROQ_API_KEY ausente ou invalida.")

    if component in {"ai", "ia", "nvidia"} and not NVIDIA_API_KEY:
        issues.append("NVIDIA_API_KEY ausente ou invalida.")

    if component in {"live", "orders", "execution"} and not live_trading_permitted():
        issues.append("Operacao real bloqueada por configuracao segura.")

    return not issues, issues
