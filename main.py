from fastapi import FastAPI, Form, Request, HTTPException, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from firebase_config import db
from openai import OpenAI
import os
from twilio.rest import Client
from dotenv import load_dotenv
from fastapi.templating import Jinja2Templates
from datetime import datetime
from typing import Optional
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables from a .env file if present
load_dotenv()

app = FastAPI()
templates = Jinja2Templates(directory="templates")
openapi_client = OpenAI()

# Initialize Twilio client with environment variables
twilio_phone_number = os.getenv('TWILIO_PHONE_NUMBER')
twilio_client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))

def get_system_prompt() -> str:
    """Retrieve the system prompt from Firestore."""
    try:
        doc_ref = db.collection("settings").document("system_prompt")
        doc = doc_ref.get()
        return doc.to_dict().get("prompt", "Default system prompt") if doc.exists else "Default system prompt"
    except Exception as e:
        logger.error(f"Error retrieving system prompt: {e}")
        return "Default system prompt"

def get_chat_history(phone_number: str) -> list:
    try:
        doc_ref = db.collection("conversations").document(phone_number)
        doc = doc_ref.get()
        return doc.to_dict().get("history", []) if doc.exists else []
    except Exception as e:
        logger.error(f"Error retrieving chat history: {e}")
        return []
    
def save_chat_history(phone_number: str, chat_history: list):
    """Save updated chat history for a specific phone number."""
    try:
        doc_ref = db.collection("conversations").document(phone_number)
        doc_ref.set({"history": chat_history})
    except Exception as e:
        logger.error(f"Error saving chat history: {e}")

def generate_openai_response(messages: list) -> str:
    """Generate a response from OpenAI GPT-4o."""
    try:
        response = openapi_client.chat.completions.create(
            model="gpt-4o-2024-08-06",
            messages=messages,
            max_tokens=200,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        return "Sorry, I couldn't process your request."

def send_message(to_number: str, body_text: str):
    """Send a message using Twilio's API."""
    try:
        message = twilio_client.messages.create(
            from_=f"whatsapp:{twilio_phone_number}",
            body=body_text,
            to=f"whatsapp:{to_number}"
        )
        logger.info(f"Message sent to {to_number}: {message.body}")
    except Exception as e:
        logger.error(f"Error sending message to {to_number}: {e}")

def group_messages(history: list, phone_number: str) -> list:
    grouped = []
    temp_pair = []
    for entry in history:
        if entry['role'] == 'user':
            if temp_pair:
                grouped.append(temp_pair)
            temp_pair = [{'role': phone_number, 'content': entry['content'], 'timestamp': entry.get('timestamp')}]
        elif entry['role'] == 'assistant':
            if temp_pair:
                temp_pair.append(entry)
                grouped.append(temp_pair)
                temp_pair = []
    if temp_pair:
        grouped.append(temp_pair)
    return grouped


@app.get("/", response_class=HTMLResponse)
async def get_edit_prompt(request: Request, message: str = None):
    """Retrieve and display the current system prompt."""
    try:
        current_prompt = get_system_prompt()
        return templates.TemplateResponse("edit_prompt.html", {
            "request": request,
            "current_prompt": current_prompt,
            "active_page": "home",
            "message": message
        })
    except Exception as e:
        logger.error(f"Error retrieving system prompt: {e}")
        return templates.TemplateResponse("edit_prompt.html", {
            "request": request,
            "current_prompt": "Default system prompt",
            "active_page": "home",
            "message": message
        })

@app.post("/")
async def post_edit_prompt(request: Request, system_prompt: str = Form(...)):
    """Update and save the system prompt."""
    try:
        doc_ref = db.collection("settings").document("system_prompt")
        doc_ref.set({"prompt": system_prompt})
        message = "System prompt updated successfully!"
        return templates.TemplateResponse("edit_prompt.html", {
            "request": request,
            "current_prompt": system_prompt,
            "active_page": "home",
            "message": message
        })
    except Exception as e:
        logger.error(f"Error saving system prompt: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error: Failed to save system prompt")


@app.get("/view-logs", response_class=HTMLResponse)
async def get_view_logs(request: Request, phone_number: Optional[str] = None, page: int = 1, per_page: int = 10):
    try:
        all_users = []

        if phone_number:
            # Fetch history for a specific phone number
            history = get_chat_history(phone_number)
            grouped_messages = group_messages(history, phone_number)
            all_users.append({
                'phone_number': phone_number,
                'messages': grouped_messages,
                'timestamp': max((entry.get('timestamp') for entry in history if entry.get('timestamp')), default=None)
            })
        else:
            ph_number = ""
            # Fetch history for all phone numbers
            docs = db.collection("conversations").stream()
            for doc in docs:
                ph_number = doc.id
                history = doc.to_dict().get("history", [])
                grouped_messages = group_messages(history, ph_number)
                all_users.append({
                    'phone_number': ph_number,
                    'messages': grouped_messages,
                    'timestamp': max((entry.get('timestamp') for entry in history if entry.get('timestamp')), default=None)
                })

        all_users.sort(key=lambda x: x['timestamp'], reverse=True)

        total_users = len(all_users)
        start_index = (page - 1) * per_page
        end_index = start_index + per_page
        paged_users = all_users[start_index:end_index]

        has_prev_page = page > 1
        has_next_page = end_index < total_users

        for user in paged_users:
            for group in user['messages']:
                for entry in group:
                    if 'timestamp' in entry:
                        try:
                            timestamp = datetime.fromisoformat(entry['timestamp'])
                            entry['formatted_timestamp'] = timestamp.strftime('%Y-%m-%d %H:%M:%S')
                        except ValueError:
                            entry['formatted_timestamp'] = 'Invalid timestamp'

        return templates.TemplateResponse("view_logs.html", {
            "request": request,
            "users": paged_users,
            "page": page,
            "per_page": per_page,
            "total_users": total_users,
            "has_prev_page": has_prev_page,
            "has_next_page": has_next_page,
            "phone_number": phone_number if phone_number else None,
            "active_page": "logs"
        })
    except Exception as e:
        logger.error(f"Error retrieving logs: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error: Failed to retrieve logs")

@app.post("/webhook")
async def whatsapp_webhook(request: Request):
    """Handle incoming WhatsApp messages and generate responses."""
    try:
        form_data = await request.form()
        message_body = form_data.get('Body')
        whatsapp_number = form_data.get('From').split("whatsapp:")[-1]

        chat_history = get_chat_history(whatsapp_number)
        chat_history.append({
            "role": "user",
            "content": message_body,
            "timestamp": datetime.now().isoformat()  # Add timestamp here
        })

        system_prompt = get_system_prompt()
        messages = [{"role": "system", "content": system_prompt}] + chat_history

        reply_text = generate_openai_response(messages)
        chat_history.append({
            "role": "assistant",
            "content": reply_text,
            "timestamp": datetime.now().isoformat()  # Add timestamp here
        })

        save_chat_history(whatsapp_number, chat_history)
        send_message(whatsapp_number, reply_text)

        return ""

    except Exception as e:
        logger.error(f"Error in webhook processing: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error: Webhook processing error")
