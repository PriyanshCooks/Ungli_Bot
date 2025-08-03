import os
import sys
import uuid
import asyncio
import logging
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    filters,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
)
from front_end_llm.utils import (
    get_chat_session, get_qa_history, build_history,
    store_message, generate_next_question,
)
from back_end_llm import run_search_pipeline
from supervisor import run_supervisor_pipeline
from pdf_extract.brochure_extract import process_brochure


from supervisor.utils import log_event_to_mongo


from pymongo import MongoClient
MONGODB_URL = "mongodb+srv://ayushsinghbasera:YEJTg3zhMwXJcTXm@cluster0.fmzrdga.mongodb.net/"
DB_NAME = "chatbot_db"
COLLECTION_NAME = "chat_sessions"
EXCEL_DB_NAME = "bot_excel_reports_db"
EXCEL_COLLECTION_NAME = "bot_excel_reports"


os.environ["TESSDATA_PREFIX"] = "/usr/local/share/tessdata/"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("scraper.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
original_print = print  # <--- save the original print!


def log(*args, **kwargs):
    msg = " ".join(str(a) for a in args)
    original_print(msg, **kwargs)
    logging.info(msg)


print = log



def mark_user_completed(telegram_id):
    client = MongoClient(MONGODB_URL)
    db = client[DB_NAME]
    col = db[COLLECTION_NAME]
    col.update_one(
        {"telegram_id": telegram_id},
        {"$set": {"completed": True}},
        upsert=True
    )



def has_user_completed(telegram_id):
    client = MongoClient(MONGODB_URL)
    db = client[DB_NAME]
    col = db[COLLECTION_NAME]
    return col.find_one({"telegram_id": telegram_id, "completed": True}) is not None



def save_company_website(user_id, chat_id, session_uuid, website):
    client = MongoClient(MONGODB_URL)
    db = client[DB_NAME]
    col = db[COLLECTION_NAME]
    query = {
        "user_id": user_id,
        "session_uuid": session_uuid,
        f"chats.{chat_id}": {"$exists": True}
    }
    update = {"$set": {f"chats.{chat_id}.company_website": website}}
    result = col.update_one(query, update)
    if result.modified_count == 0:
        fallback_data = {
            "user_id": user_id,
            "session_uuid": session_uuid,
            "chats": {
                chat_id: {
                    "company_website": website
                }
            }
        }
        col.insert_one(fallback_data)


OPENAI_FIRST_QUESTION = "What is your product and what does it do?"


user_sessions = {}


def get_or_create_session(telegram_user_id: int):
    if has_user_completed(telegram_user_id):
        return None
    if telegram_user_id not in user_sessions:
        user_sessions[telegram_user_id] = {
            "user_id": str(uuid.uuid4()),
            "chat_id": str(uuid.uuid4()),
            "session_uuid": str(uuid.uuid4()),
            "state": "await_website_prompt",
            "website": None,
            "brochure_uploaded": False,
            "pipeline_triggered": False
        }
        log(f"[NEW SESSION CREATED] Telegram ID: {telegram_user_id} | UserID: {user_sessions[telegram_user_id]['user_id']} | ChatID: {user_sessions[telegram_user_id]['chat_id']}")
        # Log session creation
        log_event_to_mongo(
            telegram_id=telegram_user_id,
            log_type="bot_logs",
            event_data={
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": "session_created",
                "message": "New user session created."
            }
        )
        # Also insert initial empty chat for that chat_id in Mongo
        client = MongoClient(MONGODB_URL)
        db = client[DB_NAME]
        col = db[COLLECTION_NAME]
        col.update_one(
            {
                "user_id": user_sessions[telegram_user_id]["user_id"],
                "session_uuid": user_sessions[telegram_user_id]["session_uuid"],
            },
            {
                "$setOnInsert": {
                    "user_id": user_sessions[telegram_user_id]["user_id"],
                    "session_uuid": user_sessions[telegram_user_id]["session_uuid"],
                },
                "$set": {f"chats.{user_sessions[telegram_user_id]['chat_id']}": {}},
            },
            upsert=True,
        )
    return user_sessions[telegram_user_id]



def get_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 Reset", callback_data="reset")],
        [InlineKeyboardButton("⛔ End Conversation", callback_data="end")],
    ])



def get_yes_no_keyboard(prefix):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data=f"{prefix}_yes")],
        [InlineKeyboardButton("❌ No", callback_data=f"{prefix}_no")],
    ])



def save_excel_to_db(telegram_id, user_id, session_uuid, chat_id, excel_path, filename='all_ranked_companies.xlsx'):
    client = MongoClient(MONGODB_URL)
    db = client[EXCEL_DB_NAME]
    col = db[EXCEL_COLLECTION_NAME]
    with open(excel_path, "rb") as f:
        excel_bytes = f.read()
    record = {
        "telegram_id": telegram_id,
        "user_id": user_id,
        "session_uuid": session_uuid,
        "chat_id": chat_id,
        "filename": filename,
        "file_data": excel_bytes,
        "timestamp": datetime.utcnow()
    }
    col.insert_one(record)
    logging.info(f"[DB] Excel file {filename} saved to DB for user {telegram_id}.")
    log_event_to_mongo(
        telegram_id=telegram_id,
        log_type="bot_logs",
        event_data={
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "excel_saved_to_db",
            "filename": filename,
            "message": "Excel rankings saved to DB"
        }
    )



async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if has_user_completed(telegram_id):
        await update.message.reply_text("⚠️ You have already completed your session! Only one run is allowed per user.")
        return
    session = get_or_create_session(telegram_id)
    session["state"] = "await_website_prompt"


    log_event_to_mongo(
        telegram_id=telegram_id,
        log_type="bot_logs",
        event_data={
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "bot_start",
            "message": "User started the bot."
        }
    )


    await update.message.reply_text(
        "👋 Welcome! Let's get started.\n\nDo you have a company website?",
        reply_markup=get_yes_no_keyboard("website")
    )



async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    session = get_or_create_session(update.effective_user.id)
    if session is None:
        await query.edit_message_text("⚠️ You have already completed your session! Only one run is allowed per user.")
        return
    log(f"[BUTTON CLICKED] {data} | State: {session['state']}")


    log_event_to_mongo(
        telegram_id=update.effective_user.id,
        log_type="bot_logs",
        event_data={
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "button_clicked",
            "button": data,
            "state": session["state"],
            "message": f"User clicked button: {data}"
        }
    )


    if data == "website_yes":
        session["state"] = "await_website_input"
        await query.edit_message_text("🌐 Please enter the company website URL.")


    elif data == "website_no":
        session["state"] = "await_brochure_prompt"
        await query.edit_message_text(
            "📎 Do you have a brochure (PDF)?", reply_markup=get_yes_no_keyboard("brochure")
        )


    elif data == "brochure_yes":
        session["state"] = "await_brochure_upload"
        await query.edit_message_text("📎 Please upload the brochure file now (PDF).")


    elif data == "brochure_no":
        session["state"] = "qa_flow"
        await query.edit_message_text("✅ Thanks! Let's begin.")
        await begin_qa_flow(update, session)


    elif data == "reset":
        old_chat_id = session["chat_id"]
        session["chat_id"] = str(uuid.uuid4())
        session["state"] = "qa_flow"
        # Initialize empty new chat under new chat_id in Mongo immediately!
        client = MongoClient(MONGODB_URL)
        db = client[DB_NAME]
        col = db[COLLECTION_NAME]
        col.update_one(
            {
                "user_id": session["user_id"],
                "session_uuid": session["session_uuid"],
            },
            {
                "$set": {f"chats.{session['chat_id']}": {}}
            },
            upsert=True
        )
        store_message(session["user_id"], old_chat_id, "", "Conversation reset by user.", role="system")
        store_message(session["user_id"], session["chat_id"], OPENAI_FIRST_QUESTION, "", role="assistant")
        await query.edit_message_text("🔁 Conversation reset!\n\n" + OPENAI_FIRST_QUESTION, reply_markup=get_main_keyboard())


    elif data == "end":
        log(f"[END] Conversation ended by user {session['user_id']}")
        log_event_to_mongo(
            telegram_id=update.effective_user.id,
            log_type="bot_logs",
            event_data={
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": "conversation_end",
                "message": "User ended the conversation."
            }
        )
        if not session.get("pipeline_triggered"):
            session["pipeline_triggered"] = True
            await query.edit_message_text("⛔ Conversation ended by user. Triggering the pipeline...")
            store_message(session["user_id"], session["chat_id"], "", "Conversation ended by user.", role="system")


            async def run_and_notify():
                try:
                    # ---- SANITY CHECK BEFORE PIPELINE ----
                    client = MongoClient(MONGODB_URL)
                    col = client[DB_NAME][COLLECTION_NAME]
                    exists = col.find_one({
                        "user_id": session["user_id"],
                        "session_uuid": session["session_uuid"],
                        f"chats.{session['chat_id']}": {"$exists": True}
                    })
                    if not exists:
                        log(f"[ERROR] No valid session/chat in Mongo for user={session['user_id']} session={session['session_uuid']} chat={session['chat_id']}")
                        await context.bot.send_message(
                            chat_id=query.message.chat_id,
                            text="⚠️ Internal error: No valid session history found. Please /start over."
                        )
                        return
                    log(f"[PIPELINE] Triggering run_search_pipeline for user={session['user_id']} chat={session['chat_id']} session={session['session_uuid']}")
                    await asyncio.to_thread(
                        run_search_pipeline,
                        user_id=session["user_id"], chat_id=session["chat_id"], session_uuid=session["session_uuid"]
                    )
                    log(f"[PIPELINE] Pipeline ended for user={session['user_id']}")


                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text="✅ Pipeline ended. Running company ranking..."
                    )
                    try:
                        xlsx_report = await run_supervisor_pipeline(
                            user_id=session["user_id"],
                            chat_id=session["chat_id"],
                            session_uuid=session["session_uuid"],
                            telegram_id=update.effective_user.id
                        )

                        if xlsx_report and "excel_paths" in xlsx_report:
                            full_xlsx_path = xlsx_report["excel_paths"]["full"]
                            top10_xlsx_path = xlsx_report["excel_paths"]["top10"]

                            # Save full Excel to DB
                            save_excel_to_db(
                                telegram_id=update.effective_user.id,
                                user_id=session["user_id"],
                                session_uuid=session["session_uuid"],
                                chat_id=session["chat_id"],
                                excel_path=full_xlsx_path,
                                filename="all_ranked_companies.xlsx"
                            )

                            # Send only top 10 Excel to user
                            if os.path.exists(top10_xlsx_path):
                                with open(top10_xlsx_path, "rb") as top10_file:
                                    await context.bot.send_document(
                                        chat_id=query.message.chat_id,
                                        document=top10_file,
                                        filename="top_10_ranked_companies.xlsx",
                                        caption="🏆 Here are the top 10 ranked companies as an Excel sheet. To unlock the complete list of leads, contact: 8800793038"
                                    )
                            else:
                                await context.bot.send_message(
                                    chat_id=query.message.chat_id,
                                    text="⚠️ Ranking completed but top 10 Excel file was not found."
                                )

                            mark_user_completed(update.effective_user.id)
                        else:
                            await context.bot.send_message(
                                chat_id=query.message.chat_id,
                                text="⚠️ Ranking completed but Excel files were not found."
                            )
                            log("[SUPERVISOR] No Excel file to send.")
                    except Exception as e:
                        log(f"[SUPERVISOR ERROR] {e}")
                        await context.bot.send_message(
                            chat_id=query.message.chat_id,
                            text="Sorry, we encountered an error. Please try again later."
                        )
                except Exception as ex:
                    log(f"[BOT ERROR] {ex}")
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text="Sorry, we encountered an error. Please try again later."
                    )
            asyncio.create_task(run_and_notify())




async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_input = update.message.text
        session = get_or_create_session(update.effective_user.id)
        if session is None:
            await update.message.reply_text("⚠️ You have already completed your session! Only one run is allowed per user.")
            return

        user_id = session["user_id"]
        chat_id = session["chat_id"]

        log_event_to_mongo(
            telegram_id=update.effective_user.id,
            log_type="bot_logs",
            event_data={
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": "user_message",
                "message": user_input,
                "state": session["state"]
            }
        )

        if session["state"] == "await_website_input":
            session["website"] = user_input
            session["state"] = "await_brochure_prompt"
            save_company_website(session["user_id"], session["chat_id"], session["session_uuid"], user_input)
            await update.message.reply_text(
                "📎 Do you have a brochure (PDF)?",
                reply_markup=get_yes_no_keyboard("brochure")
            )
            log(f"[MESSAGE] From {user_id} | State: {session['state']} | Text: {user_input}")
            log(f"[WEBSITE SAVED] {user_input}")
            return

        if session["state"] == "qa_flow":
            store_message(user_id, chat_id, "", user_input, role="user")

            qa_log = get_qa_history(user_id, chat_id)
            history = build_history(qa_log)
            assistant_questions_count = len([m for m in qa_log if m["role"] == "assistant"])

            log(f"[MESSAGE] From {user_id} | State: {session['state']} | Text: {user_input} | assistant_questions_count={assistant_questions_count}")

            if assistant_questions_count == 0:
                store_message(user_id, chat_id, OPENAI_FIRST_QUESTION, "", role="assistant")
                await update.message.reply_text(OPENAI_FIRST_QUESTION, reply_markup=get_main_keyboard())
                return

            next_question = generate_next_question(history, qa_log)
            if not next_question or not next_question.strip():
                next_question = "Can you tell me more details about your product, customers, market or applications?"

            ENDING_SIGNALS = [
                "thank you", "thanks", "all the questions", "that's all", "thank you for providing",
                "have a great day", "conversation ended",
            ]

            # If fewer than 10 questions asked, always continue asking
            if assistant_questions_count < 10:
                store_message(user_id, chat_id, next_question, "", role="assistant")
                await update.message.reply_text(next_question, reply_markup=get_main_keyboard())
                return

            # After 10 questions, check if next question contains any ending signal,
            # Bot determines if info is likely sufficient to end conversation early
            elif 10 <= assistant_questions_count < 15:
                nq_lower = next_question.lower().strip()
                if any(signal in nq_lower for signal in ENDING_SIGNALS):
                    await update.message.reply_text(
                        "Based on your responses, it seems I have enough information. If you'd like to stop, please press the 'End Conversation' button. Otherwise, you can keep providing more details.",
                        reply_markup=get_main_keyboard()
                    )
                    return
                else:
                    store_message(user_id, chat_id, next_question, "", role="assistant")
                    await update.message.reply_text(next_question, reply_markup=get_main_keyboard())
                    return

            # After 15 questions, force end of bot asking (user can still end anytime via button)
            elif assistant_questions_count >= 15:
                await update.message.reply_text(
                    "I've asked the maximum number of questions (15). Please press the 'End Conversation' button if you'd like to finish, or you can restart the conversation.",
                    reply_markup=get_main_keyboard()
                )
                # Optionally, update session state to stop further bot questions:
                session["state"] = "completed"
                mark_user_completed(update.effective_user.id)
                return

        await update.message.reply_text("⚠️ Please follow the flow. Start with /start.")

    except Exception as e:
        log(f"[BOT ERROR] {e}")
        await update.message.reply_text("Sorry, we encountered an error. Please try again later.")



async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_or_create_session(update.effective_user.id)
    file = update.message.document
    brochure_path = f"temp_brochure_{session['chat_id']}.pdf"
    tg_file = await file.get_file()
    await tg_file.download_to_drive(brochure_path)
    log(f"[BROCHURE RECEIVED] File saved to {brochure_path}")


    log_event_to_mongo(
        telegram_id=update.effective_user.id,
        log_type="bot_logs",
        event_data={
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "brochure_uploaded",
            "message": f"User uploaded brochure {file.file_name}"
        }
    )


    try:
        success, extracted_text = process_brochure(
            brochure_path,
            session["user_id"],
            session["chat_id"],
            session["session_uuid"]
        )
        if success:
            log(f"[BROCHURE PROCESSED] Length: {len(extracted_text)} | Saved to MongoDB")
            await update.message.reply_text("✅ Brochure received and processed successfully.")
        else:
            log("[BROCHURE ERROR] MongoDB update failed.")
            await update.message.reply_text("⚠️ Brochure processed but failed to update the database.")


        session["brochure_uploaded"] = True
        session["state"] = "qa_flow"
        store_message(session["user_id"], session["chat_id"], OPENAI_FIRST_QUESTION, "", role="assistant")
        await update.message.reply_text(
            OPENAI_FIRST_QUESTION,
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        log(f"[ERROR] Failed to process brochure: {e}")
        log_event_to_mongo(
            telegram_id=update.effective_user.id,
            log_type="bot_logs",
            event_data={
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": "brochure_error",
                "message": str(e)
            }
        )
        await update.message.reply_text("Sorry, we encountered an error. Please try again later.")
    finally:
        if os.path.exists(brochure_path):
            os.remove(brochure_path)
        log(f"[CLEANUP] Temp file {brochure_path} removed.")



async def begin_qa_flow(update: Update, session: dict):
    store_message(session["user_id"], session["chat_id"], OPENAI_FIRST_QUESTION, "", role="assistant")
    await update.effective_message.reply_text(OPENAI_FIRST_QUESTION, reply_markup=get_main_keyboard())



def main():
    TOKEN = os.getenv("TELEGRAM_TOKEN")
    if not TOKEN:
        raise ValueError("Please set TELEGRAM_TOKEN in .env")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_file))
    app.add_handler(CallbackQueryHandler(handle_button))
    log("🤖 Telegram bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
