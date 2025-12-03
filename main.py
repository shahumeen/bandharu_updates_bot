from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
)
from telegram import BotCommand
from datetime import time as dtime
from zoneinfo import ZoneInfo
import os
from handlers import *
from send_messages import notify_job

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

if __name__ == "__main__":
    print("Starting the bot...", flush=True)
    midnight_mle = dtime(0, 0, tzinfo=ZoneInfo("Indian/Maldives"))
    # app.job_queue.run_once(daily_stats, when=timedelta(seconds=10), name="daily stats")
    app.job_queue.run_repeating(notify_job, interval=15, first=3.0)

    # Command handlers
    # users
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("addport", subisland))
    app.add_handler(CommandHandler("addvessel", subvessel))
    app.add_handler(CommandHandler("settings", settings))
    app.add_handler(CommandHandler("toggledepartures", toggledepartures))
    app.add_handler(CommandHandler("unsub", unsub))
    app.add_handler(CommandHandler("islandchannels", islandchannels))
    app.add_handler(CommandHandler("islandstats", island_stats))
    app.add_handler(CommandHandler("vesselstats", vessel_stats))
    # admin
    app.add_handler(CommandHandler("addchannel", addchannel))
    app.add_handler(CommandHandler("channeladdvessel", channelsubvessel))
    app.add_handler(CommandHandler("channeladdisland", channelsubisland))
    app.add_handler(CommandHandler("channelsettings", channelsettings))
    app.add_handler(CommandHandler("channelunsub", channelunsub))
    app.add_handler(CommandHandler("togglechanneldepartures", togglechanneldepartures))
    app.add_handler(CommandHandler("removechannel", removechannel))

    # Conversation handler for button-based interactions
    from handlers import (
        button_add_island,
        button_add_vessel,
        button_settings,
        button_unsub,
        button_toggle_departures,
        button_island_stats,
        button_vessel_stats,
        button_island_channels,
        button_help,
        handle_island_name,
        handle_vessel_name,
        handle_island_stats_name,
        handle_vessel_stats_name,
        cancel_conversation,
        AWAITING_ISLAND_NAME,
        AWAITING_VESSEL_NAME,
        AWAITING_ISLAND_STATS,
        AWAITING_VESSEL_STATS,
    )

    conversation = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Text(["🏝 Add Island"]), button_add_island),
            MessageHandler(filters.Text(["⛴ Add Vessel"]), button_add_vessel),
            MessageHandler(filters.Text(["⚙️ Settings"]), button_settings),
            MessageHandler(filters.Text(["🗑️ Unsubscribe"]), button_unsub),
            MessageHandler(filters.Text(["🚦 Toggle Departures"]), button_toggle_departures),
            MessageHandler(filters.Text(["📈 Island Stats"]), button_island_stats),
            MessageHandler(filters.Text(["📊 Vessel Stats"]), button_vessel_stats),
            MessageHandler(filters.Text(["📣 Island Channels"]), button_island_channels),
            MessageHandler(filters.Text(["❓ Help"]), button_help),
        ],
        states={
            AWAITING_ISLAND_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_island_name),
            ],
            AWAITING_VESSEL_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_vessel_name),
            ],
            AWAITING_ISLAND_STATS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_island_stats_name),
            ],
            AWAITING_VESSEL_STATS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_vessel_stats_name),
            ],
        },
        fallbacks=[
            CommandHandler("start", cancel_conversation),
            CommandHandler("help", cancel_conversation),
            CommandHandler("settings", cancel_conversation),
            CommandHandler("toggledepartures", cancel_conversation),
            CommandHandler("unsub", cancel_conversation),
            CommandHandler("vesselstats", cancel_conversation),
            CommandHandler("islandstats", cancel_conversation),
            CommandHandler("addvessel", cancel_conversation),
            CommandHandler("addport", cancel_conversation),
            CommandHandler("islandchannels", cancel_conversation),
        ],
        allow_reentry=True,
    )

    app.add_handler(conversation)

    app.add_handler(CallbackQueryHandler(callback_handler))

    # Unknown commands (must come after all specific CommandHandlers)
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    # Handle only non-command TEXT messages (ignore service updates like pins)
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, unrecognized_command)
    )

    # Add a basic error handler to avoid scary default log and capture details
    from telegram.error import NetworkError
    import logging

    async def log_error(update, context):
        err = context.error
        if isinstance(err, NetworkError):
            logging.getLogger(__name__).warning("NetworkError: %s", err)
        else:
            logging.getLogger(__name__).exception(
                "Unhandled error in handler", exc_info=err
            )

    app.add_error_handler(log_error)

    # Use an explicit long-poll timeout lower than read_timeout to reduce ReadError likelihood
    app.run_polling(timeout=30)
