import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from peewee import JOIN

from model_helpers import (
    Port,
    Vessel,
    User,
    subscribe_user_to_port,
    subscribe_user_to_vessel,
    get_user_subscriptions,
)

load_dotenv()
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")


async def removechannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to remove the channel user associated with a port.
    Usage: /removechannel <port_name>
    If multiple ports match, shows a selection.
    """
    chat = update.effective_chat
    chat_id = chat.id

    if int(chat_id) != int(ADMIN_CHAT_ID):
        await context.bot.send_message(
            chat_id=chat_id, text="⛔️ This command can only be used by admin"
        )
        return

    if len(context.args) < 1:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "*Usage:*\n"
                "`/removechannel <port_name>`\n"
                "*Example:*\n"
                "`/removechannel Male`"
            ),
            parse_mode="MarkdownV2",
        )
        return

    port_name = " ".join(context.args).strip()

    try:
        matches = list(Port.select().where(Port.name.contains(port_name)))

        if not matches:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"😕 No islands found matching '{port_name}'",
            )
            return

        if len(matches) > 1:
            keyboard = []
            for p in matches:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            p.name, callback_data=f"remove_channel:{p.id}"
                        )
                    ]
                )
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🔎 Multiple islands found matching '{port_name}'."
                    " Please select one to remove its channel:"
                ),
                reply_markup=reply_markup,
            )
            return

        # Single match
        port = matches[0]
        channel_user = port.channel
        if not channel_user:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"ℹ️ No channel is currently associated with {port.name}",
            )
            return

        # Delete the channel user; cascades will clean subscriptions
        try:
            channel_user.delete_instance(recursive=True, delete_nullable=True)
        except Exception:
            # Fallback if recursive flags not supported
            channel_user.delete_instance()

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ Removed channel user associated with {port.name}",
        )
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Error: {str(e)}")


async def channelsettings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to view a channel's subscriptions.
    Usage: /channelsettings <channel_username>
    Accepts usernames with or without @.
    """
    chat = update.effective_chat
    chat_id = chat.id

    if int(chat_id) != int(ADMIN_CHAT_ID):
        await context.bot.send_message(
            chat_id=chat_id, text="⛔️ This command can only be used by admin"
        )
        return

    if len(context.args) != 1:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "*Usage:*\n"
                "`/channelsettings <channel_username>`\n"
                "*Example:*\n"
                "`/channelsettings @male_port`"
            ),
            parse_mode="MarkdownV2",
        )
        return

    channel_username = context.args[0].lstrip("@")

    # Find channel user
    channel = User.get_or_none(User.username == channel_username)
    if not channel:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"😕 Channel @{channel_username} not found. Use /addchannel first.",
        )
        return

    subs = get_user_subscriptions(channel.chat_id)
    port_list = subs.get("ports", [])
    vessel_list = subs.get("vessels", [])

    from telegram.helpers import escape_markdown

    def esc(s):
        return escape_markdown(str(s), version=2)

    header = f"*🧾 Subscriptions for* @{esc(channel_username)}:\n\n"
    lines = [header]

    if port_list:
        lines.append("*🏝 Ports:*")
        for p in port_list:
            lines.append(f"• {esc(p.name)}")
    else:
        lines.append("*🏝 Ports:* \\- None")

    if vessel_list:
        lines.append("\n*⛴ Vessels:*")
        for v in vessel_list:
            lines.append(f"• {esc(v.name)}")
    else:
        lines.append("\n*⛴ Vessels:* \\- None")

    await context.bot.send_message(
        chat_id=chat_id, text="\n".join(lines), parse_mode="MarkdownV2"
    )


async def togglechanneldepartures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to toggle departure notifications for a channel user.
    Usage: /togglechanneldepartures <channel_username>
    """
    chat = update.effective_chat
    chat_id = chat.id

    if int(chat_id) != int(ADMIN_CHAT_ID):
        await context.bot.send_message(
            chat_id=chat_id, text="⛔️ This command can only be used by admin"
        )
        return

    if len(context.args) != 1:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "*Usage:*\n"
                "`/togglechanneldepartures <channel_username>`\n"
                "*Example:*\n"
                "`/togglechanneldepartures @male_port`"
            ),
            parse_mode="MarkdownV2",
        )
        return

    channel_username = context.args[0].lstrip("@")
    channel = User.get_or_none(User.username == channel_username)
    if not channel:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"😕 Channel @{channel_username} not found. Use /addchannel first.",
        )
        return

    channel.notify_on_departure = not bool(channel.notify_on_departure)
    try:
        channel.save()
    except Exception:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Failed to update channel settings. Please try again later.",
        )
        return

    status_text = "ON" if channel.notify_on_departure else "OFF"
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"🚦 Departure notifications are now {status_text} for @{channel_username}",
    )


async def channelunsub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to show a channel's subscriptions with inline buttons to unsubscribe.
    Usage: /channelunsub <channel_username>
    """
    chat = update.effective_chat
    chat_id = chat.id

    if int(chat_id) != int(ADMIN_CHAT_ID):
        await context.bot.send_message(
            chat_id=chat_id, text="⛔️ This command can only be used by admin"
        )
        return

    if len(context.args) != 1:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "*Usage:*\n"
                "`/channelunsub <channel_username>`\n"
                "*Example:*\n"
                "`/channelunsub @male_port`"
            ),
            parse_mode="MarkdownV2",
        )
        return

    channel_username = context.args[0].lstrip("@")
    channel = User.get_or_none(User.username == channel_username)
    if not channel:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"😕 Channel @{channel_username} not found. Use /addchannel first.",
        )
        return

    subs = get_user_subscriptions(channel.chat_id)
    port_list = subs.get("ports", [])
    vessel_list = subs.get("vessels", [])

    keyboard = []
    for p in port_list:
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"🔕Unsubscribe: 📍{p.name}",
                    callback_data=f"channel_unsub_port:{channel.chat_id}:{p.id}",
                )
            ]
        )
    for v in vessel_list:
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"🔕Unsubscribe: ⛴{v.name}",
                    callback_data=f"channel_unsub_vessel:{channel.chat_id}:{v.id}",
                )
            ]
        )

    if not keyboard:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🔎 Channel @{channel_username} has no active subscriptions.",
        )
        return

    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"*🔕 Choose a subscription to remove for* @{channel_username}:",
        reply_markup=reply_markup,
        parse_mode="MarkdownV2",
    )


async def channelsubvessel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to subscribe a channel to a vessel.
    Usage: /channeladdvessel <channel_username> <vessel_name>"""
    chat = update.effective_chat
    chat_id = chat.id

    if int(chat_id) != int(ADMIN_CHAT_ID):
        await context.bot.send_message(
            chat_id=chat_id, text="⛔️ This command can only be used by admin"
        )
        return

    if len(context.args) < 2:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "*Usage:*\n"
                "`/channeladdvessel <channel_username> <vessel_name>`\n"
                "*Example:*\n"
                "`/channeladdvessel @channel1 RTL 101`"
            ),
            parse_mode="MarkdownV2",
        )
        return

    try:
        channel_username = context.args[0].strip("@")  # Remove @ if present
        vessel_name = " ".join(context.args[1:]).strip()

        # Check if channel exists as a user
        channel = User.get_or_none(User.username == channel_username)
        if not channel:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"😕 Channel @{channel_username} not found. Please add it first using /addchannel",
            )
            return

        # Get matches and split into already subscribed and available
        matches = list(
            Vessel.select().where(Vessel.name.contains(vessel_name)).limit(10)
        )
        subs = get_user_subscriptions(channel.chat_id)
        subbed_vessels = {v.id: v for v in subs.get("vessels", [])}

        if not matches:
            await context.bot.send_message(
                chat_id=chat_id, text=f"😕 No vessels found matching '{vessel_name}'."
            )
            return

        # If only one match and already subscribed
        if len(matches) == 1 and matches[0].id in subbed_vessels:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🔔 Channel @{channel_username} is already subscribed to {matches[0].name} ({matches[0].id}).",
            )
            return

        # If only one match and not subscribed
        if len(matches) == 1:
            v = matches[0]
            sub, created, err = subscribe_user_to_vessel(channel.chat_id, v.id)
            if sub:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ Channel @{channel_username} subscribed to vessel {v.name} ({v.id}).",
                )
            else:
                if err == "limit_reached":
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="⚠️ Channel has reached the maximum of 10 vessel subscriptions.",
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="❌ Failed to subscribe channel to vessel.",
                    )
            return

        # Show keyboard for multiple matches
        keyboard = []
        for v in matches:
            if v.id not in subbed_vessels:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"{v.name}",
                            callback_data=f"channel_sub_vessel:{channel.chat_id}:{v.id}",
                        )
                    ]
                )

        if not keyboard:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🔔 Channel @{channel_username} is already subscribed to all matching vessels.",
            )
            return

        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"➕ Choose a vessel to subscribe channel @{channel_username} to:",
            reply_markup=reply_markup,
        )

    except ValueError:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❗️ Invalid channel username format",
        )
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Error: {str(e)}")


async def channelsubisland(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to subscribe a channel to a port/island.
    Usage: /channeladdisland <channel_username> <port_name>"""
    chat = update.effective_chat
    chat_id = chat.id

    if int(chat_id) != int(ADMIN_CHAT_ID):
        await context.bot.send_message(
            chat_id=chat_id, text="⛔️ This command can only be used by admin"
        )
        return

    if len(context.args) < 2:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "*Usage:*\n"
                "`/channeladdisland <channel_username> <port_name>`\n"
                "*Example:*\n"
                "`/channeladdisland @channel1 Male`"
            ),
            parse_mode="MarkdownV2",
        )
        return

    try:
        channel_username = context.args[0].strip("@")  # Remove @ if present
        port_name = " ".join(context.args[1:]).strip()

        # Check if channel exists as a user
        channel = User.get_or_none(User.username == channel_username)
        if not channel:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"😕 Channel @{channel_username} not found. Please add it first using /addchannel",
            )
            return

        # Get all matching ports and channel's current subscriptions
        matches = list(Port.select().where(Port.name.contains(port_name)).limit(10))
        subs = get_user_subscriptions(channel.chat_id)
        subbed_ports = {p.id: p for p in subs.get("ports", [])}

        if not matches:
            await context.bot.send_message(
                chat_id=chat_id, text=f"😕 No islands found matching '{port_name}'."
            )
            return

        # If only one match and already subscribed
        if len(matches) == 1 and matches[0].id in subbed_ports:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"Channel @{channel_username} is already subscribed to {matches[0].name}.",
            )
            return

        # If only one match and not subscribed
        if len(matches) == 1:
            port = matches[0]
            sub, created, err = subscribe_user_to_port(channel.chat_id, port.id)
            if sub:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ Channel @{channel_username} subscribed to {port.name}.",
                )
            else:
                if err == "limit_reached":
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="⚠️ Channel has reached the maximum of 10 island subscriptions.",
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"❌ Failed to subscribe channel to {port.name}.",
                    )
            return

        # Show keyboard for multiple matches
        keyboard = []
        for p in matches:
            if p.id not in subbed_ports:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            p.name,
                            callback_data=f"channel_sub_port:{channel.chat_id}:{p.id}",
                        )
                    ]
                )

        if not keyboard:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🔔 Channel @{channel_username} is already subscribed to all matching islands.",
            )
            return

        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"➕ Choose an island to subscribe channel @{channel_username} to:",
            reply_markup=reply_markup,
        )

    except ValueError:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❗️ Invalid channel username format",
        )
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Error: {str(e)}")


async def addchannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a channel as a user and set its main port. Admin only command.
    Usage: /addchannel port_name channel_id channel_username"""
    chat = update.effective_chat
    chat_id = chat.id

    if int(chat_id) != int(ADMIN_CHAT_ID):
        await context.bot.send_message(
            chat_id=chat_id, text="⛔️ This command can only be used by admin"
        )
        return

    # Check if correct number of arguments provided
    if len(context.args) != 3:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "*Usage:*\n"
                "`/addchannel <port_name> <channel_id> <channel_username>`\n"
                "*Example:*\n"
                "`/addchannel Male 10012345674490 @male_port`"
            ),
            parse_mode="MarkdownV2",
        )
        return

    port_name, channel_id, channel_username = context.args

    try:
        # Convert channel_id to integer
        channel_id = int(channel_id)

        # Find matching ports
        matches = list(Port.select().where(Port.name.contains(port_name)))

        if not matches:
            await context.bot.send_message(
                chat_id=chat_id, text=f"😕 No islands found matching '{port_name}'"
            )
            return

        if len(matches) == 1:
            port = matches[0]
        else:
            # Show keyboard for multiple matches
            keyboard = []
            for p in matches:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            p.name,
                            callback_data=f"add_channel:{channel_id}:{channel_username}:{p.id}",
                        )
                    ]
                )

            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🔎 Multiple islands found matching '{port_name}'. Please select one:",
                reply_markup=reply_markup,
            )
            return

        # If a channel already exists for this port, update it; otherwise create/assign
        existing_channel = port.channel
        if existing_channel:
            if existing_channel.chat_id == channel_id:
                # Same channel record: update metadata
                existing_channel.chat_type = "channel"
                existing_channel.username = channel_username
                existing_channel.first_name = port_name
                existing_channel.main_port = port
                existing_channel.save()
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ Updated channel {channel_username} for island {port_name}",
                )
            else:
                # Reassign to new channel_id: detach old, attach/update new
                try:
                    new_user, _ = User.get_or_create(chat_id=channel_id)
                except Exception:
                    # Fallback if get_or_create fails due to type or pk issues
                    new_user = User.create(
                        chat_id=channel_id,
                        chat_type="channel",
                        username=channel_username,
                        first_name=port_name,
                        last_name=None,
                    )
                # Detach old channel from this port to keep uniqueness
                existing_channel.main_port = None
                existing_channel.save()

                # Update/attach new channel
                new_user.chat_type = "channel"
                new_user.username = channel_username
                new_user.first_name = port_name
                new_user.main_port = port
                new_user.save()

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ Reassigned island {port_name} to channel {channel_username}",
                )
        else:
            # No channel yet for this port: create or update provided channel user
            user, created = User.get_or_create(
                chat_id=channel_id,
                defaults={
                    "chat_type": "channel",
                    "username": channel_username,
                    "first_name": port_name,
                    "main_port": port,
                },
            )

            if not created:
                user.chat_type = "channel"
                user.username = channel_username
                user.first_name = port_name
                user.main_port = port
                user.save()

            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Successfully {'added' if created else 'updated'} channel {channel_username} for island {port_name}",
            )

    except ValueError:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❗️ Invalid channel ID format. Please provide a valid integer ID",
        )
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Error: {str(e)}")


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to broadcast (forward/copy) a replied message to selected users.

    Usage (must reply to a message):
        /broadcast <scope>

    Scopes:
        private  -> all private chats (individual users)
        group    -> all group & supergroup chats
        channel  -> all channel chats
        all      -> all chats

    The admin should reply with /broadcast <scope> to the message they want
    delivered. We copy the original message to preserve formatting without
    linking back to the admin chat.
    """
    chat = update.effective_chat
    chat_id = chat.id

    # Admin check
    if not ADMIN_CHAT_ID or int(chat_id) != int(ADMIN_CHAT_ID):
        await context.bot.send_message(
            chat_id=chat_id, text="⛔️ This command can only be used by admin"
        )
        return

    # Ensure scope arg provided
    if not context.args or len(context.args) != 1:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "*Usage:*\n"
                "/broadcast `<scope>` \\(reply to the message to send\\)\n\n"
                "*Scopes:*\n"
                "`private` – send to all private chats\n"
                "`group` – send to all groups & supergroups\n"
                "`channel` – send to all channels\n"
                "`all` – send to everyone\n\n"
                "*Example:* Reply to a message with `/broadcast all`"
            ),
            parse_mode="MarkdownV2",
        )
        return

    scope = context.args[0].lower().strip()
    valid_scopes = {"private", "group", "channel", "all"}
    if scope not in valid_scopes:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❗️ Invalid scope. Use one of: private, group, channel, all",
        )
        return

    # Must be a reply
    if not update.message or not update.message.reply_to_message:
        await context.bot.send_message(
            chat_id=chat_id,
            text="ℹ️ Please reply to the message you want to broadcast and include the scope. Example: reply then /broadcast private",
        )
        return

    original = update.message.reply_to_message

    # Build query for targets
    from model_helpers import User  # local import to avoid circulars at module load

    if scope == "private":
        query = User.select().where(User.chat_type == "private")
    elif scope == "group":
        query = User.select().where(User.chat_type.in_(["group", "supergroup"]))
    elif scope == "channel":
        query = User.select().where(User.chat_type == "channel")
    else:  # all
        query = User.select()

    targets = list(query)

    if not targets:
        await context.bot.send_message(
            chat_id=chat_id, text="ℹ️ No recipients found for this scope"
        )
        return

    # Send a quick preflight summary
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"📣 Broadcasting to {len(targets)} chats ({scope}). Starting...",
    )

    # Forward/copy loop with simple rate limiting
    import asyncio

    success = 0
    failures = 0
    for user in targets:
        try:
            # copy_message preserves formatting but detaches from original chat
            await context.bot.copy_message(
                chat_id=user.chat_id,
                from_chat_id=original.chat.id,
                message_id=original.message_id,
            )
            success += 1
        except Exception:
            failures += 1
        # Basic throttle to avoid hitting flood limits (adjust if needed)
        await asyncio.sleep(0.04)

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"✅ Broadcast finished. Sent: {success}, Failed: {failures}.",
    )

    # Optional: brief failure alert if many failed
    if failures > 0:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ Some messages failed to send (chat inaccessible or bot removed).",
        )
