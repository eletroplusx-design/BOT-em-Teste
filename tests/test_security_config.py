import importlib
import itertools
import sys

import pytest


ENV_KEYS = [
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_AUTHORIZED_IDS",
    "TELEGRAM_AUTHORIZED_CHAT_IDS",
    "TELEGRAM_GROUPS_ENABLED",
    "GROQ_API_KEY",
    "NVIDIA_API_KEY",
    "TRADING_ENABLED",
    "LIVE_TRADING_ENABLED",
    "GLOBAL_KILL_SWITCH",
]


def _load_config(monkeypatch, **env):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    sys.modules.pop("config", None)
    return importlib.import_module("config")


def test_defaults_operacao_real_bloqueada(monkeypatch):
    config = _load_config(monkeypatch)
    assert config.TRADING_ENABLED is False
    assert config.LIVE_TRADING_ENABLED is False
    assert config.GLOBAL_KILL_SWITCH is True
    assert config.live_trading_permitted() is False


@pytest.mark.parametrize(
    "env_key, value, expected",
    [
        ("TRADING_ENABLED", "1", True),
        ("TRADING_ENABLED", "true", True),
        ("LIVE_TRADING_ENABLED", "yes", True),
        ("GLOBAL_KILL_SWITCH", "off", False),
        ("GLOBAL_KILL_SWITCH", "0", False),
    ],
)
def test_valores_verdadeiros_e_falsos_aceitos(monkeypatch, env_key, value, expected):
    config = _load_config(monkeypatch, **{env_key: value})
    assert getattr(config, env_key) is expected
    assert getattr(config, f"{env_key}_INVALID") is False


@pytest.mark.parametrize("bad_value", ["maybe", "   ", "?", "2"])
def test_valores_invalidos_e_vazios_fecham_seguro(monkeypatch, bad_value):
    config = _load_config(
        monkeypatch,
        TRADING_ENABLED=bad_value,
        LIVE_TRADING_ENABLED=bad_value,
        GLOBAL_KILL_SWITCH=bad_value,
        TELEGRAM_BOT_TOKEN="token-teste",
        TELEGRAM_AUTHORIZED_IDS="123",
    )

    assert config.TRADING_ENABLED is False
    assert config.LIVE_TRADING_ENABLED is False
    assert config.GLOBAL_KILL_SWITCH is True
    assert config.TRADING_ENABLED_INVALID is True
    assert config.LIVE_TRADING_ENABLED_INVALID is True
    assert config.GLOBAL_KILL_SWITCH_INVALID is True
    assert config.live_trading_permitted() is False

    valido, issues = config.validate_component_config("live")
    assert valido is False
    texto = " ".join(issues)
    assert bad_value not in texto
    assert "TRADING_ENABLED invalido" in texto
    assert "LIVE_TRADING_ENABLED invalido" in texto
    assert "GLOBAL_KILL_SWITCH invalido" in texto


@pytest.mark.parametrize(
    "trading, live, kill",
    list(itertools.product([False, True], repeat=3)),
)
def test_tabela_verdade_completa(monkeypatch, trading, live, kill):
    config = _load_config(
        monkeypatch,
        TRADING_ENABLED="true" if trading else "false",
        LIVE_TRADING_ENABLED="true" if live else "false",
        GLOBAL_KILL_SWITCH="true" if kill else "false",
        TELEGRAM_BOT_TOKEN="token-teste",
        TELEGRAM_AUTHORIZED_IDS="123",
    )

    assert config.TRADING_ENABLED is trading
    assert config.LIVE_TRADING_ENABLED is live
    assert config.GLOBAL_KILL_SWITCH is kill
    assert config.live_trading_permitted() is (trading and live and not kill)


def test_kill_switch_invalido_permanece_ligado(monkeypatch):
    config = _load_config(
        monkeypatch,
        GLOBAL_KILL_SWITCH="talvez",
        TELEGRAM_BOT_TOKEN="token-teste",
        TELEGRAM_AUTHORIZED_IDS="123",
        TRADING_ENABLED="true",
        LIVE_TRADING_ENABLED="true",
    )

    assert config.GLOBAL_KILL_SWITCH is True
    assert config.GLOBAL_KILL_SWITCH_INVALID is True
    assert config.live_trading_permitted() is False


def test_config_contraditoria_falha_de_forma_segura(monkeypatch):
    config = _load_config(
        monkeypatch,
        TRADING_ENABLED="true",
        LIVE_TRADING_ENABLED="true",
        GLOBAL_KILL_SWITCH="false",
        TELEGRAM_BOT_TOKEN="token-teste",
        TELEGRAM_AUTHORIZED_IDS="",
    )

    assert config.live_trading_permitted() is True
    valido, issues = config.validate_component_config("telegram")
    assert valido is False
    assert any("TELEGRAM_AUTHORIZED_IDS" in issue for issue in issues)
    assert config.is_telegram_user_authorized(123456) is False


def test_ausencia_de_credenciais_e_ids(monkeypatch):
    config = _load_config(
        monkeypatch,
        TELEGRAM_BOT_TOKEN="",
        GROQ_API_KEY="",
        NVIDIA_API_KEY="",
        TELEGRAM_AUTHORIZED_IDS="",
    )
    valido, issues = config.validate_component_config("telegram")
    assert valido is False
    assert any("TELEGRAM_BOT_TOKEN" in issue for issue in issues)
    assert any("TELEGRAM_AUTHORIZED_IDS" in issue for issue in issues)
    assert config.is_telegram_user_authorized(123456) is False

    valido_live, issues_live = config.validate_component_config("live")
    assert valido_live is False
    assert any("Operacao real bloqueada" in issue for issue in issues_live)


def test_segredos_nao_vazam_nas_mensagens(monkeypatch):
    secret = "token-super-secreto"
    config = _load_config(
        monkeypatch,
        TELEGRAM_BOT_TOKEN=secret,
        TELEGRAM_AUTHORIZED_IDS="abc",
        GROQ_API_KEY=secret,
        NVIDIA_API_KEY=secret,
        TRADING_ENABLED="maybe",
        LIVE_TRADING_ENABLED="maybe",
        GLOBAL_KILL_SWITCH="maybe",
    )

    _, issues = config.validate_component_config("telegram")
    texto = " ".join(issues)
    assert secret not in texto
    assert "abc" not in texto

    _, issues_live = config.validate_component_config("live")
    texto_live = " ".join(issues_live)
    assert secret not in texto_live
