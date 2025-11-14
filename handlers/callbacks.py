from telegram.ext import ContextTypes
from telegram import Update

from model_helpers import (
    Port,
    Vessel,
    User,
    subscribe_user_to_port,
    subscribe_user_to_vessel,
    unsubscribe_user_from_port,
    unsubscribe_user_from_vessel,
    set_main_port,
)
from .admin import ADMIN_CHAT_ID
from .common import esc_md
from .users import MAP_QUERY, VESSEL_QUERY


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cq = update.callback_query
    if not cq or not cq.data:
        return
    await cq.answer()
    data = cq.data
    # The user who clicked
    chat = cq.message.chat
    chat_id = chat.id
    chat_type = chat.type

    # For inline button clicks, always use the chat where the button was clicked
    # regardless of who clicked it
    try:
        if chat_type in ["group", "supergroup", "channel"]:
            from model_helpers import create_user

            create_user(
                telegram_id=chat_id,
                chat_type=chat_type,
                username=None,
                first_name=chat.title,
                last_name=None,
            )
        else:
            # Private chat
            click_user = cq.from_user
            from model_helpers import create_user

            create_user(
                telegram_id=chat_id,
                chat_type=chat_type,
                username=(click_user.username if click_user else None),
                first_name=(click_user.first_name if click_user else ""),
                last_name=(click_user.last_name if click_user else None),
            )
    except Exception:
        pass

    click_id = chat_id  # Use the chat ID consistently for subscriptions

    if data.startswith("sub_port:"):
        try:
            pid = int(data.split(":", 1)[1])
            sub, created, err = subscribe_user_to_port(click_id, pid)
            if sub:
                try:
                    port = Port.get_by_id(pid)
                    await cq.edit_message_text(
                        text=f"✅ Subscribed to _*[{esc_md(port.name)}]({MAP_QUERY}{port.name})*_",
                        parse_mode="MarkdownV2",
                        disable_web_page_preview=True,
                    )
                    # If user now has zero vessel subscriptions, warn them
                    try:
                        from model_helpers import get_user_subscriptions

                        subs = get_user_subscriptions(click_id)
                        vessels = subs.get("vessels", [])
                        if not vessels:
                            await cq.message.reply_text(
                                text=(
                                    "⚠️ To receive notifications you also need at least *ONE* vessel subscription\\. Use /addvessel to add one\\."
                                ),
                                parse_mode="MarkdownV2",
                            )
                    except Exception:
                        pass
                except Exception:
                    await cq.edit_message_text(text=f"✅ Subscribed to port.")
            else:
                if err == "limit_reached":
                    await cq.edit_message_text(
                        text="⚠️ You’ve reached the maximum of *20* island subscriptions\\. Remove one with /unsub to add more\\.",
                        parse_mode="MarkdownV2",
                    )
                else:
                    try:
                        port = Port.get_by_id(pid)
                        await cq.edit_message_text(
                            text=f"❌ Failed to subscribe to {port.name}."
                        )
                    except Exception:
                        await cq.edit_message_text(
                            text=f"❌ Failed to subscribe to port."
                        )
        except Exception:
            await cq.edit_message_text(text="❌ Invalid selection.")

    elif data.startswith("sub_vessel:"):
        try:
            vid = int(data.split(":", 1)[1])
            sub, created, err = subscribe_user_to_vessel(click_id, vid)
            if sub:
                try:
                    v = Vessel.get_by_id(vid)
                    await cq.edit_message_text(
                        text=f"✅ Subscribed to _*[{esc_md(v.name)}]({VESSEL_QUERY}{v.id})*_",
                        parse_mode="MarkdownV2",
                        disable_web_page_preview=True,
                    )
                except Exception:
                    await cq.edit_message_text(text=f"✅ Subscribed to vessel.")
            else:
                if err == "limit_reached":
                    await cq.edit_message_text(
                        text="⚠️ You’ve reached the maximum of *20* vessel subscriptions\\. Use /unsub to remove one\\.",
                        parse_mode="MarkdownV2",
                    )
                else:
                    try:
                        v = Vessel.get_by_id(vid)
                        await cq.edit_message_text(
                            text=f"❌ Failed to subscribe to {v.name}."
                        )
                    except Exception:
                        await cq.edit_message_text(
                            text=f"❌ Failed to subscribe to vessel."
                        )
        except Exception:
            await cq.edit_message_text(text="❌ Invalid selection.")

    elif data.startswith("unsub_port:"):
        try:
            pid = int(data.split(":", 1)[1])
            ok = unsubscribe_user_from_port(click_id, pid)
            if ok:
                try:
                    port = Port.get_by_id(pid)
                    await cq.edit_message_text(
                        text=f"🔕 Unsubscribed from _*[{esc_md(port.name)}]({MAP_QUERY}{port.name})*_",
                        parse_mode="MarkdownV2",
                        disable_web_page_preview=True,
                    )
                except Exception:
                    await cq.edit_message_text(text=f"🔕 Unsubscribed from port.")
            else:
                try:
                    port = Port.get_by_id(pid)
                    await cq.edit_message_text(
                        text=f"❌ Failed to unsubscribe from {port.name}."
                    )
                except Exception:
                    await cq.edit_message_text(
                        text=f"❌Failed to unsubscribe from port."
                    )
        except Exception:
            await cq.edit_message_text(text="❌ Invalid selection.")

    elif data.startswith("unsub_vessel:"):
        try:
            vid = int(data.split(":", 1)[1])
            ok = unsubscribe_user_from_vessel(click_id, vid)
            if ok:
                try:
                    v = Vessel.get_by_id(vid)
                    await cq.edit_message_text(
                        text=f"🔕 Unsubscribed from  _*[{esc_md(v.name)}]({VESSEL_QUERY}{v.id})*_",
                        parse_mode="MarkdownV2",
                        disable_web_page_preview=True,
                    )
                except Exception:
                    await cq.edit_message_text(text=f"🔕 Unsubscribed from vessel.")

                # After unsubscribing a vessel, if user still has island subscriptions but now has zero vessels, send guidance
                try:
                    from model_helpers import get_user_subscriptions

                    subs = get_user_subscriptions(click_id)
                    vessels = subs.get("vessels", [])
                    # Send warning whenever user now has zero vessel subscriptions (regardless of islands)
                    if not vessels:
                        await cq.message.reply_text(
                            text=(
                                "⚠️ To receive notifications you also need at least *ONE* vessel subscription\\. Use /addvessel to add one\\."
                            ),
                            parse_mode="MarkdownV2",
                        )
                except Exception:
                    pass
            else:
                try:
                    v = Vessel.get_by_id(vid)
                    await cq.edit_message_text(
                        text=f"❌ Failed to unsubscribe from {v.name}."
                    )
                except Exception:
                    await cq.edit_message_text(
                        text=f"❌ Failed to unsubscribe from vessel."
                    )
        except Exception:
            await cq.edit_message_text(text="❌ Invalid selection.")

    elif data.startswith("add_channel:"):
        try:
            _, channel_id, channel_username, port_id = data.split(":")
            channel_id = int(channel_id)
            port_id = int(port_id)

            try:
                port = Port.get_by_id(port_id)
                existing_channel = port.channel
                if existing_channel:
                    if existing_channel.chat_id == channel_id:
                        existing_channel.chat_type = "channel"
                        existing_channel.username = channel_username
                        existing_channel.first_name = port.name
                        existing_channel.main_port = port
                        existing_channel.save()
                        await cq.edit_message_text(
                            text=f"✅ Updated channel {channel_username} for island {port.name}"
                        )
                    else:
                        # Reassign: detach old, attach/update new user
                        try:
                            new_user, _ = User.get_or_create(chat_id=channel_id)
                        except Exception:
                            new_user = User.create(
                                chat_id=channel_id,
                                chat_type="channel",
                                username=channel_username,
                                first_name=port.name,
                                last_name=None,
                            )
                        existing_channel.main_port = None
                        existing_channel.save()

                        new_user.chat_type = "channel"
                        new_user.username = channel_username
                        new_user.first_name = port.name
                        new_user.main_port = port
                        new_user.save()

                        await cq.edit_message_text(
                            text=f"✅ Reassigned island {port.name} to channel {channel_username}"
                        )
                else:
                    user, created = User.get_or_create(
                        chat_id=channel_id,
                        defaults={
                            "chat_type": "channel",
                            "username": channel_username,
                            "first_name": port.name,
                            "main_port": port,
                        },
                    )

                    if not created:
                        user.chat_type = "channel"
                        user.username = channel_username
                        user.first_name = port.name
                        user.main_port = port
                        user.save()

                    await cq.edit_message_text(
                        text=f"✅ Successfully {'added' if created else 'updated'} channel {channel_username} for island {port.name}"
                    )
            except Port.DoesNotExist:
                await cq.edit_message_text(text=f"Error: Port (id={port_id}) not found")
            except Exception as e:
                await cq.edit_message_text(text=f"Error: {str(e)}")
        except Exception:
            await cq.edit_message_text(text="Invalid selection.")

    elif data.startswith("set_main:"):
        try:
            pid = int(data.split(":", 1)[1])
            ok = set_main_port(click_id, pid)
            if ok:
                try:
                    port = Port.get_by_id(pid)
                    await cq.edit_message_text(text=f"Main port set to {port.name}.")
                except Exception:
                    await cq.edit_message_text(text=f"Main port set.")
            else:
                try:
                    port = Port.get_by_id(pid)
                    await cq.edit_message_text(
                        text=f"Failed to set main port to {port.name}."
                    )
                except Exception:
                    await cq.edit_message_text(text=f"Failed to set main port.")
        except Exception:
            await cq.edit_message_text(text="Invalid selection.")

    elif data.startswith("channel_sub_vessel:"):
        try:
            _, channel_id, vid = data.split(":")
            channel_id = int(channel_id)
            vid = int(vid)

            # Only admin can use these callbacks
            if int(chat_id) != int(ADMIN_CHAT_ID):
                await cq.edit_message_text(text="⛔️ Only admin can use this function.")
                return

            sub, created, err = subscribe_user_to_vessel(channel_id, vid)
            if sub:
                try:
                    v = Vessel.get_by_id(vid)
                    await cq.edit_message_text(
                        text=f"Channel (id={channel_id}) subscribed to {v.name}."
                    )
                except Exception:
                    await cq.edit_message_text(
                        text=f"Channel (id={channel_id}) subscribed to vessel."
                    )
            else:
                if err == "limit_reached":
                    await cq.edit_message_text(
                        text="Channel has reached the maximum of 10 vessel subscriptions."
                    )
                else:
                    try:
                        v = Vessel.get_by_id(vid)
                        await cq.edit_message_text(
                            text=f"Failed to subscribe channel to {v.name}."
                        )
                    except Exception:
                        await cq.edit_message_text(
                            text=f"Failed to subscribe channel to vessel."
                        )
        except Exception:
            await cq.edit_message_text(text="Invalid selection.")

    elif data.startswith("channel_sub_port:"):
        try:
            _, channel_id, pid = data.split(":")
            channel_id = int(channel_id)
            pid = int(pid)

            # Only admin can use these callbacks
            if int(chat_id) != int(ADMIN_CHAT_ID):
                await cq.edit_message_text(text="Only admin can use this function.")
                return

            sub, created, err = subscribe_user_to_port(channel_id, pid)
            if sub:
                try:
                    port = Port.get_by_id(pid)
                    await cq.edit_message_text(
                        text=f"Channel (id={channel_id}) subscribed to {port.name}."
                    )
                except Exception:
                    await cq.edit_message_text(
                        text=f"Channel (id={channel_id}) subscribed to port."
                    )
            else:
                if err == "limit_reached":
                    await cq.edit_message_text(
                        text="Channel has reached the maximum of 10 port subscriptions."
                    )
                else:
                    try:
                        port = Port.get_by_id(pid)
                        await cq.edit_message_text(
                            text=f"Failed to subscribe channel to {port.name}."
                        )
                    except Exception:
                        await cq.edit_message_text(
                            text=f"Failed to subscribe channel to port."
                        )
        except Exception:
            await cq.edit_message_text(text="Invalid selection.")

    elif data.startswith("channel_unsub_port:"):
        try:
            _, channel_id, pid = data.split(":")
            channel_id = int(channel_id)
            pid = int(pid)

            # Only admin can use these callbacks
            if int(chat_id) != int(ADMIN_CHAT_ID):
                await cq.edit_message_text(text="Only admin can use this function.")
                return

            ok = unsubscribe_user_from_port(channel_id, pid)
            if ok:
                try:
                    port = Port.get_by_id(pid)
                    await cq.edit_message_text(
                        text=f"Channel (id={channel_id}) unsubscribed from {port.name}."
                    )
                except Exception:
                    await cq.edit_message_text(
                        text=f"Channel (id={channel_id}) unsubscribed from port."
                    )
            else:
                try:
                    port = Port.get_by_id(pid)
                    await cq.edit_message_text(
                        text=f"Failed to unsubscribe channel from {port.name}."
                    )
                except Exception:
                    await cq.edit_message_text(
                        text=f"Failed to unsubscribe channel from port."
                    )
        except Exception:
            await cq.edit_message_text(text="Invalid selection.")

    elif data.startswith("channel_unsub_vessel:"):
        try:
            _, channel_id, vid = data.split(":")
            channel_id = int(channel_id)
            vid = int(vid)

            # Only admin can use these callbacks
            if int(chat_id) != int(ADMIN_CHAT_ID):
                await cq.edit_message_text(text="Only admin can use this function.")
                return

            ok = unsubscribe_user_from_vessel(channel_id, vid)
            if ok:
                try:
                    v = Vessel.get_by_id(vid)
                    await cq.edit_message_text(
                        text=f"Channel (id={channel_id}) unsubscribed from {v.name}."
                    )
                except Exception:
                    await cq.edit_message_text(
                        text=f"Channel (id={channel_id}) unsubscribed from vessel."
                    )
            else:
                try:
                    v = Vessel.get_by_id(vid)
                    await cq.edit_message_text(
                        text=f"Failed to unsubscribe channel from {v.name}."
                    )
                except Exception:
                    await cq.edit_message_text(
                        text=f"Failed to unsubscribe channel from vessel."
                    )
        except Exception:
            await cq.edit_message_text(text="Invalid selection.")

    elif data.startswith("get_port_stats:"):
        try:
            port_id = int(data.split(":", 1)[1])
            # Delete the selection message
            await cq.message.delete()
            # Send stats in a new message
            from .stats import send_port_stats

            await send_port_stats(context, chat_id, port_id)
        except Exception as e:
            await cq.edit_message_text(text=f"Error retrieving stats: {str(e)}")

    elif data.startswith("get_vessel_stats:"):
        try:
            vessel_id = int(data.split(":", 1)[1])
            # Delete the selection message
            await cq.message.delete()
            # Send stats in a new message
            from .stats import send_vessel_stats

            await send_vessel_stats(context, chat_id, vessel_id)
        except Exception as e:
            await cq.edit_message_text(text=f"Error retrieving stats: {str(e)}")

    elif data.startswith("remove_channel:"):
        try:
            _, pid = data.split(":")
            pid = int(pid)

            # Only admin can use these callbacks
            if int(chat_id) != int(ADMIN_CHAT_ID):
                await cq.edit_message_text(text="Only admin can use this function.")
                return

            try:
                port = Port.get_by_id(pid)
            except Exception:
                await cq.edit_message_text(text="Port not found.")
                return

            channel_user = port.channel
            if not channel_user:
                await cq.edit_message_text(
                    text=f"No channel is currently associated with {port.name}."
                )
                return

            try:
                channel_user.delete_instance(recursive=True, delete_nullable=True)
            except Exception:
                channel_user.delete_instance()

            await cq.edit_message_text(
                text=f"Removed channel user associated with {port.name}."
            )
        except Exception:
            await cq.edit_message_text(text="Invalid selection.")
