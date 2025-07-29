# supervisor/agent.py

import os
import json
import logging
from typing import List, Dict, Any
from dotenv import load_dotenv

from .pydantic_model import ConversationLog, CompanyMatchOutput, ExtractedData
from .prompts import SYSTEM_PROMPT, EVALUATION_PROMPT_TEMPLATE
from .utils import (
    fetch_company_profile,
    convert_conversationlog_to_chatml,
    sanitize_filename,
    save_output_locally,
    call_perplexity,
    log_event_to_mongo
)
from datetime import datetime, UTC

load_dotenv()

class SupervisorAgent:
    def __init__(
        self,
        chat: ConversationLog,
        companies: List[Dict[str, Any]],
        user_id: str,
        chat_id: str,
        session_uuid: str,
        batch_size: int = 5,
        telegram_id: int = None
    ):
        self.chatml = convert_conversationlog_to_chatml(chat)
        self.companies = companies
        self.user_id = user_id
        self.chat_id = chat_id
        self.session_uuid = session_uuid
        self.batch_size = batch_size
        self.company_profile = fetch_company_profile(user_id, chat_id, session_uuid)
        self.failed_companies: List[Dict[str, Any]] = []
        self.telegram_id = telegram_id

    def _construct_perplexity_prompt(self, company: Dict[str, Any]) -> List[Dict[str, str]]:
        profile = self.company_profile.get("company_profile", "")
        website = self.company_profile.get("company_website", "")
        buyer_profile_text = profile
        if website:
            buyer_profile_text += f"\n[Company Website]: {website}"
        company_info_text = json.dumps({
            "name": company.get("name", "N/A"),
            "website": company.get("website", "N/A"),
            "address": company.get("address", "N/A"),
            "phone": company.get("phone", {}).get("national", "N/A")
        }, indent=2)
        chat_history = "\n".join(
            f"assistant: {m['content']}" if m["role"] == "user" else f"user: {m['content']}"
            for m in self.chatml
        )
        user_prompt = EVALUATION_PROMPT_TEMPLATE.format(
            chat_history=chat_history,
            buyer_profile=buyer_profile_text,
            company_info=company_info_text
        )
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]

    def _get_company_field(self, company_name: str, key: str, nested_key: str = None):
        for company in self.companies:
            if company.get("name") == company_name:
                value = company.get(key)
                if nested_key and isinstance(value, dict):
                    return value.get(nested_key, "N/A")
                return value or "N/A"
        return "N/A"

    async def process_batch(self, batch: List[Dict[str, Any]]) -> List[CompanyMatchOutput]:
        results = []
        for company in batch:
            logging.info(f"🚀 Processing company: {company.get('name')}")
            if self.telegram_id:
                log_event_to_mongo(
                    self.telegram_id,
                    "supervisor_logs",
                    {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "event": "processing_company",
                        "company": company.get('name'),
                        "message": f"Supervisor processing company: {company.get('name')}"
                    }
                )
            try:
                messages = self._construct_perplexity_prompt(company)
                raw = await call_perplexity(messages)
                # Clean raw: remove code fences and 'json' word if exists
                raw = raw.strip().lstrip("`").rstrip("`")
                if raw.lower().startswith("json"):
                    raw = raw[4:].lstrip()
                parsed = json.loads(raw)

                # Robustly extract final_score
                final_score = parsed.get("final_score")
                if final_score is None:
                    # Try alternate key (as Perplexity often returns the nested structure)
                    if "final_score_matrix_summary" in parsed and isinstance(parsed["final_score_matrix_summary"], dict):
                        final_score = parsed["final_score_matrix_summary"].get("weighted_mean_final_score")
                if final_score is None:
                    logging.error(f"No final_score found in LLM response for {company.get('name')}: {parsed}")
                    self.failed_companies.append(company)
                    continue  # Skip appending or saving this company

                match = CompanyMatchOutput(
                    company=company["name"],
                    scoring_summary=parsed["scoring_summary"],
                    scores=parsed["scores"],
                    reasoning=parsed["reasoning"],
                    final_score=final_score  # This is a float
                )
                self._save_company_output(match)
                results.append(match)
                if self.telegram_id:
                    log_event_to_mongo(
                        self.telegram_id,
                        "supervisor_logs",
                        {
                            "timestamp": datetime.now(UTC).isoformat(),
                            "event": "company_processed",
                            "company": company.get('name'),
                            "final_score": match.final_score,
                            "message": f"Company {company.get('name')} processed with score {match.final_score}"
                        }
                    )

                self._save_company_output(match)
                results.append(match)
                if self.telegram_id:
                    log_event_to_mongo(
                        self.telegram_id,
                        "supervisor_logs",
                        {
                            "timestamp": datetime.now(UTC).isoformat(),
                            "event": "company_processed",
                            "company": company.get('name'),
                            "final_score": match.final_score,
                            "message": f"Company {company.get('name')} processed with score {match.final_score}"
                        }
                    )
            except Exception as e:
                logging.exception(f"❌ Failed for {company.get('name')}: {e}")
                self.failed_companies.append(company)
                if self.telegram_id:
                    log_event_to_mongo(
                        self.telegram_id,
                        "supervisor_logs",
                        {
                            "timestamp": datetime.now(UTC).isoformat(),
                            "event": "company_failed",
                            "company": company.get('name'),
                            "message": f"Supervisor failed to process company: {company.get('name')}, Error: {str(e)}"
                        }
                    )
        return results

    async def select_top_companies(self) -> Dict[str, Any]:
        import time
        start_time = time.time()
        if self.telegram_id:
            log_event_to_mongo(
                self.telegram_id,
                "supervisor_logs",
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "event": "ranking_started",
                    "message": "Supervisor started company ranking."
                }
            )
        matches = []
        for i in range(0, len(self.companies), self.batch_size):
            batch = self.companies[i:i + self.batch_size]
            matches.extend(await self.process_batch(batch))

        if self.failed_companies:
            logging.warning(f"🔁 Retrying {len(self.failed_companies)} failed companies...")
            if self.telegram_id:
                log_event_to_mongo(
                    self.telegram_id,
                    "supervisor_logs",
                    {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "event": "retry_failed_companies",
                        "count": len(self.failed_companies),
                        "message": f"Retrying {len(self.failed_companies)} failed companies."
                    }
                )
            retry_batch = await self.process_batch(self.failed_companies)
            matches.extend(retry_batch)

        if self.failed_companies:
            with open("final_structured_output/failed_companies.json", "w", encoding="utf-8") as f:
                json.dump(self.failed_companies, f, indent=2, ensure_ascii=False)
            if self.telegram_id:
                log_event_to_mongo(
                    self.telegram_id,
                    "supervisor_logs",
                    {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "event": "failed_companies_saved",
                        "count": len(self.failed_companies),
                        "message": f"Saved failed companies to disk: {len(self.failed_companies)}"
                    }
                )

        sorted_all = sorted(matches, key=lambda x: x.final_score, reverse=True)
        top10 = sorted_all[:10]
        report = {
            "ranked_companies": [
                {
                    **match.dict(),
                    "address": self._get_company_field(match.company, "address"),
                    "phone": self._get_company_field(match.company, "phone", nested_key="national")
                }
                for match in top10
            ]
        }
        markdown = "# Top 10 Ranked Companies to Contact\n\n"
        for i, m in enumerate(top10):
            address = self._get_company_field(m.company, "address")
            phone = self._get_company_field(m.company, "phone", nested_key="national")
            markdown += (
                f"## {i+1}. {m.company}\n"
                f"- **Final Score**: {m.final_score:.1f}\n"
                f"- **Reasoning**: {m.reasoning}\n"
                f"- **Address**: {address}\n"
                f"- **Phone**: {phone}\n\n"
            )
        folder = "final_structured_output"
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "all_ranked_companies.md"), "w", encoding="utf-8") as f:
            f.write(markdown)
        save_output_locally(
            ExtractedData(company="all_ranked_companies", variable_data=report),
            folder=folder
        )
        total_time = time.time() - start_time
        logging.info(f"⏱️ Total processing time: {total_time:.2f} seconds")
        if self.telegram_id:
            log_event_to_mongo(
                self.telegram_id,
                "supervisor_logs",
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "event": "ranking_completed",
                    "total_companies": len(self.companies),
                    "total_time_seconds": total_time,
                    "top_companies": [m.company for m in top10],
                    "message": "Supervisor company ranking completed."
                }
            )
        return report

    def _save_company_output(self, company_match: CompanyMatchOutput):
        folder = "final_structured_output"
        os.makedirs(folder, exist_ok=True)
        filename = sanitize_filename(company_match.company.lower()) + ".json"
        path = os.path.join(folder, filename)
        logging.info(f"💾 Saving output to {path}")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(company_match.dict(), f, indent=4, ensure_ascii=False)


        # sorted_all = sorted(matches, key=lambda x: x.final_score, reverse=True)

        # report = {
        #     "ranked_companies": [
        #         {
        #             **match.dict(),
        #             "address": self._get_company_field(match.company, "address"),
        #             "phone": self._get_company_field(match.company, "phone", nested_key="national")
        #         }
        #         for match in sorted_all
        #     ]
        # }

        # markdown = "# Ranked Companies (All)\n\n"
        # for i, m in enumerate(sorted_all):
        #     address = self._get_company_field(m.company, "address")
        #     phone = self._get_company_field(m.company, "phone", nested_key="national")
        #     markdown += (
        #         f"## {i+1}. {m.company}\n"
        #         f"- **Final Score**: {m.final_score:.1f}\n"
        #         f"- **Reasoning**: {m.reasoning}\n"
        #         f"- **Address**: {address}\n"
        #         f"- **Phone**: {phone}\n\n"
        #     )
        



#top 100 companies selection logic
    # async def select_top_companies(self) -> Dict[str, Any]:
    #     import time
    #     start_time = time.time()

    #     matches = []
    #     for i in range(0, len(self.companies), self.batch_size):
    #         batch = self.companies[i:i + self.batch_size]
    #         matches.extend(await self.process_batch(batch))

    #     # Retry failed companies once
    #     if self.failed_companies:
    #         logging.warning(f"🔁 Retrying {len(self.failed_companies)} failed companies...")
    #         retry_batch = await self.process_batch(self.failed_companies)
    #         matches.extend(retry_batch)

    #     # Save failed ones
    #     if self.failed_companies:
    #         with open("final_structured_output/failed_companies.json", "w", encoding="utf-8") as f:
    #             json.dump(self.failed_companies, f, indent=2, ensure_ascii=False)

    #     sorted_all = sorted(matches, key=lambda x: x.final_score, reverse=True)
    #     top_100 = sorted_all[:100]

    #     report = {
    #         "top_100_companies": [
    #             {
    #                 **match.dict(),
    #                 "address": self._get_company_field(match.company, "address"),
    #                 "phone": self._get_company_field(match.company, "phone", nested_key="national")
    #             }
    #             for match in top_100
    #         ]
    #     }

    #     markdown = "# Top 100 Companies to Contact\n\n"
    #     for i, m in enumerate(top_100):
    #         address = self._get_company_field(m.company, "address")
    #         phone = self._get_company_field(m.company, "phone", nested_key="national")
    #         markdown += (
    #             f"## {i+1}. {m.company}\n"
    #             f"- **Final Score**: {m.final_score:.1f}\n"
    #             f"- **Reasoning**: {m.reasoning}\n"
    #             f"- **Address**: {address}\n"
    #             f"- **Phone**: {phone}\n\n"
    #         )

    #     folder = "final_structured_output"
    #     os.makedirs(folder, exist_ok=True)
    #     with open(os.path.join(folder, "top_100_companies.md"), "w", encoding="utf-8") as f:
    #         f.write(markdown)

    #     save_output_locally(
    #         ExtractedData(company="top_100_companies", variable_data=report),
    #         folder=folder
    #     )

    #     total_time = time.time() - start_time
    #     logging.info(f"⏱️ Total processing time: {total_time:.2f} seconds")
    #     return report

   