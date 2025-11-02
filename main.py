from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from datetime import time as dtime
from zoneinfo import ZoneInfo
import os
from dotenv import load_dotenv
from utils import update_db_with_api
from command_handlers import *
from send_messages import notify_job

load_dotenv()
TOKEN = os.getenv("BOT_API")
FOLLOWME_API_KEY = os.getenv("FOLLOWME_API")
app = (
    ApplicationBuilder()
    .token(TOKEN)
    .read_timeout(45)
    .write_timeout(45)
    .concurrent_updates(True)
    .build()
)

print("initial call initiated", flush=True)
update_db_with_api(
    api_key=FOLLOWME_API_KEY, bot_start=True
)  # to ensure no notifiactions at bot start
print("initial call finished", flush=True)


if __name__ == "__main__":
    print("Starting the bot...", flush=True)
    midnight_mle = dtime(0, 0, tzinfo=ZoneInfo("Indian/Maldives"))
    # app.job_queue.run_once(daily_stats, when=timedelta(seconds=10), name="daily stats")
    app.job_queue.run_repeating(notify_job, interval=15, first=3.0)

    # Command handlers
    # users
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addisland", subisland))
    app.add_handler(CommandHandler("addvessel", subvessel))
    app.add_handler(CommandHandler("settings", settings))
    app.add_handler(CommandHandler("unsub", unsub))
    app.add_handler(CommandHandler("listchannels", listchannels))
    app.add_handler(CommandHandler("islandstats", island_stats))
    app.add_handler(CommandHandler("vesselstats", vessel_stats))
    # admin
    app.add_handler(CommandHandler("addchannel", addchannel))
    app.add_handler(CommandHandler("channeladdvessel", channelsubvessel))
    app.add_handler(CommandHandler("channeladdisland", channelsubisland))

    app.add_handler(CallbackQueryHandler(callback_handler))

    # Handle all non-command messages
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, unrecognized_command)
    )

    app.run_polling()
