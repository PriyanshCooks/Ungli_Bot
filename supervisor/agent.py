# supervisor/agent.py

# supervisor/agent.py

import os
import json
import logging
import pandas as pd
from typing import List, Dict, Any
from dotenv import load_dotenv
import asyncio
from .pydantic_model import ConversationLog, CompanyMatchOutput, ExtractedData
from .prompts import SYSTEM_PROMPT, \
    EVALUATION_PROMPT_TEMPLATE
from .utils import fetch_company_profile, \
    convert_conversationlog_to_chatml, \
    sanitize_filename, \
    save_output_locally, \
    call_perplexity, \
    log_event_to_mongo
from datetime import datetime, timezone

load_dotenv()

PERPLEXITY_COST_PER_1K = 0.01  # update your price here


class SupervisorAgent:
    def __init__(self,
                 chat: ConversationLog,
                 companies: List[Dict[str, Any]],
                 user_id: str,
                 chat_id: str,
                 session_uuid: str,
                 batch_size=5,
                 telegram_id: int = None
                 ):
        self.chatml = convert_conversationlog_to_chatml(chat)
        self.companies = companies
        self.user_id = user_id
        self.chat_id = chat_id
        self.session_uuid = session_uuid
        self.batch_size = batch_size
        self.company_profile = fetch_company_profile(user_id, chat_id, session_uuid)
        self.telegram_id = telegram_id
        self.failed_companies: List[Dict[str, Any]] = []
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def _get_folder_path(self) -> str:
        base_folder = "final_structured_output"
        if self.telegram_id:
            return os.path.join(base_folder, str(self.telegram_id))
        return base_folder

    def _construct_perplexity_prompt(self, company: Dict[str, Any]) -> List[Dict[str, str]]:
        profile = self.company_profile.get("company_profile", "")
        website = self.company_profile.get("company_website", "")
        buyer_profile_text = profile
        if website:
            buyer_profile_text += f"\n[Company Website]: {website}"

        company_info = {
            "name": company.get("name", "N/A"),
            "website": company.get("website", "N/A"),
            "address": company.get("address", "N/A"),
            "phone": company.get("phone", {}).get("national", "N/A"),
        }
        company_info_text = json.dumps(company_info, indent=2)

        chat_history_text = "\n".join(
            f"assistant: {m['content']}" if m["role"] == "user" else f"user: {m['content']}"
            for m in self.chatml
        )

        user_prompt = EVALUATION_PROMPT_TEMPLATE.format(
            chat_history=chat_history_text,
            buyer_profile=buyer_profile_text,
            company_info=company_info_text
        )

        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]

    def _get_company_field(self, company_name: str, key: str, nested_key=None):
        for company in self.companies:
            if company.get("name") == company_name:
                val = company.get(key)
                if nested_key and isinstance(val, dict):
                    return val.get(nested_key, "N/A")
                return val or "N/A"
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
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "event": "processing_company",
                        "company": company.get('name'),
                        "message": f"Supervisor processing company: {company.get('name')}"
                    }
                )
            try:
                messages = self._construct_perplexity_prompt(company)
                # Expect tuple: raw text, input tokens, output tokens
                raw, input_tokens, output_tokens = await call_perplexity(messages)
                self.total_input_tokens += input_tokens
                self.total_output_tokens += output_tokens

                # Clean response
                raw = raw.strip().lstrip("`").rstrip("`")
                if raw.lower().startswith("json"):
                    raw = raw[4:].lstrip()

                parsed = json.loads(raw)

                # Extract final score, either direct or nested
                final_score = parsed.get("final_score")
                if final_score is None and "final_score_matrix_summary" in parsed and isinstance(parsed["final_score_matrix_summary"], dict):
                    final_score = parsed["final_score_matrix_summary"].get("weighted_mean")

                    # Fallback, if above doesn't exist, try weighted_mean_score or weighted_mean_score (checking common naming)
                    if final_score is None:
                        final_score = parsed["final_score_matrix_summary"].get("weighted_mean_score")
                    if final_score is None:
                        final_score = parsed["final_score_matrix_summary"].get("weighted_mean_final_score")

                if final_score is None:
                    logging.error(f"No final_score found in response for {company.get('name')}; skipping")
                    self.failed_companies.append(company)
                    continue

                match = CompanyMatchOutput(
                    company=company["name"],
                    scoring_summary=parsed.get("scoring_summary", ""),
                    scores=parsed.get("scores", {}),
                    reasoning=parsed.get("reasoning", ""),
                    final_score=final_score
                )

                self._save_company_output(match)
                results.append(match)

                if self.telegram_id:
                    log_event_to_mongo(
                        self.telegram_id,
                        "supervisor_logs",
                        {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "event": "company_processed",
                            "company": company.get('name'),
                            "final_score": match.final_score,
                            "message": f"Company processed with score {match.final_score}"
                        }
                    )
                await asyncio.sleep(1)  # rate limit

            except Exception as e:
                logging.exception(f"❌ Failed on company {company.get('name')}: {e}")
                self.failed_companies.append(company)
                if self.telegram_id:
                    log_event_to_mongo(
                        self.telegram_id,
                        "supervisor_logs",
                        {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "event": "company_failed",
                            "company": company.get('name'),
                            "message": f"Failed processing company: {str(e)}"
                        }
                    )
        return results

import pandas as pd

async def select_top_companies(self) -> Dict[str, Any]:
    import time
    start = time.time()

    if self.telegram_id:
        log_event_to_mongo(
            self.telegram_id, "supervisor_logs",
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": "ranking_started",
                "message": "Ranking started",
            }
        )

    results = []
    for i in range(0, len(self.companies), self.batch_size):
        batch = self.companies[i:i + self.batch_size]
        res = await self.process_batch(batch)
        results.extend(res)

    # Retry failed companies if any
    if self.failed_companies:
        if self.telegram_id:
            log_event_to_mongo(
                self.telegram_id, "supervisor_logs",
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event": "retry_failed_companies",
                    "count": len(self.failed_companies),
                    "message": "Retrying failed companies",
                }
            )
        retry_results = await self.process_batch(self.failed_companies)
        results.extend(retry_results)

    # Save failed companies info locally if any
    if self.failed_companies:
        folder = self._get_folder_path()
        os.makedirs(folder, exist_ok=True)
        failed_path = os.path.join(folder, "failed_companies.json")
        with open(failed_path, "w", encoding="utf-8") as f:
            json.dump(self.failed_companies, f, indent=2, ensure_ascii=False)
        if self.telegram_id:
            log_event_to_mongo(
                self.telegram_id, "supervisor_logs",
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event": "failed_companies_saved",
                    "count": len(self.failed_companies),
                    "message": "Failed companies saved",
                }
            )

    # Sort all companies by final_score descending
    sorted_results = sorted(results, key=lambda x: x.final_score, reverse=True)

    # Create detailed data for all ranked companies
    all_data = []
    for match in sorted_results:
        all_data.append({
            "company": match.company,
            "final_score": match.final_score,
            "reasoning": match.reasoning,
            "address": self._get_company_field(match.company, "address"),
            "phone": self._get_company_field(match.company, "phone", nested_key="national"),
            # Add other fields/summaries as needed
        })

    df_all = pd.DataFrame(all_data)

    folder = self._get_folder_path()
    os.makedirs(folder, exist_ok=True)
    full_excel_path = os.path.join(folder, "all_ranked_companies.xlsx")
    df_all.to_excel(full_excel_path, index=False)

    # Create and save top 10 Excel
    top10_df = df_all.head(10)
    top10_excel_path = os.path.join(folder, "top_10_ranked_companies.xlsx")
    top10_df.to_excel(top10_excel_path, index=False)

    # Prepare markdown report for top 10 as before (optional)
    top10 = sorted_results[:10]
    md_path = os.path.join(folder, "all_ranked_companies.md")
    markdown = "# Top 10 Ranked Companies\n\n"
    for idx, comp in enumerate(top10, 1):
        markdown += (
            f"## {idx}. {comp.company}\n"
            f"- **Final Score**: {comp.final_score:.1f}\n"
            f"- **Reasoning**: {comp.reasoning}\n"
            f"- **Address**: {self._get_company_field(comp.company, 'address')}\n"
            f"- **Phone**: {self._get_company_field(comp.company, 'phone', nested_key='national')}\n\n"
        )
    markdown += (
        "---\n"
        f"Total Input Tokens: {self.total_input_tokens}\n\n"
        f"Total Output Tokens: {self.total_output_tokens}\n\n"
        f"Total Tokens: {self.total_input_tokens + self.total_output_tokens}\n\n"
        f"Estimated Cost: ${round((self.total_input_tokens + self.total_output_tokens) / 1000 * PERPLEXITY_COST_PER_1K, 6)}\n"
    )
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    # Optionally save JSON report locally
    report = {
        "ranked_companies": [
            {
                **match.dict(),
                "address": self._get_company_field(match.company, "address"),
                "phone": self._get_company_field(match.company, "phone", nested_key="national")
            }
            for match in top10
        ],
        "token_usage": {
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "estimated_cost_usd": round((self.total_input_tokens + self.total_output_tokens) / 1000 * PERPLEXITY_COST_PER_1K, 6)
        },
        "excel_paths": {
            "full": full_excel_path,
            "top10": top10_excel_path,
        }
    }
    save_output_locally(ExtractedData(company="all_ranked_companies", variable_data=report), folder)

    duration = time.time() - start
    logging.info(f"Processing time: {duration:.2f} seconds")
    logging.info(f"Token stats: input={self.total_input_tokens} output={self.total_output_tokens} cost=${report['token_usage']['estimated_cost_usd']}")

    if self.telegram_id:
        log_event_to_mongo(
            self.telegram_id, "supervisor_logs",
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": "ranking_completed",
                "total_companies": len(self.companies),
                "top_companies": [c.company for c in top10],
                "duration_seconds": duration,
                "message": "Ranking completed",
            }
        )

    # Return the full report including the Excel file paths
    return report


    def _save_company_output(self, match: CompanyMatchOutput):
        folder = self._get_folder_path()
        os.makedirs(folder, exist_ok=True)
        filename = sanitize_filename(match.company.lower()) + ".json"
        path = os.path.join(folder, filename)
        logging.info(f"Saving output for company: {match.company} at {path}")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(match.dict(), f, indent=4, ensure_ascii=False)

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

   