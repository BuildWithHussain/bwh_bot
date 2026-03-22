from bwh_bot.api.telegram import register_command
from bwh_bot.telegram_utils import send_message


@register_command("/ping")
def handle_ping(message):
	chat_id = message["chat"]["id"]
	send_message(chat_id, "pong")
