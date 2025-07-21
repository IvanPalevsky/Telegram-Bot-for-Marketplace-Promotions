# 🤖 Telegram Bot with Channel Subscription Verification

> A Python-based Telegram bot that ensures users are subscribed to a specific channel and verifies their subscription expiration using a local SQLite database.

---

## 📌 Key Features

- ✅ Checks if a user is subscribed to a specific Telegram channel

- ⏳ Validates if the user's subscription is still active (based on a stored expiration date)

- 📬 Sends inline buttons to guide users to subscribe or renew

- 🗂 Stores user subscription data in SQLite

- 🔁 Scheduled operations via `schedule` module

- 📦 Easy deployment with minimum dependencies

---

## 📂 Project Structure

📦 your_project/

├── main2.py # Main bot logic and command handling

├── subscription.txt # Subscription checking function (can be extracted into utils)

├── requirements.txt # List of required libraries

└── README.md # This documentation

---

## ⚙️ Installation

### 1. Clone the Repository

```
git clone https://github.com/yourusername/telegram-subscription-bot.git
cd telegram-subscription-bot
```
### 2. Install Dependencies
```
pip install -r requirements.txt
```
🔧 Note: You may need to install sqlite3 separately depending on your system.

## 🛠️ Configuration
- Bot Token & Channel ID
- Define them in main2.py (or better — use .env file and python-dotenv):
```
BOT_TOKEN = "your_token_here"
CHANNEL_ID = "@your_channel"
```
- Database Table Structure
- You must have a users table with at least chat_id and subscription_end:
```
CREATE TABLE users (
    chat_id INTEGER PRIMARY KEY,
    subscription_end TEXT
);
```
## 🧠 How It Works
When a user interacts with the bot:

- The bot checks if the user is a member of the target channel

- Then it verifies if the user has an active subscription date in the local database

- If not subscribed or expired, inline buttons are sent with options to subscribe or renew

## 📋 Example Usage
```
@bot.message_handler(commands=["start"])
def start_handler(message):
    if check_subscription(message.chat.id):
        bot.send_message(message.chat.id, "Добро пожаловать!")
    else:
        # check_subscription handles messaging for failures
        pass
```
## 🧪 Function Highlight: check_subscription
```
def check_subscription(chat_id):
    # Verifies Telegram channel membership and subscription date
    ...
```
📌 Returns True if user is valid and active.

📌 Sends required instructions if the user is not eligible.

📌 Uses InlineKeyboardMarkup for clean UX.

## 🛡️ License

MIT License — free to use, modify, and deploy.

## 🙋‍♂️ Author
Created by Ivan

Inst: @chll_killer
