import firebase_admin
from firebase_admin import credentials, firestore



# Check if the default app is already initialized
try:
    if not firebase_admin._apps:
        cred = credentials.Certificate("./whatsapp-bot-696cf-firebase-adminsdk-n2lju-affeca18d1.json")
        firebase_admin.initialize_app(cred)
except Exception as e:
    print(e)
db = firestore.client()
