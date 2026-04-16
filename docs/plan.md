# BWH Bot — Frappe App Implementation Plan

## Context

Build a Telegram bot as a **Frappe app** (`bwh_bot`) that listens to commands in whitelisted group chats via webhooks. Deploy by installing the app on an existing Frappe site — no separate VM or Docker needed. Starting with `/ping` → `pong`, extensible from there.

Reference: `~/Frappe/press` uses a similar webhook-based Telegram integration.

## Tech Stack

- **Framework**: Frappe (custom app)
- **Telegram library**: `python-telegram-bot` (added to app's `pyproject.toml`)
- **Config**: Single "BWH Bot Settings" DocType (singleton) — bot token + child table of whitelisted chat IDs
- **Webhook**: Frappe whitelisted API endpoint (`/api/method/bwh_bot.api.telegram.hook`)

## App Structure

```
bwh_bot/
├── bwh_bot/
│   ├── __init__.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── telegram.py              # Webhook endpoint + command routing
│   ├── telegram_utils.py            # Telegram Bot wrapper (send messages, validate)
│   ├── handlers/
│   │   ├── __init__.py
│   │   └── ping.py                  # /ping → pong
│   └── bwh_bot/
│       └── doctype/
│           ├── bwh_bot_settings/
│           │   ├── bwh_bot_settings.json   # DocType definition
│           │   └── bwh_bot_settings.py     # Settings logic
│           └── bwh_bot_whitelisted_chat/
│               ├── bwh_bot_whitelisted_chat.json  # Child table DocType
│               └── bwh_bot_whitelisted_chat.py
├── pyproject.toml                   # python-telegram-bot dependency
└── setup.py
```

## Implementation Steps

### Step 1: Scaffold the Frappe app
- Run `bench new-app bwh_bot` (or create manually)
- Add `python-telegram-bot` to `pyproject.toml` install_requires

### Step 2: BWH Bot Settings DocType (singleton)
- **BWH Bot Settings** (issingle: 1):
  - `bot_token` (Password field) — Telegram bot token
  - `webhook_secret` (Data field) — secret for verifying incoming webhooks
  - `whitelisted_chats` (Table field → BWH Bot Whitelisted Chat)
- **BWH Bot Whitelisted Chat** (child table, istable: 1):
  - `chat_id` (Data field) — Telegram chat ID
  - `label` (Data field) — friendly name for the group

### Step 3: Telegram utility (`bwh_bot/telegram_utils.py`)
- Thin wrapper: instantiate `telegram.Bot` with token from settings
- `send_message(chat_id, text)` helper
- `is_whitelisted(chat_id)` check against settings

### Step 4: Webhook endpoint (`bwh_bot/api/telegram.py`)
- `@frappe.whitelist(allow_guest=True)` endpoint
- Parses incoming Telegram Update JSON
- Validates the message is from a whitelisted chat
- Routes commands to handlers (simple dict-based dispatch)

### Step 5: Ping handler (`bwh_bot/handlers/ping.py`)
- Receives the update, replies `pong` to the same chat

### Step 6: Webhook registration
- A method (callable via bench console or a button in Settings) to call Telegram's `setWebhook` API with the site URL + endpoint path

## Key Files to Reference from Press

| Purpose | Press file |
|---------|-----------|
| Webhook endpoint | `press/api/telegram.py` |
| Bot wrapper | `press/telegram_utils.py` |
| Settings fields | `press/press/doctype/press_settings/press_settings.json` |

## Verification

1. `bench new-app bwh_bot` → `bench install-app bwh_bot`
2. Configure BWH Bot Settings with bot token + a whitelisted chat ID
3. Set webhook: call the registration method with your site's public URL
4. Send `/ping` in the whitelisted group → bot replies `pong`
5. Send `/ping` in a non-whitelisted chat → bot ignores it
