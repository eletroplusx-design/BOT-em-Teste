from openai import OpenAI

from config import GROQ_API_KEY

# Base de conhecimento SMC (injeta no prompt da IA)
SMC_KNOWLEDGE = """
VOCÊ É UM ESPECIALISTA EM SMART MONEY CONCEPTS (SMC). SIGA RIGOROSAMENTE AS DEFINIÇÕES ABAIXO:

- Fair Value Gap (FVG): Lacuna de preço entre 3 velas consecutivas que não se sobrepõem. O preço sempre retorna para fechar o FVG (ímã).
  • Bullish FVG: preço abaixo → tende a subir para fechar.
  • Bearish FVG: preço acima → tende a cair para fechar.
- Order Block (OB): Última vela de impulso antes de uma mudança de estrutura (MSS/BoS). Zona de entrada de alta probabilidade.
- CISD (Change in State of Delivery): Quebra de topos/fundos ascendentes ou descendentes. Só opere na direção do CISD.
- Liquidity Sweep: Preço rompe topo/fundo recente para caçar stops. Após o sweep, o preço frequentemente reverte. Aguarde confirmação.
- Optimal Trade Entry (OTE): Zona entre 61.8% e 79.0% de retração de Fibonacci. O bot já calcula a zona de 61.8%. Incentive a esperar essa zona.
"""

def gerar_comentario_ia(dados_resumidos):
    """
    Gera um comentário SMC com IA. Se falhar, usa fallback automático.
    """
    if not GROQ_API_KEY:
        return gerar_comentario_fallback(dados_resumidos)

    try:
        client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=GROQ_API_KEY,
            timeout=30.0,
        )

        # Extrai valores
        preco = dados_resumidos.get('preco_atual', 'N/D')
        zona = dados_resumidos.get('zona_entrada_ideal', 'N/D')
        fvg = dados_resumidos.get('fvg', 'N/D')
        volume_status = dados_resumidos.get('volume_status', 'NEUTRO')
        veredito = dados_resumidos.get('veredito', 'AGUARDAR')
        tendencia = dados_resumidos.get('tendencia', '')
        regime = dados_resumidos.get('regime', '')

        # Prompt completo: persona + conhecimento SMC + dados + regras
        prompt = f"""
{SMC_KNOWLEDGE}

PERSONA: Você é um operador de mesa sênior que usa exclusivamente Smart Money Concepts. Fale diretamente com o trader Vitor.

DADOS EXATOS DA ANÁLISE:
- Preço Atual: {preco} USD
- Zona de Entrada Ideal (OTE 61.8%): {zona}
- Alvo (FVG): {fvg}
- Volume: {volume_status}
- Veredito do Bot: {veredito}
- Tendência: {tendencia}
- Regime: {regime}

REGRAS DE RESPOSTA:
1. Responda em EXATAMENTE 2 frases curtas.
2. Frase 1: Contexto + Ação (ex: "Vitor, preço 62.552, zona 60.962, alvo 62.578. Aguarde retração.")
3. Frase 2: Interpretação SMC (use os conceitos: FVG, Sweep, OTE, OB, CISD). Justifique a ação com base neles.
4. NÃO invente números. Use apenas os fornecidos.
5. Máximo 80 palavras no total.

EXEMPLO:
Vitor, preço 62.552, zona 60.962, alvo 62.578. Aguarde retração.
O FVG Bearish está atuando como ímã e o volume baixo sugere paciência. Espere o preço corrigir até a OTE para uma entrada mais segura.
"""

        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,          # um pouco mais de flexibilidade para interpretação
            max_tokens=150,
            top_p=0.9,
        )

        resposta = completion.choices[0].message.content.strip()

        # Validação
        if not resposta or len(resposta) > 350 or not any(c.isdigit() for c in resposta):
            return gerar_comentario_fallback(dados_resumidos)

        return f"🧠 IA: {resposta}"

    except Exception as e:
        print(f"Erro na IA (Groq): {e}")
        return gerar_comentario_fallback(dados_resumidos)


def gerar_comentario_fallback(dados):
    """
    Fallback automático com dados exatos, caso a IA falhe.
    """
    preco = dados.get('preco_atual', 'N/D')
    zona = dados.get('zona_entrada_ideal', 'N/D')
    fvg = dados.get('fvg', 'N/D')
    volume_status = dados.get('volume_status', 'NEUTRO')
    veredito = dados.get('veredito', 'AGUARDAR')

    if 'AGUARDAR RETRAÇÃO' in veredito or veredito == 'AGUARDAR':
        acao = f"preço {preco}, zona {zona}, alvo {fvg}. Aguarde retração."
    elif 'COMPRA' in veredito:
        acao = f"preço {preco}, zona {zona}, alvo {fvg}. Comprar."
    elif 'VENDA' in veredito:
        acao = f"preço {preco}, zona {zona}, alvo {fvg}. Vender."
    else:
        acao = f"preço {preco}, zona {zona}, alvo {fvg}. {veredito}."

    if volume_status == 'BAIXO':
        volume_msg = "Volume baixo indica falta de convicção. Aguarde aumento para confirmar."
    elif volume_status == 'ALTO':
        volume_msg = "Volume alto confirma a força do movimento."
    else:
        volume_msg = "Volume neutro, observe a ação do preço."

    return f"🧠 IA: Vitor, {acao} {volume_msg}"
