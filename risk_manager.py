def calcular_tamanho_posicao(capital, risco_percentual, entrada, stop):
    """
    Calcula tamanho da posição com base no capital, risco e distância do stop.

    Retorna:
        tuple[float, float]: (quantidade, valor_arriscado)
    """
    valor_arriscado = capital * (risco_percentual / 100)
    distancia_stop = abs(entrada - stop)

    if distancia_stop <= 0:
        return 0.0, valor_arriscado

    quantidade = valor_arriscado / distancia_stop
    return quantidade, valor_arriscado


def verificar_limite_diario(capital, perdas_hoje, max_perda_diaria_percentual=2):
    """
    Retorna True quando as perdas do dia ultrapassam o limite definido.
    """
    limite_diario = capital * (max_perda_diaria_percentual / 100)
    return perdas_hoje > limite_diario


def verificar_sequencia_perdas(historico, max_perdas_consecutivas=3):
    """
    Verifica se há uma sequência de perdas consecutivas no histórico.
    Aceita listas simples com strings como 'PERDA'/'GANHO' ou valores booleanos.
    """
    perdas_consecutivas = 0

    for item in reversed(list(historico)):
        is_perda = item in ("PERDA", "LOSS", False, 0)
        if is_perda:
            perdas_consecutivas += 1
            if perdas_consecutivas >= max_perdas_consecutivas:
                return True
        else:
            break

    return False
