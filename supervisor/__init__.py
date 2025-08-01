import asyncio
import os
from .agent import SupervisorAgent
from .utils import fetch_chat_as_conversationlog, fetch_companies_from_applications
from .utils import ranked_companies_to_excel

def deduplicate_companies(companies):
    seen = set()
    unique_companies = []
    for company in companies:
        name = company.get("name")
        if name and name not in seen:
            seen.add(name)
            unique_companies.append(company)
    return unique_companies

async def run_supervisor_pipeline(user_id, chat_id, session_uuid, batch_size=5, telegram_id=None):
    conversation = fetch_chat_as_conversationlog(user_id, chat_id, session_uuid)
    companies = fetch_companies_from_applications(user_id, chat_id, session_uuid)
    companies = deduplicate_companies(companies)
    if not conversation or not companies:
        raise RuntimeError("Missing data for ranking.")
    agent = SupervisorAgent(
        chat=conversation,
        companies=companies,
        user_id=user_id,
        chat_id=chat_id,
        session_uuid=session_uuid,
        batch_size=batch_size,
        telegram_id=telegram_id
    )
    await agent.select_top_companies()
    folder = "final_structured_output"
    md_path = os.path.join(folder, "all_ranked_companies.md")
    xlsx_path = os.path.join(folder, "all_ranked_companies.xlsx")
    if os.path.exists(md_path):
        ranked_companies_to_excel(md_path, xlsx_path)
        return xlsx_path
    return None
