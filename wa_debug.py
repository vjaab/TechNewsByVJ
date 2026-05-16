import os
import requests
from dotenv import load_dotenv

load_dotenv()

def test_whatsapp():
    token = os.getenv('WHATSAPP_ACCESS_TOKEN')
    phone_id = os.getenv('WHATSAPP_PHONE_NUMBER_ID')
    recipient = os.getenv('WHATSAPP_RECIPIENT_PHONE_NUMBER')
    
    print(f"Token: {token[:10]}...")
    print(f"Phone ID: {phone_id}")
    
    url = f"https://graph.facebook.com/v22.0/{phone_id}/messages"
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "text",
        "text": {"body": "Button Test"}
    }
    
    r = requests.post(url, headers=headers, json=payload)
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text}")

test_whatsapp()
