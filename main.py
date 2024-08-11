from fastapi import FastAPI, Form, Request, HTTPException
from fastapi.responses import RedirectResponse
from firebase_config import db
from openai import OpenAI
import os
from twilio.rest import Client
from dotenv import load_dotenv
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

# Load environment variables from a .env file if present
load_dotenv()

app = FastAPI()
templates = Jinja2Templates(directory="templates")
openapi_client = OpenAI()


# Initialize Twilio client with environment variables
twilio_phone_number = os.getenv('TWILIO_PHONE_NUMBER')
twilio_client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))


@app.get("/", response_class=HTMLResponse)
async def get_edit_prompt(request: Request):
    try:
        # Retrieve the system prompt from Firestore
        doc_ref = db.collection("settings").document("system_prompt")
        doc = doc_ref.get()

        # Check if the document exists and has valid data
        if doc.exists and doc.to_dict() is not None:
            current_prompt = doc.to_dict().get("prompt", "Default system prompt")
        else:
            current_prompt = "Default system prompt"

    except Exception as e:
        print(f"Error retrieving system prompt: {e}")
        current_prompt = "Default system prompt"

    return templates.TemplateResponse("edit_prompt.html", {"request": request, "current_prompt": current_prompt})


@app.post("/")
async def post_edit_prompt(system_prompt: str = Form(...)):
    try:
        # Store the updated system prompt in Firestore
        doc_ref = db.collection("settings").document("system_prompt")
        doc_ref.set({"prompt": system_prompt})

        # Redirect to the home page with a success message
        return RedirectResponse(url="/?message=System%20prompt%20updated%20successfully!", status_code=302)

    except Exception as e:
        print(f"Error saving system prompt: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error: Failed to save system prompt")



@app.get("/view-logs", response_class=HTMLResponse)
async def get_view_logs(request: Request, phone_number: str = None):
    try:
        logs = []
        if phone_number:
            # Retrieve logs for a specific phone number from Firestore
            doc_ref = db.collection("conversations").document(phone_number)
            doc = doc_ref.get()
            if doc.exists:
                logs.append({"phone_number": phone_number, **doc.to_dict()})
        else:
            # Retrieve all logs
            docs = db.collection("conversations").stream()
            for doc in docs:
                logs.append({"phone_number": doc.id, **doc.to_dict()})
                
        print(f"Logs retrieved: {logs}")
        return templates.TemplateResponse("view_logs.html", {"request": request, "logs": logs, "phone_number": phone_number})

    except Exception as e:
        print(f"Error retrieving logs: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error: Failed to retrieve logs")


def send_message(to_number, body_text):
    try:
        # Send the message using Twilio's API
        message = twilio_client.messages.create(
            from_=f"whatsapp:{twilio_phone_number}",
            body=body_text,
            to=f"whatsapp:{to_number}"
        )
        print(f"Message sent to {to_number}: {message.body}")
    except Exception as e:
        print(f"Error sending message to {to_number}: {e}")


@app.post("/webhook")
async def whatsapp_webhook(request: Request):
    try:
        form_data = await request.form()
        message_body = form_data.get('Body')
        whatsapp_number = form_data.get('From').split("whatsapp:")[-1]

        # Retrieve the existing chat history for this phone number
        doc_ref = db.collection("conversations").document(whatsapp_number)
        doc = doc_ref.get()
        chat_history = doc.to_dict().get("history", []) if doc.exists and doc.to_dict() is not None else []

        # Add the incoming message to the chat history
        chat_history.append({"role": "user", "content": message_body})

        # Retrieve the system prompt from Firestore
        prompt_doc_ref = db.collection("settings").document("system_prompt")
        prompt_doc = prompt_doc_ref.get()
        system_prompt = prompt_doc.to_dict().get("prompt", "") if prompt_doc.exists and prompt_doc.to_dict() is not None else ""

        # Create the prompt with system instructions and chat history
        messages = [{"role": "system", "content": system_prompt}] + chat_history

        # Call OpenAI GPT-4o-2024-08-06 chat model to generate a response
        response = openapi_client.chat.completions.create(
            model="gpt-4o-2024-08-06",
            messages=messages,
            max_tokens=200,
            temperature=0.7
        )

        reply_text = response.choices[0].message.content.strip()

        # Store the updated chat history back in Firestore
        doc_ref.set({"history": chat_history})

        # Send the generated response to the user
        send_message(whatsapp_number, reply_text)
        return ""

    except Exception as e:
        print(f"OpenAI API error: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error: OpenAI API error")


# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000)