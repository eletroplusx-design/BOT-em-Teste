import pandas as pd

def tendencia_geral(df):
    """
    Calcula a Média Móvel Simples de 200 períodos (SMA 200)
    e compara com o último fechamento.
    Retorna uma string indicando tendência de alta ou baixa.
    """
    # Calcular SMA 200 sobre a coluna 'close'
    df["SMA200"] = df["close"].rolling(window=200).mean()
    ultima_sma = df["SMA200"].iloc[-1]
    preco_atual = df["close"].iloc[-1]

    if pd.isna(ultima_sma):
        return "Tendência: Dados insuficientes para SMA 200"

    if preco_atual > ultima_sma:
        return f"Tendência: ALTA (Acima da Média 200 – SMA: {ultima_sma:.2f})"
    else:
        return f"Tendência: BAIXA (Abaixo da Média 200 – SMA: {ultima_sma:.2f})"


def ultimos_swings(df):
    """
    Identifica o maior preço (topo) e o menor preço (fundo)
    nas últimas 50 velas.
    Retorna uma string formatada com esses valores.
    """
    janela = df.tail(50)
    if len(janela) < 1:
        return "Dados insuficientes para swings."

    topo = janela["high"].max()
    fundo = janela["low"].min()

    return f"Último Topo em {topo:.2f}, Último Fundo em {fundo:.2f}"