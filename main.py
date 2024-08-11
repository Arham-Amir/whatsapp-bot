import logging
from fastapi import FastAPI, Form, Request, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from firebase_config import db
from openai import OpenAI
import os
from twilio.rest import Client
from dotenv import load_dotenv
from fastapi.templating import Jinja2Templates

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
    """Retrieve chat history for a specific phone number."""
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


@app.get("/", response_class=HTMLResponse)
async def get_edit_prompt(request: Request):
    """Retrieve and display the current system prompt."""
    try:
        current_prompt = get_system_prompt()
        return templates.TemplateResponse("edit_prompt.html", {
            "request": request,
            "current_prompt": current_prompt,
            "active_page": "home"
        })
    except Exception as e:
        logger.error(f"Error retrieving system prompt: {e}")
        return templates.TemplateResponse("edit_prompt.html", {
            "request": request,
            "current_prompt": "Default system prompt",
            "active_page": "home"
        })


@app.post("/")
async def post_edit_prompt(system_prompt: str = Form(...)):
    """Update and save the system prompt."""
    try:
        doc_ref = db.collection("settings").document("system_prompt")
        doc_ref.set({"prompt": system_prompt})
        return RedirectResponse(url="/?message=System%20prompt%20updated%20successfully!", status_code=302)
    except Exception as e:
        logger.error(f"Error saving system prompt: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error: Failed to save system prompt")


@app.get("/view-logs", response_class=HTMLResponse)
async def get_view_logs(request: Request, phone_number: str = None):
    """Retrieve and display logs for a specific phone number or all logs."""
    try:
        logs = []
        if phone_number:
            doc_ref = db.collection("conversations").document(phone_number)
            doc = doc_ref.get()
            if doc.exists:
                logs.append({"phone_number": phone_number, **doc.to_dict()})
        else:
            docs = db.collection("conversations").stream()
            for doc in docs:
                logs.append({"phone_number": doc.id, **doc.to_dict()})

        logger.info(f"Logs retrieved: {logs}")
        return templates.TemplateResponse("view_logs.html", {
            "request": request,
            "logs": logs,
            "phone_number": phone_number,
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
        chat_history.append({"role": "user", "content": message_body})

        system_prompt = get_system_prompt()
        messages = [{"role": "system", "content": system_prompt}] + chat_history

        reply_text = generate_openai_response(messages)
        chat_history.append({"role": "assistant", "content": reply_text})

        save_chat_history(whatsapp_number, chat_history)
        send_message(whatsapp_number, reply_text)

        return ""

    except Exception as e:
        logger.error(f"Error in webhook processing: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error: Webhook processing error")


# Uncomment if running locally
# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000)
