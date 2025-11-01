import time
from utils import update_db_with_api
import os
from dotenv import load_dotenv

load_dotenv()
FOLLOWME_API_KEY = os.getenv("FOLLOWME_API")

while True:
    print("Api update starting...")
    try:
        update_db_with_api(FOLLOWME_API_KEY)
        print("Api update done")
        print("_" * 50 + "\n")
    except:
        print("API update failed")
    time.sleep(60)
