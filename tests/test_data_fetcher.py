from unittest.mock import MagicMock

import pandas as pd
import requests

import data_fetcher


def test_baixar_dados_btc_retorna_dataframe(monkeypatch):
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = [
        [1704067200000, "60000", "60100", "59900", "60050", "100", 0, 0, 0, 0, 0, 0],
        [1704070800000, "60050", "60200", "60000", "60150", "110", 0, 0, 0, 0, 0, 0],
    ]
    mock_get = MagicMock(return_value=mock_response)
    monkeypatch.setattr(data_fetcher.requests, "get", mock_get)

    df = data_fetcher.baixar_dados_btc("BTCUSDT", "1h", 2)

    assert not df.empty
    assert list(df.columns) == ["datetime", "open", "high", "low", "close", "volume"]
    assert df.attrs["fonte_dados"] == "BINANCE"
    assert mock_get.call_args.kwargs["timeout"] == 10


def test_baixar_dados_btc_trata_erro(monkeypatch):
    monkeypatch.setattr(
        data_fetcher.requests,
        "get",
        MagicMock(side_effect=requests.exceptions.RequestException("boom")),
    )

    df = data_fetcher.baixar_dados_btc("BTCUSDT", "1h", 2)

    assert isinstance(df, pd.DataFrame)
    assert df.empty
