import requests
import config
import json

# Use the key from your config file
KEY = config.CRYPTOPANIC_TOKEN
URL = "https://cryptopanic.com/api/v1/posts/"

# --- THE DISGUISE (User-Agent) ---
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

PARAMS = {
    "auth_token": KEY,
    "public": "true"
}

print(f"🔑 Testing Key: {KEY}")
print(f"📡 Connecting to: {URL}")

try:
    # Send request with HEADERS
    response = requests.get(URL, headers=HEADERS, params=PARAMS)
    
    print(f"📄 Status Code: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print("✅ SUCCESS! API is working.")
        print("-" * 30)
        print(f"Latest News: {data['results'][0]['title']}")
        print("-" * 30)
    else:
        print("❌ FAILED.")
        print(f"Reason: {response.reason}")
        
except Exception as e:
    print(f"❌ Error: {e}")
