#front_end_llm.py

import os
from openai import OpenAI
from dotenv import load_dotenv
from front_end_llm.pydantic_models import AskInput

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def _generate(messages, temperature=0.7):
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        max_tokens=150,
        temperature=temperature
    )
    return response.choices[0].message.content.strip()

def run_agent(input: AskInput) -> str:
    """Definition only — logic lives in utils.py"""
    pass
