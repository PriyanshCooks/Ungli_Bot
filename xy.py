import os
import json
import pymongo

# MongoDB connection config
MONGODB_URL = "mongodb+srv://ayushsinghbasera:YEJTg3zhMwXJcTXm@cluster0.fmzrdga.mongodb.net/"

# Use the requested Excel DB and Collection
EXCEL_DB_NAME = "bot_excel_reports_db"
EXCEL_COLLECTION_NAME = "bot_excel_reports"

def get_json_files(folder):
    return [
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.endswith('.json')
    ]

def load_all_companies(folder):
    all_companies = []
    for file_path in get_json_files(folder):
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict):
                all_companies.append(data)
            elif isinstance(data, list):
                all_companies.extend(data)
            else:
                print(f"Warning: Unexpected data format in {file_path}")
    return all_companies

def main(json_folder):
    companies = load_all_companies(json_folder)
    companies_with_score = [c for c in companies if 'final_score' in c]

    # Sort descending by final_score
    sorted_companies = sorted(companies_with_score, key=lambda x: x['final_score'], reverse=True)

    # Connect to MongoDB Excel DB and collection
    client = pymongo.MongoClient(MONGODB_URL)
    db = client[EXCEL_DB_NAME]
    collection = db[EXCEL_COLLECTION_NAME]

    # Optionally clear previous records (careful in prod)
    # collection.delete_many({})

    # Prepare documents for insertion with rank field and flatten keys
    docs = []
    for idx, comp in enumerate(sorted_companies, 1):
        doc = {
            "rank": idx,
            "company": comp.get("company"),
            "final_score": comp.get("final_score"),
            "reasoning": comp.get("reasoning"),
            "address": comp.get("address"),
            "phone": comp.get("phone"),
            # If those fields are nested or in scoring_summary, flatten as needed
            # For example, merge scoring_summary or others here if needed
        }
        docs.append(doc)

    # Insert all documents individually (preferred for Excel export)
    collection.insert_many(docs)

    print(f"Inserted {len(docs)} company reports into {EXCEL_DB_NAME}.{EXCEL_COLLECTION_NAME}")

if __name__ == "__main__":
    FOLDER = "/home/ec2-user/Ungli_Bot/final_structured_output"
    main(FOLDER)
