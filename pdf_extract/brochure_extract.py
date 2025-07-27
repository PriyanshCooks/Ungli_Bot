# pdf_extract/brochure_extract.py

import pytesseract
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'


import fitz  # PyMuPDF
from pdf2image import convert_from_path
import pytesseract
from PIL import Image
import os
from pymongo import MongoClient

MONGODB_URL = "mongodb+srv://ayushsinghbasera:YEJTg3zhMwXJcTXm@cluster0.fmzrdga.mongodb.net/"
DB_NAME = "chatbot_db"
COLLECTION_NAME = "chat_sessions"

# If Tesseract is not in PATH, specify the exact binary path below (Windows example)
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def extract_text_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    text = "\n".join([page.get_text().strip() for page in doc])
    return text.strip()

def pytesseract_image(img_path):
    try:
        text = pytesseract.image_to_string(Image.open(img_path))
        return text
    except Exception as e:
        print(f"[TESSERACT ERROR] Failed to OCR {img_path}: {e}")
        return ""

def extract_text_with_ocr_if_needed(pdf_path):
    text = extract_text_from_pdf(pdf_path)
    if len(text) >= 100:
        return text
    
    # If direct extraction is too short, do OCR on all pages
    images = convert_from_path(pdf_path)
    text = ""
    for i, image in enumerate(images):
        temp_img_path = f"temp_page_{i}.png"
        image.save(temp_img_path, "PNG")
        ocr_text = pytesseract_image(temp_img_path)
        text += f"\n\n--- Page {i + 1} ---\n\n" + ocr_text
        os.remove(temp_img_path)
    return text.strip()

def push_to_mongodb(user_id, chat_id, session_uuid, extracted_text):
    client = MongoClient(MONGODB_URL)
    db = client[DB_NAME]
    col = db[COLLECTION_NAME]
    query = {
        "user_id": user_id,
        "session_uuid": session_uuid,
        f"chats.{chat_id}": {"$exists": True}
    }
    update = {"$set": {f"chats.{chat_id}.company_profile": extracted_text}}
    result = col.update_one(query, update)
    if result.modified_count == 0:
        print("[MONGO WARNING] No matching chat session found. Attempting to insert a new record...")
        fallback_data = {
            "user_id": user_id,
            "session_uuid": session_uuid,
            "chats": {
                chat_id: {
                    "company_profile": extracted_text
                }
            }
        }
        insert_result = col.insert_one(fallback_data)
        if insert_result.inserted_id:
            print(f"[MONGO INSERT] Inserted new chat session with ID: {insert_result.inserted_id}")
            return True
        else:
            print("[MONGO ERROR] Failed to insert fallback document.")
            return False
    else:
        print("[MONGO UPDATE] Company profile successfully updated.")
        return True

def process_brochure(pdf_path, user_id, chat_id, session_uuid):
    text = extract_text_with_ocr_if_needed(pdf_path)
    success = push_to_mongodb(user_id, chat_id, session_uuid, text)
    return success, text
