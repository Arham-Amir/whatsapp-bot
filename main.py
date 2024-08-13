from typing import Optional
import bcrypt
from fastapi import FastAPI, Form, Request, HTTPException, Depends, status
from fastapi.responses import RedirectResponse, HTMLResponse
from firebase_config import db  # Firebase Firestore configuration
from openai import OpenAI
from fastapi.templating import Jinja2Templates
from passlib.context import CryptContext
from twilio.rest import Client
import os
import uuid
from dotenv import load_dotenv
from datetime import datetime, timedelta
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables from a .env file
load_dotenv()

app = FastAPI()
templates = Jinja2Templates(directory="templates")
openapi_client = OpenAI()

# Initialize Twilio client with environment variables
twilio_phone_number = os.getenv('TWILIO_PHONE_NUMBER')
twilio_client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))


# Password hashing context

APP_USERNAME = os.getenv("APP_USERNAME")
APP_PASSWORD_HASH = os.getenv("APP_PASSWORD_HASH")


async def get_current_user(request: Request):
    session_id = request.cookies.get("session_id")
    
    if not session_id:
        return None  # User is not authenticated

    # Check if the session exists in Firestore
    session_ref = db.collection("user_sessions").document(session_id)
    session_doc = session_ref.get()
    
    if not session_doc.exists or not session_doc.to_dict().get("authenticated"):
        return None  # Session is not valid or not authenticated

    return session_doc.to_dict().get("username")

async def require_authentication(request: Request):
    # user = await get_current_user(request)
    # if user is None:
    #     raise HTTPException(
    #         status_code=status.HTTP_302_FOUND,
    #         detail="Not authenticated",
    #         headers={"Location": "/signin"}
    #     )
    
    return True

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed_password.decode('utf-8')

def verify_password(password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))

def get_session_from_db(session_id):
    """Retrieve session data from Firebase."""
    try:
        doc_ref = db.collection("user_sessions").document(session_id)
        doc = doc_ref.get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        logger.error(f"Error retrieving session from Firebase: {e}")
        return None

def save_session_to_db(session_id, session_data):
    """Save session data to Firebase."""
    try:
        db.collection("user_sessions").document(session_id).set(session_data)
    except Exception as e:
        logger.error(f"Error saving session to Firebase: {e}")

def delete_session_from_db(session_id):
    """Delete session data from Firebase."""
    try:
        db.collection("user_sessions").document(session_id).delete()
    except Exception as e:
        logger.error(f"Error deleting session from Firebase: {e}")

def authenticate_user(username: str, password: str):
    """Check if the provided username and password are correct."""
    if username == APP_USERNAME and verify_password(password, APP_PASSWORD_HASH):
        return True
    return False

def create_session(username: str):
    """Create a new session and store it in Firebase."""
    session_id = str(uuid.uuid4())
    session_data = {
        "username": username,
        "created_at": datetime.now().isoformat(),
        "expires_at": (datetime.now() + timedelta(hours=1)).isoformat(),  # Set session expiry
        "authenticated": True
    }
    save_session_to_db(session_id, session_data)
    return session_id

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


@app.get("/signin", response_class=HTMLResponse)
async def get_signin(request: Request, user: str = Depends(get_current_user)):
    # If the user is authenticated, redirect to the home page
    if user:
        return RedirectResponse("/", status_code=303)
    # Otherwise, return the sign-in page
    return templates.TemplateResponse("signin.html", {"request": request})

@app.post("/signin")
async def post_signin(request: Request, username: str = Form(...), password: str = Form(...)):
    if authenticate_user(username, password):
        session_id = create_session(username)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(key="session_id", value=session_id, httponly=True, max_age=3600)
        return response
    else:
        return templates.TemplateResponse("signin.html", {
            "request": request,
            "error": "Invalid username or password"
        })


@app.get("/signout")
async def signout(request: Request):
    session_id = request.cookies.get("session_id")
    if session_id:
        delete_session_from_db(session_id)
    response = RedirectResponse("/signin", status_code=303)
    response.delete_cookie("session_id")
    return response

@app.get("/", response_class=HTMLResponse)
async def get_edit_prompt(request: Request, message: str = None, user: str = Depends(require_authentication)):
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
async def post_edit_prompt(request: Request, system_prompt: str = Form(...), user: str = Depends(require_authentication)):
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
async def get_view_logs(request: Request, phone_number: Optional[str] = None, page: int = 1, per_page: int = 10, user: str = Depends(require_authentication)):
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
