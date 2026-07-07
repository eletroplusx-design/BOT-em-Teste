from openai import OpenAI

client = OpenAI(
    api_key="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",
    base_url="https://integrate.api.nvidia.com/v1"
)

try:
    completion = client.chat.completions.create(
        model="deepseek-ai/deepseek-v4-flash",
        messages=[{"role": "user", "content": "O que é um Fair Value Gap?"}],
        max_tokens=200,
        temperature=0.5
    )
    print(completion.choices[0].message.content)
except Exception as e:
    print(f"Erro: {e}")