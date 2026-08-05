import os
from dotenv import load_dotenv
load_dotenv()
gemmini_api_key = os.getenv("GEMINI_API_KEY", "")

print("gemmini_api_key : ", gemmini_api_key)