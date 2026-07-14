import os
from typing import Set

from dotenv import load_dotenv


load_dotenv()


TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


def _parse_bool(value: str | None, default: bool = False) -> tuple[bool, bool]:
    if value is None:
        return default, False

    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True, False
    if normalized in FALSE_VALUES:
        return False, False
    return default, True


def _parse_int_set(value: str | None) -> tuple[Set[int], bool]:
    if value is None:
        return set(), False

    if not value.strip():
        return set(), True

    itens = set()
    for item in value.split(","):
        item = item.strip()
        if not item:
            return set(), True
        try:
            itens.add(int(item))
        except ValueError:
            return set(), True
    return itens, False

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_AUTHORIZED_IDS, TELEGRAM_AUTHORIZED_IDS_INVALID = _parse_int_set(os.getenv("TELEGRAM_AUTHORIZED_IDS"))
TELEGRAM_AUTHORIZED_CHAT_IDS, TELEGRAM_AUTHORIZED_CHAT_IDS_INVALID = _parse_int_set(
    os.getenv("TELEGRAM_AUTHORIZED_CHAT_IDS")
)
TELEGRAM_GROUPS_ENABLED, TELEGRAM_GROUPS_ENABLED_INVALID = _parse_bool(
    os.getenv("TELEGRAM_GROUPS_ENABLED"), False
)

# APIs
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Trading switches
TRADING_ENABLED, TRADING_ENABLED_INVALID = _parse_bool(os.getenv("TRADING_ENABLED"), False)
LIVE_TRADING_ENABLED, LIVE_TRADING_ENABLED_INVALID = _parse_bool(os.getenv("LIVE_TRADING_ENABLED"), False)
GLOBAL_KILL_SWITCH, GLOBAL_KILL_SWITCH_INVALID = _parse_bool(os.getenv("GLOBAL_KILL_SWITCH"), True)

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
PAPER_MONITORED_RUNTIME_REQUIRED = True
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
    return is_telegram_user_authorized(chat_id)


def is_telegram_user_authorized(user_id: int | None) -> bool:
    if user_id is None:
        return False
    if not TELEGRAM_AUTHORIZED_IDS or TELEGRAM_AUTHORIZED_IDS_INVALID:
        return False
    return int(user_id) in TELEGRAM_AUTHORIZED_IDS


def is_telegram_chat_authorized(chat_id: int | None) -> bool:
    if chat_id is None:
        return False
    if not TELEGRAM_AUTHORIZED_CHAT_IDS or TELEGRAM_AUTHORIZED_CHAT_IDS_INVALID:
        return False
    return int(chat_id) in TELEGRAM_AUTHORIZED_CHAT_IDS


def can_execute_sensitive_telegram_action(
    user_id: int | None,
    chat_id: int | None = None,
    chat_type: str | None = None,
) -> bool:
    if not is_telegram_user_authorized(user_id):
        return False
    if chat_type is None:
        return False

    normalized_chat_type = str(chat_type).strip().lower()
    if not normalized_chat_type:
        return False
    if normalized_chat_type == "private":
        return True
    if normalized_chat_type not in {"group", "supergroup"}:
        return False
    if not TELEGRAM_GROUPS_ENABLED or TELEGRAM_GROUPS_ENABLED_INVALID:
        return False
    if not is_telegram_chat_authorized(chat_id):
        return False
    return True


def live_trading_permitted() -> bool:
    if TRADING_ENABLED_INVALID or LIVE_TRADING_ENABLED_INVALID or GLOBAL_KILL_SWITCH_INVALID:
        return False
    return bool(TRADING_ENABLED and LIVE_TRADING_ENABLED and not GLOBAL_KILL_SWITCH)


def validate_component_config(component: str) -> tuple[bool, list[str]]:
    component = (component or "").strip().lower()
    issues: list[str] = []

    if component in {"telegram", "bot", "bot_telegram"}:
        if not TELEGRAM_BOT_TOKEN:
            issues.append("TELEGRAM_BOT_TOKEN ausente ou invalido.")
        if TELEGRAM_AUTHORIZED_IDS_INVALID:
            issues.append("TELEGRAM_AUTHORIZED_IDS invalido; modo seguro ativo.")
        elif not TELEGRAM_AUTHORIZED_IDS:
            issues.append("TELEGRAM_AUTHORIZED_IDS ausente; modo seguro ativo.")
        if TELEGRAM_AUTHORIZED_CHAT_IDS_INVALID:
            issues.append("TELEGRAM_AUTHORIZED_CHAT_IDS invalido.")
        if TELEGRAM_GROUPS_ENABLED_INVALID:
            issues.append("TELEGRAM_GROUPS_ENABLED invalido.")

    if component in {"ai", "ia", "groq"} and not GROQ_API_KEY:
        issues.append("GROQ_API_KEY ausente ou invalida.")

    if component in {"live", "orders", "execution"}:
        if TRADING_ENABLED_INVALID:
            issues.append("TRADING_ENABLED invalido.")
        if LIVE_TRADING_ENABLED_INVALID:
            issues.append("LIVE_TRADING_ENABLED invalido.")
        if GLOBAL_KILL_SWITCH_INVALID:
            issues.append("GLOBAL_KILL_SWITCH invalido.")
        if not live_trading_permitted():
            issues.append("Operacao real bloqueada por configuracao segura.")

    return not issues, issues
