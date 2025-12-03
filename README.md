# Bandharu Updates Bot

Real‑time Telegram bot for tracking vessel movements across Maldives ports using FollowMe.mv API data. Users subscribe to islands and vessels to receive instant arrival/departure alerts. Admins can manage island channels, broadcast announcements, and tune delivery.

Links:
- Live platform: Telegram Bot
- Data source: FollowMe.mv
- License: MIT


## What it does

- Pulls vessel location data from FollowMe.mv every ~60 seconds
- Detects arrivals/departures at ports and stores them in a small database
- Notifies users/chats who matched the event based on their subscriptions
- Offers daily island statistics and a growing set of tools for power users


## User features (commands)

All commands work in private chats and also works in groups where the bot is present.

- /start — Welcome, onboarding, and quick tips
- /help — How the bot works and the full command list
- /addport <island_name> — Subscribe to an island (aka port). If multiple matches, you get inline buttons to choose
- /addvessel <vessel_name> — Subscribe to a vessel by its name. Also supports partial matches with an inline picker
- /settings — View your current subscriptions and whether departure alerts are enabled
- /unsub — Inline menu to remove island or vessel subscriptions
- /toggledepartures — Turn departure alerts ON/OFF for this chat
- /islandstats <island_name> — Get yesterday’s daily stats for an island (peak hour(s), most active vessels, longest trips, etc.)
- /vesselstats — Need to  implement
- /islandchannels — Link to curated island update channels

Limits and behavior:
- You can subscribe to at most 10 islands and 10 vessels
- You’ll receive a notification when any of your vessels visits any of your islands
- If you subscribe to vessels but to zero islands, you’ll receive all events for those vessels (any island)
- Use /toggledepartures to suppress or re-enable departure messages per chat


## Admin features (commands)

Admin is identified by ADMIN_CHAT_ID. These commands only work for that chat id.

Channel management:
- /addchannel <port_name> <channel_id> <channel_username>
  - Assigns a Telegram channel to an island (port). The channel becomes the “main_port” user and can receive island-wide updates
  - Handles reassignment and updates gracefully if the island already has a channel
- /removechannel <port_name>
  - Remove the channel user associated with an island (cascades cleanly)
- /channelsettings <@channel_username>
  - Show the channel’s vessel and island subscriptions in a neat summary
- /channelunsub <@channel_username>
  - Inline picker to unsubscribe that channel from specific islands or vessels
- /togglechanneldepartures <@channel_username>
  - Turn departure alerts ON/OFF for that channel

Subscribe a channel:
- /channeladdisland <@channel_username> <port_name>
- /channeladdvessel <@channel_username> <vessel_name>
  - Both accept partial names and present inline options when there are multiple matches

Broadcasting:
- Reply to any message, then run: /broadcast <scope>
  - Scopes: private | group | channel | all
  - The bot copies the original message to each recipient (preserves formatting without linking back)


## How notifications are decided

The routing logic is implemented in model_helpers.get_users_to_notify_for_log and exercised by tests.

A user/chat will be notified about a port event when:
- They’re subscribed to that vessel AND (they’re subscribed to that port OR they have no port subscriptions at all)
- Additionally, any chat whose main_port equals that port will be notified (useful for island channels)

Other details:
- Per‑user per‑log notification state is tracked via PortLogNotification and cleaned as messages are sent
- Users can disable departure notifications per chat (/toggledepartures)
- The bot tries to prune users/chats that blocked or removed the bot to reduce errors (best‑effort)


## Data model (Peewee ORM)

- Port(id, name)
- User(chat_id, chat_type, username, first_name, last_name, date_joined, main_port, notify_on_departure)
- Vessel(id, name, vessel_type, contact, last_port, last_port_log_id)
- PortSubscription(user, port)
- VesselSubscription(user, vessel)
- PortLog(id, timestamp, vessel, port, event: arrival|departure, notified)
- PortLogNotification(port_log, user, sent, notified_at)

Storage:
- Local development defaults to SQLite (vessels_bot.db)
- On Heroku, Postgress


## Architecture and scheduling

- Framework: python-telegram-bot v22.x with JobQueue
- API updater: utils.update_db_with_api wraps rate‑limited calls to FollowMe.mv
- app.py starts two things in one process:
  1) API update loop (thread) every ~60 seconds
  2) Telegram bot (main thread) with a repeating notify job every 15 seconds
- handlers/ contains command handlers for users and admin; callbacks.py handles inline button actions
- send_messages.py builds messages and handles delivery, rate‑limits, and cleanup
- stats_calculator.py builds the daily island stats for /islandstats


## Configuration

Create a .env file (or configure Heroku config vars) with:

- BOT_API — Telegram Bot token (from @BotFather)
- FOLLOWME_API — FollowMe.mv public API key (Get key from  info@followme.mv / https://followme.mv/api/)
- ADMIN_CHAT_ID — Telegram chat id allowed to run admin commands
- DATABASE_URL — Optional (Postgres URL, recommended on Heroku). Falls back to local SQLite if unset

Optional/implicit:
- DYNO — Used on Heroku to enforce SSL for DATABASE_URL


## Local development

Requirements are pinned in requirements.txt. Python 3.12 is recommended (runtime.txt)

Install deps and run the bot (API updater + bot in one process):

```powershell
python -m venv .venv
. .venv\Scripts\Activate.ps1
pip install -r requirements.txt
# set env vars in .env or the shell before running
python app.py
```

Tips:
- app.py runs the background updater + bot; main.py only runs the bot (useful for debugging)
- The database file vessels_bot.db will appear locally when DATABASE_URL is not set


## Deployment (Heroku)

This repo is configured for Heroku:
- Procfile: `bot: python app.py`
- runtime.txt: Python 3.12.7

Typical steps (high‑level):
1) Create a Heroku app and add a Postgres add‑on
2) Set config vars: BOT_API, FOLLOWME_API, ADMIN_CHAT_ID, DATABASE_URL
3) Push the code to Heroku (git push heroku main)
4) Scale the bot dyno: `heroku ps:scale bot=1`

Notes:
- On first boot, the bot runs an initial sync to avoid flooding users
- Logs: `heroku logs --tail` to watch updates and notifications

## Contributing

Issues and pull requests are welcome. A few ideas:
- Add nationwide stats and other intresting stats
- Improve islandstats and vessel stats
- Screenshots/GIFs in the README


## Acknowledgements

- FollowMe.mv for the public data
- python-telegram-bot for the bot framework


## Support

End users can reach out @shahumeen on Telegram. Developers can open issues on GitHub.
