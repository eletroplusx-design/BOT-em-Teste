import pandas as pd
from data_fetcher import baixar_dados_btc
from analisador_fvg import identificar_fvg
from analisador_contexto import tendencia_geral, ultimos_swings

def calcular_atr(df, periodo=14):
    """
    Calcula o Average True Range (ATR) para o DataFrame.
    Colunas esperadas: 'high', 'low', 'close'.
    """
    max_min = df["high"] - df["low"]
    max_fechamento_anterior = abs(df["high"] - df["close"].shift(1))
    min_fechamento_anterior = abs(df["low"] - df["close"].shift(1))

    true_range = pd.concat([max_min, max_fechamento_anterior, min_fechamento_anterior], axis=1).max(axis=1)
    atr = true_range.rolling(window=periodo).mean()
    return atr

def main():
    print("⬇️  Baixando dados do BTC/USDT (últimas 100 velas de 1 hora)...")
    df = baixar_dados_btc()

    if df.empty:
        print("Não foi possível obter os dados. Encerrando.")
        return

    # Último candle
    ultimo = df.iloc[-1]
    preco_atual = ultimo["close"]
    volume = ultimo["volume"]

    # Calcular ATR(14)
    df["ATR"] = calcular_atr(df, periodo=14)
    atr_atual = df["ATR"].iloc[-1]

    # Análises adicionais
    resultado_fvg = identificar_fvg(df)
    resultado_tendencia = tendencia_geral(df)
    resultado_swings = ultimos_swings(df)

    # Exibição unificada na ordem solicitada
    print("📊 Análise do BTC: "
          f"Preço Atual: {preco_atual:.2f}, "
          f"ATR(14): {atr_atual:.2f}, "
          f"Volume: {volume:.2f}")
    print(resultado_tendencia)
    print(resultado_swings)
    print(resultado_fvg)

if __name__ == "__main__":
    main()