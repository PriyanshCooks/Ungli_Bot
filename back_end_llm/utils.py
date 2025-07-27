import logging
import requests
import re
import time
from typing import List, Optional, Tuple
from .pydantic_models import ConversationEntry
from pymongo.collection import Collection
from dotenv import load_dotenv
from pymongo import MongoClient
import os

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
MONGODB_URL = os.getenv("MONGODB_URL")
WRITE_MONGO_DB_NAME = os.getenv("WRITE_MONGO_DB_NAME")
WRITE_MONGO_COLLECTION_NAME = os.getenv("WRITE_MONGO_COLLECTION_NAME")
READ_MONGO_DB = os.getenv("READ_MONGO_DB")
READ_MONGO_COLLECTION = os.getenv("READ_MONGO_COLLECTION")



logging.basicConfig(
    filename="scraper.log",   # or whatever log filename you're using
    filemode="w",             # <-- Overwrites file on each run
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
# ------------------ MongoDB Utilities ------------------
def get_mongo_collection() -> Collection:
    client = MongoClient(MONGODB_URL)
    db = client[WRITE_MONGO_DB_NAME]
    return db[WRITE_MONGO_COLLECTION_NAME]

def get_mongo_client():
    return MongoClient(MONGODB_URL)

def get_read_collection():
    client = MongoClient(MONGODB_URL)
    return client[READ_MONGO_DB][READ_MONGO_COLLECTION]

def get_write_collection():
    client = MongoClient(MONGODB_URL)
    return client[WRITE_MONGO_DB_NAME][WRITE_MONGO_COLLECTION_NAME]

def fetch_latest_session_from_mongo(session_uuid: str, user_id: str, chat_id: str) -> Tuple[Optional[List[ConversationEntry]], Optional[str]]:
    collection = get_read_collection()
    query = { "session_uuid": session_uuid, "user_id": user_id }
    logging.info(f"MongoDB query: {query}")
    session = collection.find_one(query)
    logging.info(f"Raw session fetch result: {session}")
    if not session:
        logging.warning(f"No session found for session_uuid={session_uuid}, user_id={user_id}")
        return None, None
    logging.info("✅ Session fetched from MongoDB.")

    chats = session.get("chats", {})
    chat_data = chats.get(chat_id, {})
    company_profile = chat_data.get("company_profile", "")
    if company_profile and company_profile.strip():
        logging.info("✅ Brochure (company_profile) FOUND inside chats.")
        logging.info(f"📄 Brochure content length: {len(company_profile)}")
    else:
        logging.warning("❌ No brochure (company_profile) found inside chats or it's empty/whitespace.")

    messages = chat_data.get("messages", [])
    qa_pairs = []
    for i in range(0, len(messages) - 1):
        current = messages[i]
        next_msg = messages[i + 1]
        if current["role"] == "assistant" and next_msg["role"] == "user":
            qa_pairs.append(ConversationEntry(
                question=current.get("question", "") or current.get("answer", ""),
                answer=next_msg.get("answer", "")
            ))
    return qa_pairs if qa_pairs else [], company_profile







# ------------------ ChatML Utility ------------------
def json_to_chatml(conversation_log) -> str:
    chatml_lines = []
    for entry in conversation_log.conversation:
        chatml_lines.append(f"<|user|> {entry.question}")
        chatml_lines.append(f"<|assistant|> {entry.answer}")
    return "\n".join(chatml_lines)

# ------------------ Location Extraction ------------------
def extract_user_location(conversation_entries: List['ConversationEntry']) -> Optional[str]:
    location_keywords = ["location", "city", "region", "area", "place", "from", "based in", "supply", "deliver", "across", "to"]

    for entry in reversed(conversation_entries):
        text = (entry.question or "") + " " + (entry.answer or "")
        text = text.lower()

        for keyword in location_keywords:
            if keyword in text:
                match = re.search(r"\b(?:in|to|across|from|at)?\s*([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)", entry.answer or "")
                if match:
                    return match.group(1).strip()
    return None

def get_lat_lng_from_location(location_name: str) -> Optional[Tuple[float, float]]:
    geocode_url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": location_name, "key": GOOGLE_PLACES_API_KEY}
    try:
        response = requests.get(geocode_url, params=params, timeout=10)
        data = response.json()
        if data.get("status") == "OK":
            loc = data["results"][0]["geometry"]["location"]
            return loc["lat"], loc["lng"]
    except Exception as e:
        logging.error(f"Error in geocoding location '{location_name}': {e}")
    return None

# ------------------ Place Details Enhancer ------------------
def get_place_details(place_id: str) -> dict:
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        "place_id": place_id,
        "fields": "website,url,formatted_phone_number,international_phone_number",
        "key": GOOGLE_PLACES_API_KEY
    }
    try:
        res = requests.get(url, params=params, timeout=10)
        if res.status_code == 200:
            return res.json().get("result", {})
    except Exception as e:
        logging.error(f"Error getting details for place_id '{place_id}': {e}")
    return {}

# ------------------ Google Places Search ------------------
def search_google_places(query: str, location: Optional[Tuple[float, float]] = None, radius: int = 50000) -> Tuple[List[dict], str]:
    endpoint = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": ",".join([
            "places.id",
            "places.displayName",
            "places.formattedAddress",
            "places.location",
            "places.primaryType",
            "places.types",
            "places.businessStatus",
            "places.googleMapsUri",
            "places.websiteUri",
            "places.nationalPhoneNumber",
            "places.internationalPhoneNumber",
            "places.rating",
            "places.userRatingCount"
        ])
    }

    payload = {
        "textQuery": query,
        "maxResultCount": 20
    }

    if location:
        lat, lng = location
        delta = 0.5
        payload["locationRestriction"] = {
            "rectangle": {
                "minLatitude": lat - delta,
                "maxLatitude": lat + delta,
                "minLongitude": lng - delta,
                "maxLongitude": lng + delta
            }
        }

    all_results = []
    try:
        for _ in range(3):
            response = requests.post(endpoint, headers=headers, json=payload, timeout=10)
            data = response.json()

            places = data.get("places", [])
            for place in places:
                place_id = place.get("id")
                if place_id:
                    details = get_place_details(place_id)
                    place["websiteURL"] = details.get("website")
                    place["googleMapsURL"] = details.get("url")
                    place["nationalPhoneNumber"] = details.get("formatted_phone_number")
                    place["internationalPhoneNumber"] = details.get("international_phone_number")
            
            all_results.extend(places)

            next_page_token = data.get("nextPageToken")
            if not next_page_token:
                break

            time.sleep(2)
            payload["pageToken"] = next_page_token

    except Exception as e:
        logging.error(f"Google Places API Exception | Query: '{query}' | Exception: {e}")
        return all_results, "ERROR"

    return all_results, "OK"
