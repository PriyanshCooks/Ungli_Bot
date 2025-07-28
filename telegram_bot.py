import os
import uuid
import asyncio
import logging
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

# --- MONGODB DB INFO ---
from pymongo import MongoClient
MONGODB_URL = "mongodb+srv://ayushsinghbasera:YEJTg3zhMwXJcTXm@cluster0.fmzrdga.mongodb.net/"
DB_NAME = "chatbot_db"
COLLECTION_NAME = "chat_sessions"

print("BOT STARTEDD")

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
        print(f"[NEW SESSION CREATED] Telegram ID: {telegram_user_id} | UserID: {user_sessions[telegram_user_id]['user_id']} | ChatID: {user_sessions[telegram_user_id]['chat_id']}")
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_or_create_session(update.effective_user.id)
    session["state"] = "await_website_prompt"
    await update.message.reply_text(
        "👋 Welcome! Let's get started.\n\nDo you have a company website?",
        reply_markup=get_yes_no_keyboard("website")
    )

async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    session = get_or_create_session(update.effective_user.id)
    print(f"[BUTTON CLICKED] {data} | State: {session['state']}")

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
        store_message(session["user_id"], old_chat_id, "", "Conversation reset by user.", role="system")
        store_message(session["user_id"], session["chat_id"], OPENAI_FIRST_QUESTION, "", role="assistant")
        await query.edit_message_text("🔁 Conversation reset!\n\n" + OPENAI_FIRST_QUESTION, reply_markup=get_main_keyboard())

    elif data == "end":
        print(f"[END] Conversation ended by user {session['user_id']}")
        if not session.get("pipeline_triggered"):
            session["pipeline_triggered"] = True
            await query.edit_message_text("⛔ Conversation ended by user. Triggering the pipeline...")
            store_message(session["user_id"], session["chat_id"], "", "Conversation ended by user.", role="system")

            async def run_and_notify():
                print(f"[PIPELINE] Triggering run_search_pipeline for user={session['user_id']} chat={session['chat_id']} session={session['session_uuid']}")
                await asyncio.to_thread(
                    run_search_pipeline,
                    user_id=session["user_id"], chat_id=session["chat_id"], session_uuid=session["session_uuid"]
                )
                print(f"[PIPELINE] Pipeline ended for user={session['user_id']}")
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="✅ Pipeline ended. Running company ranking..."
                )
                try:
                    xlsx_path = await run_supervisor_pipeline(
                        user_id=session["user_id"],
                        chat_id=session["chat_id"],
                        session_uuid=session["session_uuid"]
                    )
                    if xlsx_path and os.path.exists(xlsx_path):
                        await context.bot.send_document(
                            chat_id=query.message.chat_id,
                            document=open(xlsx_path, "rb"),
                            filename="all_ranked_companies.xlsx",
                            caption="🏆 Here are your ranked companies as an Excel sheet."
                        )
                        print("[SUPERVISOR] Ranking complete and Excel sent to user.")
                    else:
                        await context.bot.send_message(
                            chat_id=query.message.chat_id,
                            text="⚠️ Ranking completed but Excel file was not found."
                        )
                        print("[SUPERVISOR] No Excel file to send.")
                except Exception as e:
                    print(f"[SUPERVISOR ERROR] {e}")
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=f"⚠️ SupervisorAgent ranking failed: {e}"
                    )

            asyncio.create_task(run_and_notify())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    session = get_or_create_session(update.effective_user.id)
    user_id = session["user_id"]
    chat_id = session["chat_id"]

    if session["state"] == "await_website_input":
        session["website"] = user_input
        session["state"] = "await_brochure_prompt"
        save_company_website(session["user_id"], session["chat_id"], session["session_uuid"], user_input)
        await update.message.reply_text(
            "📎 Do you have a brochure (PDF)?",
            reply_markup=get_yes_no_keyboard("brochure")
        )
        print(f"[MESSAGE] From {user_id} | State: {session['state']} | Text: {user_input}")
        print(f"[WEBSITE SAVED] {user_input}")
        return

    if session["state"] == "qa_flow":
        store_message(user_id, chat_id, "", user_input, role="user")
        qa_log = get_qa_history(user_id, chat_id)
        history = build_history(qa_log)
        assistant_questions_count = len([m for m in qa_log if m["role"] == "assistant"])

        print(f"[MESSAGE] From {user_id} | State: {session['state']} | Text: {user_input}")

        if assistant_questions_count == 14:
            next_question = "Would you like to share anything else about the product which would help us find you even better matches?"
        elif assistant_questions_count >= 15:
            print(f"[QA COMPLETE] User {user_id} finished Q&A. Triggering pipeline for session={session['session_uuid']} chat={chat_id}")
            if not session.get("pipeline_triggered"):
                session["pipeline_triggered"] = True
                await update.message.reply_text("✅ Thanks! Triggering the pipeline...")

                async def run_and_notify():
                    print(f"[PIPELINE] Triggering run_search_pipeline for user={user_id} chat={chat_id} session={session['session_uuid']}")
                    await asyncio.to_thread(
                        run_search_pipeline,
                        user_id=user_id, chat_id=chat_id, session_uuid=session["session_uuid"]
                    )
                    print(f"[PIPELINE] Pipeline ended for user={user_id}")
                    await context.bot.send_message(
                        chat_id=update.message.chat_id,
                        text="✅ Pipeline ended. Running company ranking..."
                    )
                    try:
                        xlsx_path = await run_supervisor_pipeline(
                            user_id=user_id, chat_id=chat_id, session_uuid=session["session_uuid"]
                        )
                        if xlsx_path and os.path.exists(xlsx_path):
                            await context.bot.send_document(
                                chat_id=update.message.chat_id,
                                document=open(xlsx_path, "rb"),
                                filename="all_ranked_companies.xlsx",
                                caption="🏆 Here are your ranked companies as an Excel sheet."
                            )
                            print("[SUPERVISOR] Ranking complete and Excel sent to user.")
                        else:
                            await context.bot.send_message(
                                chat_id=update.message.chat_id,
                                text="⚠️ Ranking completed but Excel file was not found."
                            )
                            print("[SUPERVISOR] No Excel file to send.")
                    except Exception as e:
                        print(f"[SUPERVISOR ERROR] {e}")
                        await context.bot.send_message(
                            chat_id=update.message.chat_id,
                            text=f"⚠️ SupervisorAgent ranking failed: {e}"
                        )

                asyncio.create_task(run_and_notify())
            return
        else:
            next_question = generate_next_question(history, qa_log)
        store_message(user_id, chat_id, next_question, "", role="assistant")
        await update.message.reply_text(next_question, reply_markup=get_main_keyboard())
        return

    await update.message.reply_text("⚠️ Please follow the flow. Start with /start.")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_or_create_session(update.effective_user.id)
    file = update.message.document
    brochure_path = f"temp_brochure_{session['chat_id']}.pdf"
    tg_file = await file.get_file()
    await tg_file.download_to_drive(brochure_path)
    print(f"[BROCHURE RECEIVED] File saved to {brochure_path}")

    try:
        success, extracted_text = process_brochure(
            brochure_path,
            session["user_id"],
            session["chat_id"],
            session["session_uuid"]
        )
        if success:
            print(f"[BROCHURE PROCESSED] Length: {len(extracted_text)} | Saved to MongoDB")
            await update.message.reply_text("✅ Brochure received and processed successfully.")
        else:
            print("[BROCHURE ERROR] MongoDB update failed.")
            await update.message.reply_text("⚠️ Brochure processed but failed to update the database.")

        session["brochure_uploaded"] = True
        session["state"] = "qa_flow"
        store_message(session["user_id"], session["chat_id"], OPENAI_FIRST_QUESTION, "", role="assistant")
        await update.message.reply_text(
            OPENAI_FIRST_QUESTION,
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        print(f"[ERROR] Failed to process brochure: {e}")
        await update.message.reply_text(f"❌ Failed to process brochure: {e}")
    finally:
        if os.path.exists(brochure_path):
            os.remove(brochure_path)
        print(f"[CLEANUP] Temp file {brochure_path} removed.")

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
    print("🤖 Telegram bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
