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


def _reset_portlogs_on_startup() -> None:
    """Reset all portlogs notified status to true on bot startup."""
    try:
        from models import PortLog, db

        # Update only portlogs with notified=False to set notified=True
        updated_count = PortLog.update({PortLog.notified: True}).where(
            PortLog.notified == False
        ).execute()
        print(
            f"Reset {updated_count} portlogs notified status to true on startup.",
            flush=True,
        )
        
        # Vacuum the database on startup
        db.execute_sql("VACUUM")
        print("Database vacuumed on startup", flush=True)
    except Exception as e:
        print(f"Error resetting portlogs on startup: {e}", flush=True)
        traceback.print_exc()


def _start_api_calls_loop() -> None:
    """Start the API update loop from api_calls.py (blocking call)."""
    try:
        # Import inside the function to avoid side effects at module import time
        import api_calls  # noqa: WPS433 - intentional runtime import

        api_calls.main()
    except Exception:
        # Print full traceback to make debugging on Heroku logs easier
        traceback.print_exc()


async def _vacuum_database_job(context) -> None:
    """Background job to vacuum the database daily."""
    try:
        from models import db

        db.execute_sql("VACUUM")
        print("Database vacuumed (daily job)", flush=True)
    except Exception as e:
        print(f"Error vacuuming database: {e}", flush=True)
        traceback.print_exc()


def _run_bot() -> None:
    """Configure handlers and run the Telegram bot from main.py (blocking)."""
    # Reset portlogs notified status on bot startup
    _reset_portlogs_on_startup()

    # Import inside to ensure main.py module-level bootstrap runs once
    import main as bot_main  # noqa: WPS433 - intentional runtime import

    # Handlers and jobs are defined in separate modules; import explicitly here
    from telegram.ext import (
        CommandHandler,
        CallbackQueryHandler,
        MessageHandler,
        ConversationHandler,
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
        # menu / button-based handlers and conversation pieces
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
    from send_messages import notify_job, send_db_backup, update_contacts_job
    from telegram.error import NetworkError
    import logging

    print("Starting the bot...", flush=True)

    # Schedule background notifications job
    bot_main.app.job_queue.run_repeating(notify_job, interval=15, first=3.0)

    # Schedule database backup job (every hour)
    bot_main.app.job_queue.run_repeating(send_db_backup, interval=21600, first=120.0)

    # Schedule weekly contacts update job (every 24 hours)
    bot_main.app.job_queue.run_repeating(update_contacts_job, interval=604800, first=3600.0)

    # Schedule daily database vacuum job
    bot_main.app.job_queue.run_repeating(_vacuum_database_job, interval=86400, first=10.0)

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

    # Conversation handler for button-based interactions (menu buttons)
    conversation = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Text(["🏝 Add Island"]), button_add_island),
            MessageHandler(filters.Text(["⛴ Add Vessel"]), button_add_vessel),
            MessageHandler(filters.Text(["⚙️ Settings"]), button_settings),
            MessageHandler(filters.Text(["🗑️ Unsubscribe"]), button_unsub),
            MessageHandler(
                filters.Text(["🚦 Toggle Departures"]), button_toggle_departures
            ),
            MessageHandler(filters.Text(["📈 Island Stats"]), button_island_stats),
            MessageHandler(filters.Text(["📊 Vessel Stats"]), button_vessel_stats),
            MessageHandler(
                filters.Text(["📣 Island Channels"]), button_island_channels
            ),
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
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, handle_island_stats_name
                ),
            ],
            AWAITING_VESSEL_STATS: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, handle_vessel_stats_name
                ),
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

    bot_main.app.add_handler(conversation)

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
