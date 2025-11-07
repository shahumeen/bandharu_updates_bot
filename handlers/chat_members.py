from telegram import Update
from telegram.ext import ContextTypes
from models import User
from model_helpers import create_user
from send_messages import _notify_admin_of_block


async def my_chat_member_update(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """React to updates about the bot's own status in chats (blocked/unblocked, added/removed).

    - Private chats: when a user blocks (status -> kicked) or unblocks (status -> member)
    - Groups/supergroups/channels: when bot is added/removed or loses/gains admin/member status
    """
    cmu = update.my_chat_member
    if not cmu:
        return

    chat = cmu.chat
    chat_id = chat.id
    chat_type = getattr(chat, "type", None)
    new_status = getattr(cmu.new_chat_member, "status", None)
    old_status = getattr(cmu.old_chat_member, "status", None)

    # Helper: best-effort admin notification
    async def _notify(reason: str) -> None:
        try:
            await _notify_admin_of_block(chat_id, reason, context)
        except Exception:
            pass

    # Private chat: block/unblock
    if chat_type == "private":
        # Blocked -> status becomes 'kicked'
        if new_status == "kicked":
            try:
                u = User.get_or_none(User.chat_id == chat_id)
                if u:
                    u.delete_instance(recursive=True)
                await _notify(
                    f"my_chat_member private: {old_status} -> {new_status} (blocked by user)"
                )
            except Exception:
                pass
            return

        # Unblocked or allowed -> ensure user row exists
        if new_status in ("member",):
            try:
                actor = cmu.from_user
                username = getattr(actor, "username", None)
                first_name = (
                    getattr(actor, "first_name", None) or chat.first_name or "-"
                )
                last_name = getattr(actor, "last_name", None)
                create_user(
                    telegram_id=chat_id,
                    chat_type=chat_type,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                )
            except Exception:
                pass
            return

    # Groups / supergroups / channels
    if chat_type in ("group", "supergroup", "channel"):
        # Removed: 'left' (voluntary) or 'kicked' (removed/banned)
        if new_status in ("left", "kicked"):
            try:
                u = User.get_or_none(User.chat_id == chat_id)
                if u:
                    u.delete_instance(recursive=True)
                await _notify(
                    f"my_chat_member {chat_type}: {old_status} -> {new_status} (bot removed)"
                )
            except Exception:
                pass
            return

        # Added or promoted: 'member' or 'administrator'
        if new_status in ("member", "administrator"):
            try:
                title = getattr(chat, "title", None) or chat_type
                create_user(
                    telegram_id=chat_id,
                    chat_type=chat_type,
                    username=None,
                    first_name=title,
                    last_name=None,
                )
            except Exception:
                pass
            return
