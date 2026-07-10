import risk_manager


def _fake_exchange_info():
    return {
        "step_size": 0.001,
        "min_qty": 0.001,
        "max_qty": 1000,
        "tick_size": 0.01,
        "min_price": 0.01,
        "max_price": 1000000,
        "min_notional": 10.0,
        "price_precision": 2,
        "quantity_precision": 3,
        "exchange_info_ok": True,
    }


def test_calculo_quantidade_correta(monkeypatch):
    monkeypatch.setattr(risk_manager, "_buscar_exchange_info", lambda symbol, force_refresh=False: _fake_exchange_info())
    resultado = risk_manager.calcular_posicao(
        capital=10000,
        risco_pct=1.0,
        entrada=100,
        stop=95,
        symbol="BTCUSDT",
        alavancagem=1,
    )
    assert resultado["aprovado"] is True
    assert resultado["quantidade"] == 20.0
    assert resultado["valor_arriscado"] == 100.0
    assert resultado["valor_nocional"] == 2000.0


def test_alavancagem_nao_multiplica_risco(monkeypatch):
    monkeypatch.setattr(risk_manager, "_buscar_exchange_info", lambda symbol, force_refresh=False: _fake_exchange_info())
    sem_alavancagem = risk_manager.calcular_posicao(
        capital=10000,
        risco_pct=1.0,
        entrada=100,
        stop=95,
        symbol="BTCUSDT",
        alavancagem=1,
    )
    com_alavancagem = risk_manager.calcular_posicao(
        capital=10000,
        risco_pct=1.0,
        entrada=100,
        stop=95,
        symbol="BTCUSDT",
        alavancagem=10,
    )
    assert sem_alavancagem["quantidade"] == com_alavancagem["quantidade"]
    assert com_alavancagem["margem_necessaria"] == sem_alavancagem["valor_nocional"] / 10


def test_bloqueio_distancia_zero(monkeypatch):
    monkeypatch.setattr(risk_manager, "_buscar_exchange_info", lambda symbol, force_refresh=False: _fake_exchange_info())
    resultado = risk_manager.calcular_posicao(capital=10000, risco_pct=1.0, entrada=100, stop=100)
    assert resultado["aprovado"] is False
    assert "zero" in resultado["motivo"].lower()


def test_bloqueio_quantidade_minima(monkeypatch):
    monkeypatch.setattr(
        risk_manager,
        "_buscar_exchange_info",
        lambda symbol, force_refresh=False: {
            "step_size": 0.001,
            "min_qty": 1000.0,
            "max_qty": 1000000,
            "tick_size": 0.01,
            "min_price": 0.01,
            "max_price": 1000000,
            "min_notional": 10.0,
            "price_precision": 2,
            "quantity_precision": 3,
            "exchange_info_ok": True,
        },
    )
    resultado = risk_manager.calcular_posicao(capital=10000, risco_pct=1.0, entrada=100, stop=95, symbol="BTCUSDT")
    assert resultado["aprovado"] is False
    assert "abaixo" in resultado["motivo"].lower()


def test_arredondamento_step_size(monkeypatch):
    monkeypatch.setattr(
        risk_manager,
        "_buscar_exchange_info",
        lambda symbol, force_refresh=False: {
            "step_size": 0.1,
            "min_qty": 0.1,
            "max_qty": 1000,
            "tick_size": 0.01,
            "min_price": 0.01,
            "max_price": 1000000,
            "min_notional": 10.0,
            "price_precision": 2,
            "quantity_precision": 3,
            "exchange_info_ok": True,
        },
    )
    resultado = risk_manager.calcular_posicao(capital=10000, risco_pct=1.0, entrada=100, stop=95, symbol="BTCUSDT")
    assert resultado["quantidade"] == 20.0


def test_bloqueio_perda_diaria(monkeypatch):
    monkeypatch.setattr(risk_manager, "_buscar_exchange_info", lambda symbol, force_refresh=False: _fake_exchange_info())
    resultado = risk_manager.calcular_posicao(
        capital=10000,
        risco_pct=1.0,
        entrada=100,
        stop=95,
        perdas_hoje=300,
    )
    assert resultado["aprovado"] is False
    assert "di" in resultado["motivo"].lower()


def test_bloqueio_sequencia_perdas(monkeypatch):
    monkeypatch.setattr(risk_manager, "_buscar_exchange_info", lambda symbol, force_refresh=False: _fake_exchange_info())
    resultado = risk_manager.calcular_posicao(
        capital=10000,
        risco_pct=1.0,
        entrada=100,
        stop=95,
        perdas_consecutivas=3,
    )
    assert resultado["aprovado"] is False
    assert "sequ" in resultado["motivo"].lower()


def test_bloqueio_exchange_info_invalida(monkeypatch):
    monkeypatch.setattr(
        risk_manager,
        "_buscar_exchange_info",
        lambda symbol, force_refresh=False: {
            "step_size": 0.001,
            "min_qty": 0.001,
            "max_qty": 1000,
            "tick_size": 0.01,
            "min_price": 0.01,
            "max_price": 1000000,
            "min_notional": 10.0,
            "price_precision": 2,
            "quantity_precision": 3,
            "exchange_info_ok": False,
        },
    )
    resultado = risk_manager.calcular_posicao(capital=10000, risco_pct=1.0, entrada=100, stop=95, symbol="BTCUSDT")
    assert resultado["aprovado"] is False
    assert "exchange" in resultado["motivo"].lower()
