from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
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


async def _post_init(application):
    """Set bot command menu for user-friendly mobile UI."""
    try:
        await application.bot.set_my_commands(
            [
                BotCommand("start", "Welcome and overview"),
                BotCommand("help", "How to use the bot"),
                BotCommand("addport", "Subscribe to an island"),
                BotCommand("addvessel", "Subscribe to a vessel"),
                BotCommand("settings", "View your subscriptions"),
                BotCommand("unsub", "Remove subscriptions"),
                BotCommand("toggledepartures", "Toggle departure alerts"),
                BotCommand("islandstats", "Island stats"),
                BotCommand("vesselstats", "Vessel stats - weekly"),
                BotCommand("islandchannels", "Island update channels"),
            ]
        )
    except Exception:
        # Non-fatal; continue without setting commands
        pass


app.post_init = _post_init


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
