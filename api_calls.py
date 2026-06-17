import time
from utils import update_db_with_api
import os
from dotenv import load_dotenv
from models import PortLog

load_dotenv()
FOLLOWME_API_KEY = os.getenv("FOLLOWME_API")


def main():
    try:
        while True:
            start_time = time.time()
            print("Api update starting...", flush=True)
            try:
                update_db_with_api(FOLLOWME_API_KEY)
                print("Api update done", flush=True)
                
                # Clean up old PortLog rows to keep table under 100k rows
                deleted = PortLog.cleanup_old_rows()
                if deleted > 0:
                    print(f"Cleaned up {deleted} old portlog rows", flush=True)
            except Exception as e:
                print(f"API update failed: {str(e)}", flush=True)

            # Calculate how long to wait until next update
            elapsed_time = time.time() - start_time
            wait_time = max(
                60 - elapsed_time, 0
            )  # ensure we don't get negative wait time
            print(f"Waiting {wait_time:.1f} seconds until next update")
            print("_" * 50 + "\n", flush=True)
            time.sleep(wait_time)
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")


if __name__ == "__main__":
    main()
