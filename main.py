from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
from openai import OpenAI
import os
from twilio.rest import Client
from dotenv import load_dotenv

# Load environment variables from a .env file if present
load_dotenv()

app = FastAPI()
openapi_client = OpenAI()

# Initialize Twilio client with environment variables
twilio_phone_number = os.getenv('TWILIO_PHONE_NUMBER')
twilio_client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))

chat_history = []

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
    global chat_history

    try:
        form_data = await request.form()
        message_body = form_data.get('Body')
        whatsapp_number = form_data.get('From').split("whatsapp:")[-1]

        # print(f"Received message from {whatsapp_number}: {message_body}")

        # Add the incoming message to the chat history
        chat_history.append({"role": "user", "content": message_body})

        # Define the system prompt
        system_prompt = (
            "### Instructions for Missing Items Collection Bot\n\n"
            "1. Greeting:\n"
            "- Begin with a clear greeting that states your role. For example, \"Hello! I'm here to help you report any missing items in our store.\"\n\n"
            "2. Inquiry About Missing Item:\n"
            "- Ask the user what specific item they are having trouble finding. If their description is too broad, ask for further clarification once to ensure you understand what they are looking for, keeping the process easy for the user.\n"
            "- Ask whether the item was previously available in the store or if it’s something new they would like to have in the shop.\n\n"
            "3. Item Collection:\n"
            "- Ensure you collect information about at least one missing item during the conversation.\n\n"
            "4. Notification and Email Collection:\n"
            "- After gathering the necessary details, inform the user that you will notify the manager and work to restock the item as soon as possible. Ask if they would like to be notified when the item is back on the shelf and request their email for this purpose.\n\n"
            "5. Email Handling:\n"
            "- If the user provides their email, thank them and confirm that you will reach out once the item is restocked. If they do not provide their email, simply proceed without it."
        )

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
        
        # print(f"Replying with: {reply_text}")
        send_message(whatsapp_number, reply_text)
        return ""
        
    except Exception as e:
        print(f"OpenAI API error: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error: OpenAI API error")

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000)
