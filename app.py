"""
Run the Telegram bot (main.py) and the API updater loop (api_calls.py)
in a single Heroku dyno by starting the updater in a background thread
and keeping the bot in the main thread.

Heroku Procfile should point to this file, e.g.:
  bot: python app.py
"""

from threading import Thread
import sys
import traceback
import os
from dotenv import load_dotenv

load_dotenv()
FOLLOWME_API_KEY = os.getenv("FOLLOWME_API")


def _start_api_calls_loop() -> None:
    """Start the API update loop from api_calls.py (blocking call)."""
    try:
        # Import inside the function to avoid side effects at module import time
        import api_calls  # noqa: WPS433 - intentional runtime import

        api_calls.main()
    except Exception:
        # Print full traceback to make debugging on Heroku logs easier
        traceback.print_exc()


def _run_bot() -> None:
    """Configure handlers and run the Telegram bot from main.py (blocking)."""
    # Import inside to ensure main.py module-level bootstrap runs once
    import main as bot_main  # noqa: WPS433 - intentional runtime import

    # Handlers and jobs are defined in separate modules; import explicitly here
    from telegram.ext import (
        CommandHandler,
        CallbackQueryHandler,
        MessageHandler,
        ChatMemberHandler,
        filters,
    )
    from telegram import BotCommand
    from handlers import (
        start,
        help_command,
        subisland,
        subvessel,
        toggledepartures,
        settings,
        unsub,
        islandchannels,
        island_stats,
        vessel_stats,
        my_chat_member_update,
        unknown_command,
        # admin
        addchannel,
        channelsubvessel,
        channelsubisland,
        callback_handler,
        unrecognized_command,
        channelsettings,
        channelunsub,
        togglechanneldepartures,
        removechannel,
        broadcast,
    )
    from send_messages import notify_job
    from telegram.error import NetworkError
    import logging

    print("Starting the bot...", flush=True)

    async def _post_init(application):
        """Set bot command menu for user-friendly mobile UI.

        Populates the Telegram client-side command shortcuts so users can tap
        instead of typing. Wrapped in try/except because failure (e.g. network
        hiccup) is non-fatal: the bot still runs, only the menu is missing.
        """
        try:
            await application.bot.set_my_commands(
                [
                    BotCommand("addport", "Subscribe to an island"),
                    BotCommand("addvessel", "Subscribe to a vessel"),
                    BotCommand("settings", "View your subscriptions"),
                    BotCommand("unsub", "Remove subscriptions"),
                    BotCommand("toggledepartures", "Toggle departure alerts"),
                    BotCommand("islandstats", "Island stats"),
                    BotCommand("vesselstats", "Vessel stats (beta)"),
                    BotCommand("islandchannels", "Island update channels"),
                    BotCommand("help", "How to use the bot"),
                    BotCommand("start", "Welcome and overview"),
                ]
            )
        except Exception:
            # Non-fatal; continue without setting commands
            pass

    # Register post-init hook so Application calls this after it starts
    bot_main.app.post_init = _post_init

    # Schedule background notifications job
    bot_main.app.job_queue.run_repeating(notify_job, interval=15, first=3.0)

    # Register command handlers (users)
    bot_main.app.add_handler(CommandHandler("start", start))
    bot_main.app.add_handler(CommandHandler("help", help_command))
    bot_main.app.add_handler(CommandHandler("addport", subisland))
    bot_main.app.add_handler(CommandHandler("addvessel", subvessel))
    bot_main.app.add_handler(CommandHandler("toggledepartures", toggledepartures))
    bot_main.app.add_handler(CommandHandler("settings", settings))
    bot_main.app.add_handler(CommandHandler("unsub", unsub))
    bot_main.app.add_handler(CommandHandler("islandchannels", islandchannels))
    bot_main.app.add_handler(CommandHandler("islandstats", island_stats))
    bot_main.app.add_handler(CommandHandler("vesselstats", vessel_stats))

    # Register command handlers (admin)
    bot_main.app.add_handler(CommandHandler("addchannel", addchannel))
    bot_main.app.add_handler(CommandHandler("channeladdvessel", channelsubvessel))
    bot_main.app.add_handler(CommandHandler("channeladdisland", channelsubisland))
    bot_main.app.add_handler(CommandHandler("channelsettings", channelsettings))
    bot_main.app.add_handler(CommandHandler("channelunsub", channelunsub))
    bot_main.app.add_handler(
        CommandHandler("togglechanneldepartures", togglechanneldepartures)
    )
    bot_main.app.add_handler(CommandHandler("removechannel", removechannel))
    bot_main.app.add_handler(CommandHandler("broadcast", broadcast))

    # Callback queries and command fallbacks
    bot_main.app.add_handler(CallbackQueryHandler(callback_handler))
    # Unknown commands should receive a friendly reply
    bot_main.app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    # Non-command text fallback (ignore service updates like pins)
    bot_main.app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, unrecognized_command)
    )

    # React to changes in the bot's own member status (blocked/unblocked, added/removed)
    bot_main.app.add_handler(
        ChatMemberHandler(
            my_chat_member_update, chat_member_types=ChatMemberHandler.MY_CHAT_MEMBER
        )
    )

    # Register a global error handler so PTB doesn't emit the default warning and we get clearer logs
    async def log_error(update, context):
        err = context.error
        if isinstance(err, NetworkError):
            logging.getLogger(__name__).warning("NetworkError: %s", err)
        else:
            logging.getLogger(__name__).exception(
                "Unhandled error in handler", exc_info=err
            )

    bot_main.app.add_error_handler(log_error)

    # Blocking call; handles SIGTERM/SIGINT on Heroku for graceful shutdown
    # Use an explicit long-poll timeout lower than read_timeout to reduce ReadError likelihood
    bot_main.app.run_polling(timeout=30)


def main() -> None:
    """Entry point to run updater loop in a thread and bot in main thread."""
    print("Launching API updater thread and Telegram bot...", flush=True)

    # Start the API updater in a daemon thread so the process can exit cleanly
    api_thread = Thread(target=_start_api_calls_loop, name="ApiCallsLoop", daemon=True)
    api_thread.start()

    # Run the bot in the main thread (safer for signal handling)
    _run_bot()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Shutdown requested. Exiting...", flush=True)
        sys.exit(0)
