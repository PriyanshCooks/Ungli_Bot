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
            # Assuming each JSON is a single company dictionary
            if isinstance(data, dict):
                all_companies.append(data)
            elif isinstance(data, list):
                # Just in case some file has a list of companies
                all_companies.extend(data)
            else:
                print(f"Warning: Unexpected data format in file {file_path}")
    return all_companies

def main(json_folder):
    # 1. Load all companies
    companies = load_all_companies(json_folder)

    print(f"Loaded {len(companies)} companies from JSON files.")

    # 2. Filter out entries missing 'final_score' and warn about them
    companies_with_score = []
    missing_score_count = 0
    for c in companies:
        if 'final_score' in c:
            companies_with_score.append(c)
        else:
            missing_score_count += 1
            print(f"Warning: Company entry missing 'final_score', skipping: {c.get('company', '<unknown>')}")

    print(f"Companies with 'final_score': {len(companies_with_score)}")
    print(f"Companies skipped due to missing 'final_score': {missing_score_count}")

    # 3. Sort by 'final_score' descending
    sorted_companies = sorted(companies_with_score, key=lambda x: x['final_score'], reverse=True)

    # 4. Export to MongoDB
    client = pymongo.MongoClient(MONGODB_URL)
    db = client[DB_NAME]
    collection = db[COLLECTION_NAME]

    # Optional: clear previous data for a clean insert (use with caution)
    # collection.delete_many({})

    # 5. Insert one document with all ranked companies
    collection.insert_one({
        "ranked_companies": sorted_companies,
        "total_companies": len(sorted_companies)
    })

    print(f"Inserted {len(sorted_companies)} companies into MongoDB.")

if __name__ == "__main__":
    FOLDER = "/home/ec2-user/Ungli_Bot/final_structured_output"
    main(FOLDER)
