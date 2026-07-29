from bwh_bot.api.telegram import register_command
from bwh_bot.telegram_utils import send_message


@register_command("/ping", description="Check if bot is alive")
def handle_ping(message):
	chat_id = message["chat"]["id"]
	send_message(
		chat_id,
		"pong",
		reply_to_message_id=message["message_id"],
		message_thread_id=message.get("message_thread_id"),
	)
