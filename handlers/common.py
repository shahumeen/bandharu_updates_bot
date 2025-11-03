from telegram.helpers import escape_markdown


def esc_md(value) -> str:
    """Small helper for MarkdownV2 escaping."""
    return escape_markdown(str(value), version=2)
