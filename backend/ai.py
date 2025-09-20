# backend/ai.py
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

def get_client():
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
        default_headers={
            "HTTP-Referer": os.getenv("SITE_URL", "http://localhost:5173"),
            "X-Title": os.getenv("SITE_NAME", "SmartDocChecker")
        }
    )

def ask_model(system, user, model="openai/gpt-4o-mini"):
    client = get_client()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ]
    )
    return resp.choices[0].message.content
