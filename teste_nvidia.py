from openai import OpenAI
from config import NVIDIA_API_KEY

if not NVIDIA_API_KEY:
    raise RuntimeError("NVIDIA_API_KEY ausente no ambiente.")

client = OpenAI(
    api_key=NVIDIA_API_KEY,
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
