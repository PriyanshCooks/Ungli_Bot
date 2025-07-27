# Front End LLM Chatbot

This project is a FastAPI-based chatbot application powered by OpenAI's GPT (GPT-4o). It is designed to ask relevant, domain-specific questions to help discover product details for potential B2B customers.

## 🧠 Features
- Conversational product discovery using approved GPT prompts
- Async MongoDB session logging with `motor`
- Dynamic UI rendered with Jinja2 templates
- Persistent user sessions

## 📂 Project Structure
```
front_end_llm/
├── front_end_llm.py          # Main FastAPI application entry
├── prompts.py                # GPT prompt system and logic
├── utils.py                  # Route handlers and MongoDB utilities
├── ss/
│   ├── templates/            # Jinja2 HTML templates
│   └── static/               # CSS and assets
├── .env                      # Environment configuration (API keys, DB URI)
├── requirements.txt          # Python dependencies
├── output.json               # Optional: stores output if needed
└── readme.md                 # Project overview (this file)
```

## 🚀 Getting Started

### 1. Clone the Repo


### 2. Set Up Environment
Create a `.env` file:
```env
OPENAI_API_KEY=your_openai_key
MONGO_URL=your_mongo_uri
FASTAPI_SECRET_KEY=some_secret_key
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the App
```bash
uvicorn front_end_llm:app --reload
```
Visit: `http://127.0.0.1:8000`

## 🛠 Technologies
- **FastAPI** for backend
- **Jinja2** for templating
- **Motor** for async MongoDB
- **OpenAI GPT-4o** for LLM interactions

## 📄 License
MIT License. Feel free to use, fork, and adapt.
