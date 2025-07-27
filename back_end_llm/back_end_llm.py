import logging
from uuid import uuid4
from back_end_llm.prompts import get_application_extraction_prompt, get_google_search_prompt
from back_end_llm.utils import (
    fetch_latest_session_from_mongo,
    json_to_chatml,
    extract_user_location,
    get_lat_lng_from_location,
    search_google_places,
    get_write_collection
)
from back_end_llm.pydantic_models import (
    ConversationLog, PredictionResult, SearchQueryEntry, SearchQueryResults, Place, SearchTerms
)
from pydantic_ai import Agent
from datetime import datetime

# Logging configuration
logging.basicConfig(
    level=logging.INFO,  # set to DEBUG for more
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("scraper.log", mode='a', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

def run_search_pipeline(user_id, chat_id, session_uuid):
    logging.info(f"Running pipeline with user_id={user_id}, chat_id={chat_id}, session_uuid={session_uuid}")
    conversation_entries, company_profile = fetch_latest_session_from_mongo(session_uuid, user_id, chat_id)
    if not conversation_entries and not company_profile:
        logging.warning("No valid chat messages or brochure text found.")
        print("No valid session or brochure found.")
        return

    # Log state of the data pulled from MongoDB
    if company_profile:
        logging.info("Brochure (company_profile) FOUND.")
        logging.info(f"Raw content: {repr(company_profile)}")
        logging.info(f"Length: {len(company_profile)}")
        if company_profile.strip():
            logging.info("Brochure content is non-empty after stripping.")
            logging.debug(f"First 300 characters: {company_profile.strip()[:300]}")
        else:
            logging.warning("Brochure is empty or only whitespace after stripping.")
    else:
        logging.info("No brochure (company_profile) found for this session.")

    # Prepare conversation and brochure for prompt
    chatml_lines = []
    if conversation_entries:
        conv_log = ConversationLog(conversation=conversation_entries)
        chatml_lines.append("<|user|> The following is a conversation log about the product:")
        chatml_lines.append(json_to_chatml(conv_log))
    if company_profile and company_profile.strip():
        chatml_lines.append("<|user|> The following is a brochure about the same product:")
        chatml_lines.append(f"<|user|> {company_profile.strip()}")
    chatml_conversation = "\n".join(chatml_lines)

    # Optionally save the input to a debug file
    with open("debug_chatml_input.txt", "w", encoding="utf-8") as f:
        f.write(chatml_conversation)

    # Location handling
    user_location = extract_user_location(conversation_entries or [])
    coords = get_lat_lng_from_location(user_location) if user_location else None
    if coords:
        logging.info(f"User location: {user_location} → {coords}")

    # GPT prompt for extracting applications of product
    agent = Agent("openai:gpt-3.5-turbo")
    result = agent.run_sync(get_application_extraction_prompt(chatml_conversation), output_type=PredictionResult)
    applications = result.output.predicted_interests

    search_results = []

    for app in applications:
        search_terms = []
        try:
            PROMPT = get_google_search_prompt(app)
            search_result = agent.run_sync(PROMPT, output_type=SearchTerms)
            search_terms = search_result.output.search_terms
        except Exception as e:
            logging.error("Search term generation failed for '%s': %s", app, str(e))

        all_places = []
        final_status = "ZERO_RESULTS"
        for term in search_terms:
            places, status = search_google_places(term, location=coords)
            if status == "OK" and places:
                final_status = "OK"
            elif status == "ERROR":
                final_status = "ERROR"
            all_places.extend(places)
        unique_places = {
            p.get("id"): p
            for p in all_places
            if p.get("businessStatus") != "CLOSED_PERMANENTLY" and p.get("id")
        }
        search_results.append(SearchQueryEntry(
            application=app,
            google_search_terms=search_terms,
            matched_places=[Place(**place) for place in unique_places.values()],
            status=final_status
        ))

    final_output = SearchQueryResults(
        extracted_applications=applications,
        targeting_keywords=search_results
    )

    # Save result locally (optional)
    with open('output.json', 'w', encoding='utf-8') as f:
        f.write(final_output.model_dump_json(indent=2))
    print("Results saved to: output.json")

    # Save results into MongoDB under correct chat and session
    collection = get_write_collection()
    output_data = [
        {
            "application": entry.application,
            "search_terms": entry.google_search_terms,
            "companies": [
                {
                    "name": p.displayName.text if hasattr(p.displayName, "text") else None,
                    "address": p.formattedAddress,
                    "location": {
                        "latitude": p.location.latitude if p.location else None,
                        "longitude": p.location.longitude if p.location else None
                    },
                    "phone": {
                        "national": p.nationalPhoneNumber,
                        "international": p.internationalPhoneNumber
                    },
                    "website": p.websiteURL,
                    "google_maps_url": p.googleMapsURL,
                    "rating": p.rating,
                    "user_rating_count": p.userRatingCount,
                    "types": p.types or [],
                    "status": p.businessStatus
                } for p in entry.matched_places
            ]
        } for entry in final_output.targeting_keywords
    ]
    collection.update_one(
        {"session_uuid": session_uuid, "user_id": user_id},
        {"$set": {f"chats.{chat_id}.output": output_data}},
        upsert=True
    )
    logging.info(f"Chat data inserted under chat ID '{chat_id}' in MongoDB.")
    print(f"Chat data inserted under chat ID '{chat_id}' in MongoDB.")

if __name__ == "__main__":
    import sys
    if len(sys.argv) == 4:
        run_search_pipeline(user_id=sys.argv[1], chat_id=sys.argv[2], session_uuid=sys.argv[3])
