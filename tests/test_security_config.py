import config


def test_defaults_operacao_real_bloqueada():
    assert config.TRADING_ENABLED is False
    assert config.LIVE_TRADING_ENABLED is False
    assert config.GLOBAL_KILL_SWITCH is True
    assert config.live_trading_permitted() is False


def test_validacao_telegram_exige_lista_autorizada(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "token-teste")
    monkeypatch.setattr(config, "TELEGRAM_AUTHORIZED_IDS", set())

    valido, issues = config.validate_component_config("telegram")

    assert valido is False
    assert any("TELEGRAM_AUTHORIZED_IDS" in issue for issue in issues)
    assert config.is_telegram_authorized(123456) is False


def test_validacao_live_trading_bloqueada_por_padrao():
    valido, issues = config.validate_component_config("live")

    assert valido is False
    assert any("Operacao real bloqueada" in issue for issue in issues)
