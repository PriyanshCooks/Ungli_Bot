#front_end_llm/utils.py

import os
import certifi
from typing import List, Dict, Optional
from pymongo import MongoClient
from datetime import datetime
import uuid

from fuzzywuzzy import fuzz

from front_end_llm.pydantic_models import AskInput
from front_end_llm.prompts import SYSTEM_PROMPT, RETRY_PROMPT_SUFFIX, NEXT_QUESTION_PROMPT
from front_end_llm.front_end_llm import _generate  # _generate is defined in front_end_llm.py


# --------------------
# Filtering Functions
# --------------------

forbidden_phrases = [
    "expected demand", "future demand", "market forecast", "how much future demand",
    "how much demand", "estimate future sales", "foresee any increase in demand",
    "market size", "current market size", "future market size"
]

def is_forbidden(question: str) -> bool:
    return any(phrase in question.lower() for phrase in forbidden_phrases)

def is_duplicate(question: str, qa_items: List[Dict], threshold=80) -> bool:
    for item in qa_items:
        if item["role"] == "assistant":
            similarity = fuzz.ratio(item["question"].lower(), question.lower())
            if similarity >= threshold:
                return True
    return False


# --------------------
# MongoDB Setup
# --------------------

MONGO_URL = os.getenv("MONGODB_URL")
if not MONGO_URL:
    raise RuntimeError("MONGO_URL not found in environment variables")

client = MongoClient(MONGO_URL, tlsCAFile=certifi.where())
db = client["chatbot_db"]
collection = db["chat_sessions"]


# --------------------
# Mongo Functions
# --------------------

def store_message(user_id: str, chat_id: str, question: str, answer: str, role: str = "user") -> None:
    message = {
        "question": question if role == "assistant" else "",
        "answer": answer if role == "user" else (answer if role == "system" else ""),
        "role": role,
        "timestamp": datetime.utcnow()
    }

    existing_doc = collection.find_one({"user_id": user_id})

    if existing_doc:
        if chat_id in existing_doc.get("chats", {}):
            collection.update_one(
                {"user_id": user_id},
                {"$push": {f"chats.{chat_id}.messages": message}}
            )
        else:
            collection.update_one(
                {"user_id": user_id},
                {"$set": {f"chats.{chat_id}": {"messages": [message]}}}
            )
    else:
        collection.insert_one({
            "user_id": user_id,
            "session_uuid": str(uuid.uuid4()),
            "chats": {
                chat_id: {
                    "messages": [message]
                }
            },
            "createdAt": datetime.utcnow()
        })


def get_chat_session(user_id: str, chat_id: str) -> Optional[List[Dict]]:
    doc = collection.find_one({"user_id": user_id}, {f"chats.{chat_id}.messages": 1})
    if not doc or "chats" not in doc or chat_id not in doc["chats"]:
        return None
    return doc["chats"][chat_id].get("messages", [])


def get_qa_history(user_id: str, chat_id: str) -> List[Dict]:
    session = get_chat_session(user_id, chat_id)
    session = session if session else []

    # 💡 Convert datetime to string here itself
    for item in session:
        if isinstance(item.get("timestamp"), datetime):
            item["timestamp"] = item["timestamp"].isoformat()

    return session


# --------------------
# GPT Agent Orchestration
# --------------------

def run_agent(input: AskInput) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(input.history)

    question = _generate(messages, temperature=0.7)

    if is_forbidden(question) or is_duplicate(question, input.qa_items):
        retry_prompt = SYSTEM_PROMPT + RETRY_PROMPT_SUFFIX
        retry_messages = [{"role": "system", "content": retry_prompt}]
        retry_messages.extend(input.history)

        question = _generate(retry_messages, temperature=0.3)

        if is_forbidden(question) or is_duplicate(question, input.qa_items):
            question = "Thank you. That’s all the questions we needed for now."

    return question


def generate_next_question(history: List[Dict[str, str]], qa_log: List[Dict[str, str]]) -> str:
    return run_agent(AskInput(
        prompt=NEXT_QUESTION_PROMPT,
        history=history,
        qa_items=qa_log
    ))


# --------------------
# Utility Function
# --------------------

def build_history(qa_items: List[Dict]) -> List[Dict[str, str]]:
    history = []
    for item in qa_items:
        if item["role"] == "assistant":
            history.append({"role": "assistant", "content": item["question"]})
        elif item["role"] == "user":
            history.append({"role": "user", "content": item["answer"]})
    return history
