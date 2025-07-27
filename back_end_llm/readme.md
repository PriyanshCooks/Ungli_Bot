#  LLM-Based Application Discovery and Place Search System

This project uses Large Language Models (LLMs) to analyze chatbot session data, extract granular product-level application areas, and retrieve location-based search results for relevant companies using Google Places API.

---

##  Project Structure

├── back_end_llm.py # Main processing script to orchestrate the full pipeline
├── prompts.py # Contains prompt templates for LLM tasks
├── pydantic_models.py # Defines data models using Pydantic
├── utils.py # Utility functions for formatting and extraction
├── .env # Environment variables (API keys and DB config)


---

##  How It Works

### 1. **Chat Session Retrieval**
- Connects to MongoDB using `motor` async client.
- Retrieves the latest chat session from `chat_sessions` collection.
- Extracts Q&A pairs where the user and assistant interacted.

### 2. **Conversation Formatting**
- Converts Q&A pairs to ChatML format using `json_to_chatml()` from `utils.py`.

### 3. **Application Extraction**
- A structured prompt is sent to the LLM (OpenAI GPT-3.5) using the `application_prompt`.
- The model returns a list of specific product-level applications (20+ use-cases).

### 4. **Location Extraction**
- User location is inferred from the session Q&A using `extract_user_location()`.
- If a location is found, its coordinates are fetched via Google Geocoding API.

### 5. **Search Phrase Generation**
- For each application, a second LLM prompt (`search_prompt`) generates 20+ targeted Google search queries.

### 6. **Google Places Search**
- For each search phrase, the system calls the **Google Places API** to retrieve relevant businesses and manufacturers.
- Filters out permanently closed places and ensures uniqueness.

### 7. **Output Handling**
- Results are stored in:
  - MongoDB collection (for permanent logging)
  - `search_results.json` (for offline inspection)

---

## Tech Stack
- Python 3.10+

- OpenAI GPT-3.5 Turbo (via pydantic_ai.Agent) 

- Google Places API + Geocoding API 

- MongoDB 

- Pydantic 

- httpx 

- python-dotenv 

## Environment Variables

Create a .env file in the root directory with the following keys:

```python
OPENAI_API_KEY=your-openai-api-key
GOOGLE_PLACES_API_KEY=your-google-places-api-key
MONGODB_URL=your-mongodb-connection-url
MONGO_DB_NAME=your-database-name
MONGO_COLLECTION_NAME=your-collection-name
```

## Requirements
Install all required dependencies :

```python
pip install -r requirements.txt
```

## Example Usage (Mini Script)

```python
import asyncio
from back_end_llm import ApplicationProcessor

if __name__ == "__main__":
    async def main():
        processor = ApplicationProcessor()
        result = await processor.run()
        print(result)

    asyncio.run(main())
```


