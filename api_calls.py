import time
from utils import update_db_with_api
import os
from dotenv import load_dotenv

load_dotenv()
FOLLOWME_API_KEY = os.getenv("FOLLOWME_API")

while True:
    print("Api update starting...", flush=True)
    try:
        update_db_with_api(FOLLOWME_API_KEY)
        print("Api update done", flush=True)
        print("_" * 50 + "\n", flush=True)
    except:
        print("API update failed", flush=True)
    time.sleep(60)
