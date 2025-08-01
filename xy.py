import os
import json
import pymongo

# MongoDB connection config
MONGODB_URL = "mongodb+srv://ayushsinghbasera:YEJTg3zhMwXJcTXm@cluster0.fmzrdga.mongodb.net/"
DB_NAME = "chatbot_db"
COLLECTION_NAME = "chat_sessions"

def get_json_files(folder):
    """Get all JSON file paths in the folder."""
    return [
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.endswith('.json')
    ]

def load_all_companies(folder):
    """Load all company objects from all JSON files."""
    all_companies = []
    for file_path in get_json_files(folder):
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Adapt as needed: are your results in a root list or key?
            if isinstance(data, dict) and "ranked_companies" in data:
                all_companies.extend(data["ranked_companies"])
            elif isinstance(data, list):
                all_companies.extend(data)
            else:
                all_companies.append(data)
    return all_companies

def main(json_folder):
    # 1. Load and aggregate all company records
    companies = load_all_companies(json_folder)

    # 2. Sort all companies by final_score descending
    sorted_companies = sorted(companies, key=lambda x: x['final_score'], reverse=True)

    # 3. Export to MongoDB
    client = pymongo.MongoClient(MONGODB_URL)
    db = client[DB_NAME]
    collection = db[COLLECTION_NAME]

    # Optionally, remove existing documents (take care with production!)
    # collection.delete_many({})

    # 4. Insert all sorted companies as a single document, or individually
    collection.insert_one({
        "ranked_companies": sorted_companies,
        "total_companies": len(sorted_companies)
    })

    print(f"Inserted {len(sorted_companies)} companies to MongoDB.")

if __name__ == "__main__":
    # Set folder path to where your JSON files are
    FOLDER = "/home/ec2-user/Ungli_Bot/final_structured_output"
    main(FOLDER)
