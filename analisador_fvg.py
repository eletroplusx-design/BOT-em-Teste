import pandas as pd

def identificar_fvg(df):
    """
    Analisa as últimas 50 velas em busca de Fair Value Gaps (FVG).
    
    Regras:
    - FVG Bullish (alta): low[i] > high[i-2]
    - FVG Bearish (baixa): high[i] < low[i-2]
    
    Retorna uma string com o último FVG encontrado e seus limites de preço,
    ou 'Nenhum FVG recente' se nada for detectado.
    """
    # Pegamos apenas as 50 velas mais recentes (últimas linhas)
    janela = df.tail(50).reset_index(drop=True)
    
    if len(janela) < 3:
        return "Dados insuficientes para análise de FVG (mínimo 3 velas)."

    ultimo_fvg = None
    tipo = None

    # Percorre a janela a partir da terceira vela (índice 2)
    for i in range(2, len(janela)):
        low_i = janela.loc[i, "low"]
        high_i = janela.loc[i, "high"]
        high_i_2 = janela.loc[i-2, "high"]
        low_i_2 = janela.loc[i-2, "low"]

        # Bullish FVG
        if low_i > high_i_2:
            ultimo_fvg = (high_i_2, low_i)  # gap entre high[i-2] e low[i]
            tipo = "Bullish"
        
        # Bearish FVG
        elif high_i < low_i_2:
            ultimo_fvg = (high_i, low_i_2)  # gap entre high[i] e low[i-2]
            tipo = "Bearish"

    if ultimo_fvg is None:
        return "Nenhum FVG recente"
    else:
        return f"Último FVG {tipo} encontrado entre {ultimo_fvg[0]:.2f} e {ultimo_fvg[1]:.2f}"