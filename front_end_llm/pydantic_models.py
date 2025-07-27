#front_end_llm/pydantic_models.py

from typing import List, Dict
from pydantic import BaseModel

class AskInput(BaseModel):
    prompt: str
    history: List[Dict[str, str]]
    qa_items: List[Dict[str, str]]
