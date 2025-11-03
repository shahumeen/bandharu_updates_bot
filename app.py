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
        filters,
    )
    from handlers import (
        start,
        subisland,
        subvessel,
        toggledepartures,
        settings,
        unsub,
        listchannels,
        island_stats,
        vessel_stats,
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
    )
    from send_messages import notify_job

    print("Starting the bot...", flush=True)

    # Schedule background notifications job
    bot_main.app.job_queue.run_repeating(notify_job, interval=15, first=3.0)

    # Register command handlers (users)
    bot_main.app.add_handler(CommandHandler("start", start))
    bot_main.app.add_handler(CommandHandler("addisland", subisland))
    bot_main.app.add_handler(CommandHandler("addvessel", subvessel))
    bot_main.app.add_handler(CommandHandler("toggledepartures", toggledepartures))
    bot_main.app.add_handler(CommandHandler("settings", settings))
    bot_main.app.add_handler(CommandHandler("unsub", unsub))
    bot_main.app.add_handler(CommandHandler("listchannels", listchannels))
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

    # Callback queries and non-command text
    bot_main.app.add_handler(CallbackQueryHandler(callback_handler))
    bot_main.app.add_handler(MessageHandler(filters.COMMAND, unrecognized_command))

    # Blocking call; handles SIGTERM/SIGINT on Heroku for graceful shutdown
    bot_main.app.run_polling()


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
