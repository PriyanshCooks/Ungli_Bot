# supervisor/utils.py
import openpyxl
import logging
import os
import json
import httpx
from dotenv import load_dotenv
from typing import Dict, Any, List
from pymongo import MongoClient
from .pydantic_model import ConversationLog, ExtractedData, ConversationEntry
import tiktoken

load_dotenv()

def get_mongo_client():
    return MongoClient(os.getenv("MONGODB_URL"))

def fetch_company_profile(user_id: str, chat_id: str, session_uuid: str) -> Dict[str, Any]:
    client = get_mongo_client()
    db = client[os.getenv("READ_MONGO_DB")]
    collection = db[os.getenv("READ_MONGO_COLLECTION")]
    doc = collection.find_one({
        "user_id": user_id,
        "session_uuid": session_uuid
    })
    chat_data = doc.get("chats", {}).get(chat_id, {}) if doc else {}
    return {
        "company_profile": chat_data.get("company_profile", ""),
        "company_website": chat_data.get("company_website", "")
    }

def fetch_chat_as_conversationlog(user_id: str, chat_id: str, session_uuid: str) -> ConversationLog:
    client = get_mongo_client()
    db = client[os.getenv("READ_MONGO_DB")]
    collection = db[os.getenv("READ_MONGO_COLLECTION")]
    doc = collection.find_one({
        "user_id": user_id,
        "session_uuid": session_uuid
    })
    if not doc:
        raise ValueError("No valid session found in MongoDB.")
    chat_data = doc.get("chats", {}).get(chat_id, {})
    raw_messages = chat_data.get("messages", [])
    messages = []
    for m in raw_messages:
        role = m.get("role")
        if role not in {"user", "assistant"}:
            continue
        question = m.get("question", "") if role == "assistant" else ""
        answer = m.get("answer", "") if role == "user" else ""
        messages.append(ConversationEntry(question=question, answer=answer))
    return ConversationLog(conversation=messages)

def convert_conversationlog_to_chatml(conv_log: ConversationLog) -> List[Dict[str, str]]:
    messages = []
    for entry in conv_log.conversation:
        if entry.question:
            messages.append({"role": "user", "content": entry.question})
        if entry.answer:
            messages.append({"role": "assistant", "content": entry.answer})
    return messages

def sanitize_filename(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in "-_ ").rstrip()

def save_output_locally(data_obj, folder="final_structured_output"):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{sanitize_filename(data_obj.company.lower())}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data_obj.dict(), f, indent=2, ensure_ascii=False)

def count_tokens(messages, model="gpt-3.5-turbo"):
    # Use fallback encoding "cl100k_base" for unknown models like sonar-pro
    if model in ["sonar-pro", "sonar-small", "sonar-medium"]:
        enc = tiktoken.get_encoding("cl100k_base")
    else:
        try:
            enc = tiktoken.encoding_for_model(model)
        except KeyError:
            enc = tiktoken.get_encoding("cl100k_base")
    text = ""
    for m in messages:
        text += m["content"] + " "
    return len(enc.encode(text))

async def call_perplexity(messages: List[Dict[str, str]]) -> tuple:
    headers = {
        "Authorization": f"Bearer {os.getenv('PERPLEXITY_API_KEY')}",
        "Content-Type": "application/json"
    }
    model = os.getenv("PERPLEXITY_MODEL", "sonar-pro")
    payload = {"model": model, "messages": messages}
    input_tokens = count_tokens(messages, model)
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post("https://api.perplexity.ai/chat/completions", headers=headers, json=payload)
        response.raise_for_status()
        output = response.json()["choices"][0]["message"]["content"]
        # Estimate output tokens using same fallback logic as input tokens
        if model in ["sonar-pro", "sonar-small", "sonar-medium"]:
            enc = tiktoken.get_encoding("cl100k_base")
        else:
            try:
                enc = tiktoken.encoding_for_model(model)
            except KeyError:
                enc = tiktoken.get_encoding("cl100k_base")
        output_tokens = len(enc.encode(output))
        return output, input_tokens, output_tokens


    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post("https://api.perplexity.ai/chat/completions", headers=headers, json=payload)
        response.raise_for_status()
        output = response.json()["choices"][0]["message"]["content"]

        try:
            enc = tiktoken.encoding_for_model(model)
        except KeyError:
            enc = tiktoken.get_encoding("cl100k_base")
        output_tokens = len(enc.encode(output))

        return output, input_tokens, output_tokens

def fetch_companies_from_applications(user_id: str, chat_id: str, session_uuid: str) -> List[Dict[str, Any]]:
    client = get_mongo_client()
    db = client[os.getenv("WRITE_MONGO_DB_NAME")]
    collection = db[os.getenv("WRITE_MONGO_COLLECTION_NAME")]
    doc = collection.find_one({
        "user_id": user_id,
        "session_uuid": session_uuid,
        f"chats.{chat_id}": {"$exists": True}
    })
    if not doc:
        logging.warning(f"⚠️ No document found for session_uuid={session_uuid}")
        return []
    chat_data = doc.get("chats", {}).get(chat_id, {})
    companies = []
    for entry in chat_data.get("output", []):
        companies.extend(entry.get("companies", []))
    logging.info(f"✅ Retrieved {len(companies)} companies from DB")
    return companies

def ranked_companies_to_excel(md_path, xlsx_path):
    with open(md_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['Rank', 'Company', 'Final Score', 'Reasoning', 'Address', 'Phone'])
    rank = 0
    current = {}
    for line in lines:
        line = line.strip()
        if line.startswith("## "):  # Company header
            if current:
                ws.append([current.get('Rank'), current.get('Company'), current.get('Score'), current.get('Reasoning'), current.get('Address'), current.get('Phone')])
            rank += 1
            current = {'Rank': rank, 'Company': line[3:]}
        elif line.startswith("- **Final Score**:"):
            current['Score'] = line.split(": ", 1)[1]
        elif line.startswith("- **Reasoning**:"):
            current['Reasoning'] = line.split(": ", 1)[1]
        elif line.startswith("- **Address**:"):
            current['Address'] = line.split(": ", 1)[1]
        elif line.startswith("- **Phone**:"):
            current['Phone'] = line.split(": ", 1)[1]
    if current:
        ws.append([current.get('Rank'), current.get('Company'), current.get('Score'), current.get('Reasoning'), current.get('Address'), current.get('Phone')])
    wb.save(xlsx_path)

# -------- MONGODB SUPERVISOR/BOT LOGGING UTILITY --------

from datetime import datetime

SUPERVISOR_LOG_MONGODB_URL = "mongodb+srv://ayushsinghbasera:YEJTg3zhMwXJcTXm@cluster0.fmzrdga.mongodb.net/"
SUPERVISOR_LOG_DB = "chatbot_db"
SUPERVISOR_LOG_COLLECTION = "bot_logs"

def get_botlogs_collection():
    client = MongoClient(SUPERVISOR_LOG_MONGODB_URL)
    db = client[SUPERVISOR_LOG_DB]
    return db[SUPERVISOR_LOG_COLLECTION]

def log_event_to_mongo(telegram_id, log_type, event_data):
    """
    log_type: 'bot_logs' or 'supervisor_logs'
    event_data: dict ('timestamp' and 'message' recommended)
    """
    col = get_botlogs_collection()
    col.update_one(
        {'telegram_id': telegram_id},
        {'$push': {log_type: event_data}},
        upsert=True
    )
