#pydantic_model.py

from pydantic import BaseModel
from typing import List, Dict, Optional, Any

class ConversationEntry(BaseModel):
    question: str
    answer: str

class ConversationLog(BaseModel):
    conversation: List[ConversationEntry]

class ExtractedData(BaseModel):
    company: str
    variable_data: Dict[str, Any]

class CompanyMatchOutput(BaseModel):
    company: str
    scoring_summary: str
    scores: Dict[str, Dict[str, Any]]
    reasoning: str
    final_score: float
