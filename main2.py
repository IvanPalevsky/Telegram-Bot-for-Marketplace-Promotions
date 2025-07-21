import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, LabeledPrice
import requests
from datetime import datetime, timedelta
import sqlite3
import logging
import sys
import threading
import schedule
import time
import csv
import io

# 🔧 Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# 🔑 Получение токена бота из переменных окружения
BOT_TOKEN = ''

# 💳 Токен для Telegram Payments (получите его у @BotFather)
PAYMENT_TOKEN = ''

# 📢 ID канала, на который нужно подписаться
CHANNEL_ID = '@your_channel_username'

# 🤖 Инициализация бота
bot = telebot.TeleBot(BOT_TOKEN)

# 🗄️ Инициализация базы данных
conn = sqlite3.connect('marketplace_bot.db', check_same_thread=False)
cursor = conn.cursor()

# 📊 Создание таблиц в базе данных
cursor.execute('''CREATE TABLE IF NOT EXISTS users
                  (id INTEGER PRIMARY KEY, chat_id INTEGER UNIQUE, subscription_end DATE, balance REAL DEFAULT 0, 
                   ozon_api_key TEXT, ozon_client_id TEXT, wb_api_key TEXT, subscription_type TEXT,
                   auto_cancel_enabled INTEGER DEFAULT 0, monitoring_enabled INTEGER DEFAULT 1,
                   ozon_action_id TEXT, wb_promotion_id TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS ignored_products
                  (id INTEGER PRIMARY KEY, user_id INTEGER, marketplace TEXT, product_id TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS promo_codes
                  (id INTEGER PRIMARY KEY, code TEXT UNIQUE, discount REAL, uses INTEGER DEFAULT 0)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS referrals
                  (id INTEGER PRIMARY KEY, referrer_id INTEGER, referred_id INTEGER, date DATE)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS ozon_actions
                  (id INTEGER PRIMARY KEY, user_id INTEGER, action_type TEXT, product_id TEXT, date DATETIME)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS wb_actions
                  (id INTEGER PRIMARY KEY, user_id INTEGER, action_type TEXT, product_id TEXT, date DATETIME)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS pending_actions
                  (id INTEGER PRIMARY KEY, user_id INTEGER, marketplace TEXT, product_id TEXT, action_type TEXT, 
                   notification_time DATETIME)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS ozon_promotions
                  (id INTEGER PRIMARY KEY, user_id INTEGER, action_id INTEGER, title TEXT, 
                   action_type TEXT, date_start TEXT, date_end TEXT, is_participating INTEGER)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS wb_promotions
                  (id INTEGER PRIMARY KEY, user_id INTEGER, promotion_id INTEGER, title TEXT, 
                   date_start TEXT, date_end TEXT, is_participating INTEGER)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS wb_prices
                  (id INTEGER PRIMARY KEY, user_id INTEGER, nmId TEXT, price REAL, discount REAL)''')
conn.commit()

# 🛠️ Функции для работы с базой данных
def add_user(chat_id):
    try:
        cursor.execute("INSERT OR IGNORE INTO users (chat_id, subscription_end) VALUES (?, date('now', '+3 days'))", (chat_id,))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")

def check_subscription(chat_id):
    try:
        # Проверка срока подписки
        cursor.execute("SELECT subscription_end FROM users WHERE chat_id = ?", (chat_id,))
        result = cursor.fetchone()
        if result:
            subscription_end = datetime.strptime(result[0], "%Y-%m-%d").date()
            if subscription_end >= datetime.now().date():
                return True
            else:
                keyboard = InlineKeyboardMarkup()
                keyboard.add(InlineKeyboardButton("🔄 Продлить подписку", callback_data="renew_subscription"))
                bot.send_message(chat_id, "⚠️ Ваша подписка истекла. Пожалуйста, продлите ее для продолжения использования бота.", reply_markup=keyboard)
                return False
        
        # Если подписки нет, предлагаем подписаться на канал
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_ID[1:]}"))
        keyboard.add(InlineKeyboardButton("✅ Я подписался", callback_data="confirm_subscription"))
        bot.send_message(chat_id, "🔔 Пожалуйста, подпишитесь на наш канал и нажмите кнопку 'Я подписался'.", reply_markup=keyboard)
        return True
    except Exception as e:
        logger.error(f"Error in check_subscription: {e}")
        return True

def add_ignored_product(user_id, marketplace, product_id):
    try:
        cursor.execute("INSERT INTO ignored_products (user_id, marketplace, product_id) VALUES (?, ?, ?)",
                       (user_id, marketplace, product_id))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")

def remove_ignored_product(user_id, marketplace, product_id):
    try:
        cursor.execute("DELETE FROM ignored_products WHERE user_id = ? AND marketplace = ? AND product_id = ?",
                       (user_id, marketplace, product_id))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")

def get_ignored_products(user_id, marketplace):
    try:
        cursor.execute("SELECT product_id FROM ignored_products WHERE user_id = ? AND marketplace = ?",
                       (user_id, marketplace))
        return [row[0] for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        return []

def add_promo_code(code, discount):
    try:
        cursor.execute("INSERT INTO promo_codes (code, discount) VALUES (?, ?)", (code, discount))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")

def use_promo_code(code, user_id):
    try:
        cursor.execute("SELECT discount, uses FROM promo_codes WHERE code = ?", (code,))
        result = cursor.fetchone()
        if result:
            discount, uses = result
            cursor.execute("UPDATE promo_codes SET uses = ? WHERE code = ?", (uses + 1, code))
            cursor.execute("UPDATE users SET subscription_end = date(subscription_end, '+30 days') WHERE chat_id = ?", (user_id,))
            conn.commit()
            return discount
        return None
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        return None

def add_referral(referrer_id, referred_id):
    try:
        cursor.execute("INSERT INTO referrals (referrer_id, referred_id, date) VALUES (?, ?, date('now'))", (referrer_id, referred_id))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")

def get_referral_count(user_id):
    try:
        cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,))
        return cursor.fetchone()[0]
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        return 0

def update_balance(user_id, amount):
    try:
        cursor.execute("UPDATE users SET balance = balance + ? WHERE chat_id = ?", (amount, user_id))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")

def get_user_analytics(user_id):
    try:
        cursor.execute("""
            SELECT DATE(date) as day, COUNT(*) as count
            FROM (
                SELECT date FROM ozon_actions WHERE user_id = ?
                UNION ALL
                SELECT date FROM wb_actions WHERE user_id = ?
            )
            GROUP BY day
            ORDER BY day
            LIMIT 30
        """, (user_id, user_id))
        return cursor.fetchall()
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        return []

def log_action(user_id, marketplace, action_type, product_id):
    try:
        table_name = f"{marketplace}_actions"
        cursor.execute(f"""
            INSERT INTO {table_name} (user_id, action_type, product_id, date)
            VALUES (?, ?, ?, datetime('now'))
        """, (user_id, action_type, product_id))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")

def get_marketplace_credentials(user_id, marketplace):
    try:
        if marketplace == 'ozon':
            cursor.execute("SELECT ozon_api_key, ozon_client_id FROM users WHERE chat_id = ?", (user_id,))
            result = cursor.fetchone()
            if result:
                return {'api_key': result[0], 'client_id': result[1]}
        elif marketplace == 'wb':
            cursor.execute("SELECT wb_api_key FROM users WHERE chat_id = ?", (user_id,))
            result = cursor.fetchone()
            if result:
                return {'api_key': result[0]}
        return None
    except sqlite3.Error as e:
        logger.error(f"Database error in get_marketplace_credentials: {e}")
        return None

def update_marketplace_credentials(user_id, marketplace, api_key, client_id=None):
    try:
        if marketplace == 'ozon':
            cursor.execute("UPDATE users SET ozon_api_key = ?, ozon_client_id = ? WHERE chat_id = ?", 
                           (api_key, client_id, user_id))
        elif marketplace == 'wb':
            cursor.execute("UPDATE users SET wb_api_key = ? WHERE chat_id = ?", 
                           (api_key, user_id))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")

def add_pending_action(user_id, marketplace, product_id, action_type):
    try:
        notification_time = datetime.now() + timedelta(hours=1)
        cursor.execute("""
            INSERT INTO pending_actions (user_id, marketplace, product_id, action_type, notification_time)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, marketplace, product_id, action_type, notification_time))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")

def get_pending_actions():
    try:
        cursor.execute("""
            SELECT id, user_id, marketplace, product_id, action_type
            FROM pending_actions
            WHERE notification_time <= datetime('now')
        """)
        return cursor.fetchall()
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        return []

def remove_pending_action(action_id):
    try:
        cursor.execute("DELETE FROM pending_actions WHERE id = ?", (action_id,))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")

def set_auto_cancel(user_id, enabled):
    try:
        cursor.execute("UPDATE users SET auto_cancel_enabled = ? WHERE chat_id = ?", (1 if enabled else 0, user_id))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")

def get_auto_cancel_status(user_id):
    try:
        cursor.execute("SELECT auto_cancel_enabled FROM users WHERE chat_id = ?", (user_id,))
        result = cursor.fetchone()
        return bool(result[0]) if result else False
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        return False

# 🌐 Функции для работы с API маркетплейсов
def get_ozon_actions(api_key, client_id):
    url = "https://api-seller.ozon.ru/v1/actions"
    headers = {
        "Client-Id": client_id,
        "Api-Key": api_key,
        "Content-Type": "application/json"
    }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json().get('result', [])
    except requests.RequestException as e:
        logger.error(f"Ozon API error in get_ozon_actions: {e}")
        return []

def get_wb_actions(api_key):
    url = "https://suppliers-api.wildberries.ru/api/v1/calendar/promotions"
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json"
    }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json().get('data', [])
    except requests.RequestException as e:
        logger.error(f"Wildberries API error in get_wb_actions: {e}")
        return []
    
def get_ozon_promo_products(api_key, client_id, action_id, offset=0, limit=100):
    url = "https://api-seller.ozon.ru/v1/actions/products"
    headers = {
        "Client-Id": client_id,
        "Api-Key": api_key,
        "Content-Type": "application/json"
    }
    payload = {
        "action_id": int(action_id),
        "limit": limit,
        "offset": offset
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json().get('result', {})
    except requests.exceptions.HTTPError as e:
        logger.error(f"Ozon API error: {e}")
        logger.error(f"Request URL: {url}")
        logger.error(f"Request Headers: {headers}")
        logger.error(f"Request Payload: {payload}")
        logger.error(f"Response: {e.response.text}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Ozon API request failed: {e}")
        return None

def remove_ozon_product_from_promo(api_key, client_id, product_id):
    url = "https://api-seller.ozon.ru/v1/actions/products/deactivate"
    headers = {
        "Client-Id": client_id,
        "Api-Key": api_key,
        "Content-Type": "application/json"
    }
    payload = {
        "product_ids": [product_id]
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.error(f"Ozon API error: {e}")
        return False

def get_wb_promo_products(api_key, promotion_id, in_action=True, offset=0, limit=1000):
    url = "https://suppliers-api.wildberries.ru/api/v1/calendar/products"
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json"
    }
    params = {
        "inAction": "true" if in_action else "false",
        "limit": limit,
        "offset": offset,
        "promotionId": promotion_id
    }
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json().get('data', [])
    except requests.RequestException as e:
        logger.error(f"Wildberries API error: {e}")
        return None

def update_wb_product_discount(api_key, product_data):
    url = "https://suppliers-api.wildberries.ru/api/v1/calendar/prices"
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(url, headers=headers, json=product_data)
        response.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.error(f"Wildberries API error: {e}")
        return False

# 🔄 Функции для обновления информации об акциях
def update_ozon_actions(user_id, actions):
    try:
        cursor.execute("DELETE FROM ozon_promotions WHERE user_id = ?", (user_id,))
        for action in actions:
            cursor.execute('''INSERT INTO ozon_promotions 
                              (user_id, action_id, title, action_type, date_start, date_end, is_participating) 
                              VALUES (?, ?, ?, ?, ?, ?, ?)''', 
                           (user_id, action['id'], action['title'], action['action_type'],
                            action['date_start'], action['date_end'], int(action['is_participating'])))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error in update_ozon_actions: {e}")

def update_wb_actions(user_id, actions):
    try:
        cursor.execute("DELETE FROM wb_promotions WHERE user_id = ?", (user_id,))
        for action in actions:
            cursor.execute('''INSERT INTO wb_promotions 
                              (user_id, promotion_id, title, date_start, date_end, is_participating) 
                              VALUES (?, ?, ?, ?, ?, ?)''', 
                           (user_id, action['id'], action['name'], action['startDate'],
                            action['endDate'], int(action['isActive'])))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error in update_wb_actions: {e}")

# 📊 Функция для обработки шаблона цен Wildberries
def process_price_template(message):
    try:
        if message.document:
            file_info = bot.get_file(message.document.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            csv_file = io.StringIO(downloaded_file.decode('utf-8'))
            csv_reader = csv.DictReader(csv_file)
            
            price_data = []
            for row in csv_reader:
                price_data.append({
                    'nmId': row['nmId'],
                    'price': float(row['price']),
                    'discount': float(row['discount'])
                })
            
            update_wb_prices(message.chat.id, price_data)
            
            success_text = (
                "✅ Шаблон цен успешно загружен и обработан!\n\n"
                "📊 Теперь бот будет использовать эти цены при работе с товарами Wildberries.\n"
                f"📦 Обработано товаров: {len(price_data)}\n"
                "🔄 Вы всегда можете обновить шаблон, загрузив новый файл."
            )
            bot.reply_to(message, success_text)
        else:
            bot.reply_to(message, "❌ Пожалуйста, отправьте файл в формате CSV.")
    except Exception as e:
        logger.error(f"Error in process_price_template: {e}")
        bot.reply_to(message, "❌ Произошла ошибка при обработке шаблона цен. Пожалуйста, проверьте формат файла и попробуйте снова.")

def update_wb_prices(user_id, price_data):
    try:
        cursor.execute("DELETE FROM wb_prices WHERE user_id = ?", (user_id,))
        for item in price_data:
            cursor.execute('''INSERT INTO wb_prices (user_id, nmId, price, discount) 
                              VALUES (?, ?, ?, ?)''', 
                           (user_id, item['nmId'], item['price'], item['discount']))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error in update_wb_prices: {e}")

# 🤖 Обработчики команд и сообщений
@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        add_user(message.chat.id)
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("✅ Я подписан", callback_data="check_subscription"))
        welcome_text = (
            "🚀 Добро пожаловать в бот 'Стоп Акция'! 🚀\n\n"
            f"🔔 Для начала работы, пожалуйста, подпишитесь на наш канал: {CHANNEL_ID}\n\n"
            "🌟 С нами вы сможете:\n"
            "   • 📊 Автоматически отслеживать товары в акциях\n"
            "   • ⚡ Быстро реагировать на изменения цен\n"
            "   • 💰 Увеличить вашу прибыль\n\n"
            "👇 Нажмите кнопку ниже, когда будете готовы начать!"
        )
        bot.reply_to(message, welcome_text, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error in send_welcome: {e}")
        bot.reply_to(message, "❌ Произошла ошибка при запуске бота. Пожалуйста, попробуйте позже.")

@bot.callback_query_handler(func=lambda call: call.data == "check_subscription")
def handle_subscription_check(call):
    try:
        if check_subscription(call.message.chat.id):
            show_main_menu(call.message)
        else:
            bot.answer_callback_query(call.id, "📢 Пожалуйста, подпишитесь на канал для использования бота.")
    except Exception as e:
        logger.error(f"Error in handle_subscription_check: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка. Пожалуйста, попробуйте позже.")

def show_main_menu(message):
    try:
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("👤 Мой профиль", callback_data="profile"),
            InlineKeyboardButton("🛒 WB", callback_data="wb"),
            InlineKeyboardButton("🛍 Ozon", callback_data="ozon"),
            InlineKeyboardButton("❓ Помощь", callback_data="help")
        )
        bot.send_message(message.chat.id, "🔍 Выберите действие:", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error in show_main_menu: {e}")
        bot.reply_to(message, "❌ Произошла ошибка при отображении меню. Пожалуйста, попробуйте позже.")

@bot.callback_query_handler(func=lambda call: call.data == "profile")
def profile_callback(call):
    try:
        show_profile(call.message)
    except Exception as e:
        logger.error(f"Error in profile_callback: {e}")
        bot.answer_callback_query(call.id, "❌ Не удалось загрузить профиль. Пожалуйста, попробуйте позже.")

@bot.callback_query_handler(func=lambda call: call.data in ["wb", "ozon"])
def handle_marketplace(call):
    try:
        if not check_subscription(call.message.chat.id):
            bot.answer_callback_query(call.id, "⚠️ Для доступа к этому разделу необходима активная подписка.")
            return

        marketplace = "Wildberries" if call.data == "wb" else "Ozon"
        keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        keyboard.add(
            KeyboardButton("⚙️ Настройки"),
            KeyboardButton("🚫 Исключение по товару"),
            KeyboardButton("✅ Включить мониторинг"),
            KeyboardButton("❌ Отключить мониторинг")
        )
        if call.data == "wb":
            keyboard.add(KeyboardButton("📊 Загрузить шаблон цен"))
        
        inline_keyboard = InlineKeyboardMarkup()
        inline_keyboard.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_main"))
        
        bot.send_message(
            call.message.chat.id,
            f"🛍 Вы выбрали {marketplace}.\n\n🔍 Выберите действие или вернитесь назад:",
            reply_markup=keyboard
        )
        bot.send_message(
            call.message.chat.id,
            "📌 Для возврата в главное меню нажмите кнопку ниже:",
            reply_markup=inline_keyboard
        )
    except Exception as e:
        logger.error(f"Error in handle_marketplace: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка. Пожалуйста, попробуйте позже.")

@bot.callback_query_handler(func=lambda call: call.data == "back_to_main")
def back_to_main(call):
    try:
        show_main_menu(call.message)
    except Exception as e:
        logger.error(f"Error in back_to_main: {e}")
        bot.answer_callback_query(call.id, "❌ Не удалось вернуться в главное меню. Пожалуйста, попробуйте позже.")

@bot.callback_query_handler(func=lambda call: call.data == "help")
def show_help(call):
    try:
        help_text = """
        🤖 Команды бота:
        /start - Начать работу с ботом
        /profile - Просмотр профиля
        /help - Показать эту справку
        
        📊 Для управления товарами используйте кнопки в меню или следующие команды:
        /remove_ozon_[ID] - Удалить товар из акции Ozon
        /return_wb_[ID] - Вернуть скидку товара на Wildberries
        /auto_cancel_on - Включить автоматическую отмену акций
        /auto_cancel_off - Выключить автоматическую отмену акций
        """
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_main"))
        bot.edit_message_text(help_text, call.message.chat.id, call.message.message_id, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error in show_help: {e}")
        bot.answer_callback_query(call.id, "❌ Не удалось отобразить справку. Пожалуйста, попробуйте позже.")

def show_profile(message):
    try:
        user_id = message.chat.id
        cursor.execute("SELECT subscription_end, balance, auto_cancel_enabled FROM users WHERE chat_id = ?", (user_id,))
        result = cursor.fetchone()
        if result:
            subscription_end, balance, auto_cancel_enabled = result
            referral_count = get_referral_count(user_id)
            profile_text = (
                "👤 Ваш профиль:\n\n"
                f"📅 Дата истечения подписки: {subscription_end}\n"
                f"👥 Вы пригласили: {referral_count} пользователей\n"
                f"🔄 Автоотмена акций: {'✅ Включена' if auto_cancel_enabled else '❌ Выключена'}\n\n"
                "🎁 За каждого приглашенного пользователя вы получаете:\n"
                "   скидку 10% на подписку\n\n"
                "🔗 Ваша реферальная ссылка:\n"
                f"https://t.me/your_bot_username?start={user_id}"
            )
            keyboard = InlineKeyboardMarkup(row_width=2)
            keyboard.add(
                InlineKeyboardButton("💼 Тарифы", callback_data="tariffs"),
                InlineKeyboardButton("🆘 Поддержка", callback_data="support"),
                InlineKeyboardButton("◀️ Вернуться в меню", callback_data="back_to_main"),
                InlineKeyboardButton("🔗 Поделиться ссылкой", callback_data="share_referral")
            )
            bot.send_message(message.chat.id, profile_text, reply_markup=keyboard)
        else:
            bot.send_message(message.chat.id, "❌ Произошла ошибка при получении данных профиля")
    except Exception as e:
        logger.error(f"Error in show_profile: {e}")
        bot.send_message(message.chat.id, "❌ Не удалось загрузить профиль. Пожалуйста, попробуйте позже.")

@bot.callback_query_handler(func=lambda call: call.data == "support")
def show_support(call):
    try:
        support_text = (
            "🆘 Служба поддержки\n\n"
            "Если у вас возникли вопросы или проблемы, пожалуйста, свяжитесь с нами.\n"
        )
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("📝 Написать в поддержку", url="https://t.me/shelbitofficial"))
        keyboard.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_profile"))
        bot.edit_message_text(support_text, call.message.chat.id, call.message.message_id, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in show_support: {e}")
        bot.answer_callback_query(call.id, "❌ Не удалось отобразить информацию о поддержке. Пожалуйста, попробуйте позже.")

@bot.callback_query_handler(func=lambda call: call.data == "back_to_profile")
def back_to_profile(call):
    try:
        show_profile(call.message)
    except Exception as e:
        logger.error(f"Error in back_to_profile: {e}")
        bot.answer_callback_query(call.id, "❌ Не удалось вернуться к профилю. Пожалуйста, попробуйте позже.")

@bot.callback_query_handler(func=lambda call: call.data == "tariffs")
def show_tariffs(call):
    try:
        tariffs_text = (
            "💼 <b>Тарифы</b>\n\n"
            "🌟 Доступ ко ВСЕМ функциям бота\n"
            "🚫 БЕЗ ОГРАНИЧЕНИЙ\n"
            "📢 БЕЗ РЕКЛАМЫ\n\n"
            "1️⃣ <b>Базовый</b>\n"
            "   ⏱ 1 месяц\n"
            "   💰 Цена: 499 руб.\n"
            "   ✨ Идеально для начинающих\n\n"
            "2️⃣ <b>Премиум</b>\n"
            "   ⏱ 1 год\n"
            "   💰 Цена: 4990 руб.\n"
            "   💥 Экономия 25%\n"
            "   🎁 Бонус: персональная консультация"
        )
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("Базовый", callback_data="subscribe_1month"),
            InlineKeyboardButton("Премиум", callback_data="subscribe_1year"),
            InlineKeyboardButton("🎟 Промокод", callback_data="enter_promo"),
            InlineKeyboardButton("◀️ Назад", callback_data="back_to_profile")
        )
        bot.edit_message_text(tariffs_text, call.message.chat.id, call.message.message_id, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in show_tariffs: {e}")
        bot.answer_callback_query(call.id, "❌ Не удалось отобразить тарифы. Пожалуйста, попробуйте позже.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("subscribe_"))
def handle_subscription(call):
    try:
        duration = "1 month" if call.data == "subscribe_1month" else "1 year"
        price = 49900 if duration == "1 month" else 499000  # в копейках

        bot.send_invoice(
            call.message.chat.id,
            title=f"Подписка на {duration}",
            description=f"Доступ ко всем функциям бота на {duration}",
            provider_token=PAYMENT_TOKEN,
            currency="RUB",
            prices=[LabeledPrice(label=f"Подписка на {duration}", amount=price)],
            start_parameter="subscription",
            invoice_payload=f"sub_{duration}"
        )
    except Exception as e:
        logger.error(f"Error in handle_subscription: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка при оформлении подписки. Пожалуйста, попробуйте позже.")

@bot.pre_checkout_query_handler(func=lambda query: True)
def process_pre_checkout_query(pre_checkout_query):
    try:
        bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
    except Exception as e:
        logger.error(f"Error in process_pre_checkout_query: {e}")
        bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="❌ Произошла ошибка при обработке платежа.")

@bot.message_handler(content_types=['successful_payment'])
def process_successful_payment(message):
    try:
        duration = "1 month" if message.successful_payment.invoice_payload == "sub_1 month" else "1 year"
        cursor.execute(f"UPDATE users SET subscription_end = date('now', '+{duration}') WHERE chat_id = ?", (message.chat.id,))
        conn.commit()
        bot.send_message(message.chat.id, f"✅ Спасибо за оплату! Ваша подписка на {duration} активирована.")
        show_main_menu(message)
    except Exception as e:
        logger.error(f"Error in process_successful_payment: {e}")
        bot.send_message(message.chat.id, "❌ Произошла ошибка при активации подписки. Пожалуйста, обратитесь в поддержку.")

@bot.callback_query_handler(func=lambda call: call.data == "enter_promo")
def ask_for_promo_code(call):
    try:
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "🎟 Введите промокод:")
        bot.register_next_step_handler(msg, process_promo_code)
    except Exception as e:
        logger.error(f"Error in ask_for_promo_code: {e}")
        bot.send_message(call.message.chat.id, "❌ Произошла ошибка. Пожалуйста, попробуйте позже.")

def process_promo_code(message):
    try:
        promo_code = message.text.strip().upper()
        discount = use_promo_code(promo_code, message.chat.id)
        if discount:
            success_text = (
                "✅ Промокод успешно применен!\n\n"
                f"🎉 Ваша подписка продлена на 30 дней.\n"
                f"💰 Скидка: {discount}%\n\n"
                "Спасибо за использование нашего бота!"
            )
            bot.reply_to(message, success_text)
        else:
            bot.reply_to(message, "❌ Неверный промокод или он уже был использован.")
        show_profile(message)
    except Exception as e:
        logger.error(f"Error in process_promo_code: {e}")
        bot.reply_to(message, "❌ Произошла ошибка при обработке промокода. Пожалуйста, попробуйте позже.")

@bot.callback_query_handler(func=lambda call: call.data == "share_referral")
def share_referral(call):
    try:
        user_id = call.message.chat.id
        referral_link = f"https://t.me/your_bot_username?start={user_id}"
        share_text = (
            "🔗 Ваша реферальная ссылка:\n\n"
            f"{referral_link}\n\n"
            "📢 Поделитесь ею с друзьями и получите:\n"
            "   • 💰 10% скидку на подписку за каждого приглашенного\n"
            "   • 🎁 Дополнительные бонусы при достижении определенного количества рефералов\n\n"
            "🤝 Вместе мы сможем сделать управление товарами в акциях еще эффективнее!"
        )
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("📤 Поделиться в Telegram", switch_inline_query=f"Попробуй бот для управления акциями! {referral_link}"))
        bot.send_message(call.message.chat.id, share_text, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error in share_referral: {e}")
        bot.answer_callback_query(call.id, "❌ Не удалось сгенерировать реферальную ссылку. Пожалуйста, попробуйте позже.")

@bot.message_handler(func=lambda message: message.text in ["⚙️ Настройки", "🚫 Исключение по товару", "✅ Включить мониторинг", "❌ Отключить мониторинг", "📊 Загрузить шаблон цен"])
def handle_marketplace_actions(message):
    try:
        if not check_subscription(message.chat.id):
            bot.reply_to(message, "⚠️ Для доступа к этому разделу необходима активная подписка.")
            return

        if message.text == "⚙️ Настройки":
            show_settings(message)
        elif message.text == "🚫 Исключение по товару":
            bot.reply_to(message, "🔢 Введите ID товара для добавления в исключения:")
            bot.register_next_step_handler(message, process_add_exception)
        elif message.text == "✅ Включить мониторинг":
            enable_monitoring(message)
        elif message.text == "❌ Отключить мониторинг":
            disable_monitoring(message)
        elif message.text == "📊 Загрузить шаблон цен":
            bot.reply_to(message, "📁 Пожалуйста, отправьте файл с шаблоном цен в формате CSV.")
            bot.register_next_step_handler(message, process_price_template)
    except Exception as e:
        logger.error(f"Error in handle_marketplace_actions: {e}")
        bot.reply_to(message, "❌ Произошла ошибка. Пожалуйста, попробуйте позже.")

def show_settings(message):
    try:
        user_id = message.chat.id
        cursor.execute("SELECT wb_api_key, ozon_api_key FROM users WHERE chat_id = ?", (user_id,))
        result = cursor.fetchone()
        
        keyboard = InlineKeyboardMarkup()
        if result:
            wb_api_key, ozon_api_key = result
            if wb_api_key:
                keyboard.row(InlineKeyboardButton("🔄 Обновить интеграцию с Wildberries", callback_data="integrate_wb"))
            else:
                keyboard.row(InlineKeyboardButton("🔗 Интеграция с Wildberries", callback_data="integrate_wb"))
            if ozon_api_key:
                keyboard.row(InlineKeyboardButton("🔄 Обновить интеграцию с Ozon", callback_data="integrate_ozon"))
            else:
                keyboard.row(InlineKeyboardButton("🔗 Интеграция с Ozon", callback_data="integrate_ozon"))
        
        keyboard.row(InlineKeyboardButton("🔄 Настройка автоотмены", callback_data="auto_cancel_settings"))
        keyboard.row(InlineKeyboardButton("◀️ Назад", callback_data="back_to_marketplace"))
        
        settings_text = (
            "⚙️ <b>Настройки</b>\n\n"
            "Здесь вы можете настроить интеграцию с маркетплейсами и другие параметры бота.\n\n"
            "🔍 Выберите действие из меню ниже:"
        )
        bot.send_message(message.chat.id, settings_text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in show_settings: {e}")
        bot.reply_to(message, "❌ Не удалось отобразить настройки. Пожалуйста, попробуйте позже.")

@bot.callback_query_handler(func=lambda call: call.data in ["integrate_ozon", "integrate_wb"])
def handle_integration(call):
    try:
        marketplace = "Ozon" if call.data == "integrate_ozon" else "Wildberries"
        bot.answer_callback_query(call.id)
        integration_text = (
            f"🔗 <b>Интеграция с {marketplace}</b>\n\n"
            f"Для интеграции с {marketplace} нам потребуется ваш API ключ.\n"
            "Пожалуйста, введите его в следующем сообщении.\n\n"
            "❓ Если вы не знаете, где найти API ключ, следуйте инструкции:\n"
            f"1. Войдите в личный кабинет {marketplace}\n"
            "2. Перейдите в раздел настроек\n"
            "3. Найдите пункт 'API' или 'Интеграции'\n"
            "4. Скопируйте ваш API ключ\n\n"
            "⚠️ Никогда не передавайте свой API ключ третьим лицам!"
        )
        msg = bot.send_message(call.message.chat.id, integration_text, parse_mode="HTML")
        bot.register_next_step_handler(msg, process_api_key, marketplace)
    except Exception as e:
        logger.error(f"Error in handle_integration: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка. Пожалуйста, попробуйте позже.")

def process_api_key(message, marketplace):
    try:
        api_key = message.text.strip()
        if marketplace == "Ozon":
            msg = bot.reply_to(message, "🆔 Теперь введите ваш Client ID для Ozon:")
            bot.register_next_step_handler(msg, process_client_id, api_key)
        else:
            update_marketplace_credentials(message.chat.id, 'wb', api_key)
            success_text = (
                "✅ Интеграция с Wildberries успешно завершена!\n\n"
                "Теперь вы можете использовать все функции бота для работы с акциями на Wildberries.\n"
                "🔍 Если у вас возникнут вопросы, не стесняйтесь обращаться в службу поддержки."
            )
            bot.reply_to(message, success_text)
            show_settings(message)
    except Exception as e:
        logger.error(f"Error in process_api_key: {e}")
        bot.reply_to(message, "❌ Произошла ошибка при обработке API ключа. Пожалуйста, попробуйте позже.")

def process_client_id(message, api_key):
    try:
        client_id = message.text.strip()
        update_marketplace_credentials(message.chat.id, 'ozon', api_key, client_id)
        success_text = (
            "✅ Интеграция с Ozon успешно завершена!\n\n"
            "Теперь вы можете использовать все функции бота для работы с акциями на Ozon.\n"
            "🔍 Если у вас возникнут вопросы, не стесняйтесь обращаться в службу поддержки."
        )
        bot.reply_to(message, success_text)
        show_settings(message)
    except Exception as e:
        logger.error(f"Error in process_client_id: {e}")
        bot.reply_to(message, "❌ Произошла ошибка при обработке Client ID. Пожалуйста, попробуйте позже.")

@bot.callback_query_handler(func=lambda call: call.data == "auto_cancel_settings")
def auto_cancel_settings(call):
    try:
        user_id = call.message.chat.id
        current_status = get_auto_cancel_status(user_id)
        status_text = "включена" if current_status else "выключена"
        
        settings_text = (
            "🔄 <b>Настройка автоотмены акций</b>\n\n"
            f"Текущий статус: <b>{status_text}</b>\n\n"
            "При включенной автоотмене бот будет автоматически отменять акции на ваши товары через час после уведомления, "
            "если вы не предприняли никаких действий.\n\n"
            "🔍 Выберите действие:"
        )
        
        keyboard = InlineKeyboardMarkup()
        keyboard.row(InlineKeyboardButton("✅ Включить" if not current_status else "❌ Выключить", 
                                          callback_data="toggle_auto_cancel"))
        keyboard.row(InlineKeyboardButton("◀️ Назад", callback_data="back_to_settings"))
        
        bot.edit_message_text(settings_text, call.message.chat.id, call.message.message_id, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in auto_cancel_settings: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка. Пожалуйста, попробуйте позже.")

@bot.callback_query_handler(func=lambda call: call.data == "toggle_auto_cancel")
def toggle_auto_cancel(call):
    try:
        user_id = call.message.chat.id
        current_status = get_auto_cancel_status(user_id)
        new_status = not current_status
        set_auto_cancel(user_id, new_status)
        
        status_text = "включена" if new_status else "выключена"
        bot.answer_callback_query(call.id, f"✅ Автоотмена акций {status_text}")
        
        # Обновляем сообщение с настройками
        auto_cancel_settings(call)
    except Exception as e:
        logger.error(f"Error in toggle_auto_cancel: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка. Пожалуйста, попробуйте позже.")

@bot.callback_query_handler(func=lambda call: call.data == "back_to_settings")
def back_to_settings(call):
    try:
        show_settings(call.message)
    except Exception as e:
        logger.error(f"Error in back_to_settings: {e}")
        bot.answer_callback_query(call.id, "❌ Не удалось вернуться к настройкам. Пожалуйста, попробуйте позже.")

@bot.callback_query_handler(func=lambda call: call.data == "back_to_marketplace")
def back_to_marketplace(call):
    try:
        keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        keyboard.add(
            KeyboardButton("⚙️ Настройки"),
            KeyboardButton("🚫 Исключение по товару"),
            KeyboardButton("✅ Включить мониторинг"),
            KeyboardButton("❌ Отключить мониторинг"),
            KeyboardButton("📊 Загрузить шаблон цен")
        )
        
        inline_keyboard = InlineKeyboardMarkup()
        inline_keyboard.add(InlineKeyboardButton("◀️ Назад в главное меню", callback_data="back_to_main"))
        
        bot.send_message(
            call.message.chat.id,
            "🔍 Выберите действие или вернитесь в главное меню:",
            reply_markup=keyboard
        )
        bot.send_message(
            call.message.chat.id,
            "📌 Для возврата в главное меню нажмите кнопку ниже:",
            reply_markup=inline_keyboard
        )
        
        # Удаляем предыдущее сообщение с настройками
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception as e:
        logger.error(f"Error in back_to_marketplace: {e}")
        bot.answer_callback_query(call.id, "❌ Не удалось вернуться к настройкам маркетплейса. Пожалуйста, попробуйте позже.")

def process_add_exception(message):
    try:
        product_id = message.text.strip()
        add_ignored_product(message.chat.id, "both", product_id)
        success_text = (
            f"✅ Товар с ID {product_id} успешно добавлен в исключения.\n\n"
            "Теперь этот товар не будет учитываться при автоматическом мониторинге акций.\n"
            "🔍 Вы всегда можете изменить список исключений в настройках бота."
        )
        bot.reply_to(message, success_text)
    except Exception as e:
        logger.error(f"Error in process_add_exception: {e}")
        bot.reply_to(message, "❌ Произошла ошибка при добавлении исключения. Пожалуйста, попробуйте позже.")

def enable_monitoring(message):
    try:
        user_id = message.chat.id
        cursor.execute("UPDATE users SET monitoring_enabled = 1 WHERE chat_id = ?", (user_id,))
        conn.commit()
        success_text = (
            "✅ Мониторинг товаров успешно включен!\n\n"
            "Теперь бот будет автоматически отслеживать акции на ваши товары и уведомлять вас о них.\n"
            "🔍 Вы всегда можете изменить настройки мониторинга в разделе настроек."
        )
        bot.reply_to(message, success_text)
    except Exception as e:
        logger.error(f"Error in enable_monitoring: {e}")
        bot.reply_to(message, "❌ Не удалось включить мониторинг. Пожалуйста, попробуйте позже.")

def disable_monitoring(message):
    try:
        user_id = message.chat.id
        cursor.execute("UPDATE users SET monitoring_enabled = 0 WHERE chat_id = ?", (user_id,))
        conn.commit()
        warning_text = (
            "❌ Мониторинг товаров отключен.\n\n"
            "⚠️ Внимание: теперь вы не будете получать уведомления о новых акциях на ваши товары.\n"
            "🔍 Рекомендуем включить мониторинг, чтобы всегда быть в курсе изменений."
        )
        bot.reply_to(message, warning_text)
    except Exception as e:
        logger.error(f"Error in disable_monitoring: {e}")
        bot.reply_to(message, "❌ Не удалось отключить мониторинг. Пожалуйста, попробуйте позже.")

@bot.message_handler(func=lambda message: message.text.startswith('/remove_ozon_'))
def remove_ozon_product(message):
    try:
        if not check_subscription(message.chat.id):
            bot.reply_to(message, "❗ Ваша подписка истекла. Пожалуйста, обновите подписку.")
            return

        product_id = message.text.split('_')[-1]
        ozon_credentials = get_marketplace_credentials(message.chat.id, 'ozon')
        if ozon_credentials:
            ozon_api_key, ozon_client_id = ozon_credentials['api_key'], ozon_credentials['client_id']
            if remove_ozon_product_from_promo(ozon_api_key, ozon_client_id, product_id):
                success_text = (
                    f"✅ Товар с ID {product_id} успешно удален из акции Ozon.\n\n"
                    "ℹ️ Изменения могут отражаться на платформе с небольшой задержкой.\n"
                    "🔍 Рекомендуем проверить статус товара через некоторое время."
                )
                bot.reply_to(message, success_text)
                log_action(message.chat.id, 'ozon', 'remove_from_promo', product_id)
            else:
                bot.reply_to(message, f"❌ Не удалось удалить товар с ID {product_id} из акции Ozon.")
        else:
            bot.reply_to(message, "❗ Не удалось получить данные для доступа к API Ozon. Пожалуйста, проверьте настройки интеграции.")
    except Exception as e:
        logger.error(f"Error in remove_ozon_product: {e}")
        bot.reply_to(message, "❌ Произошла ошибка при удалении товара из акции. Пожалуйста, попробуйте позже.")

@bot.message_handler(func=lambda message: message.text.startswith('/return_wb_'))
def return_wb_discount(message):
    try:
        if not check_subscription(message.chat.id):
            bot.reply_to(message, "❗ Ваша подписка истекла. Пожалуйста, обновите подписку.")
            return

        product_id = message.text.split('_')[-1]
        wb_credentials = get_marketplace_credentials(message.chat.id, 'wb')
        if wb_credentials:
            wb_api_key = wb_credentials['api_key']
            product_data = {
                "nmId": int(product_id),
                "discount": 0
            }
            if update_wb_product_discount(wb_api_key, product_data):
                success_text = (
                    f"✅ Скидка для товара с ID {product_id} успешно возвращена на Wildberries.\n\n"
                    "ℹ️ Изменения могут отражаться на платформе с небольшой задержкой.\n"
                    "🔍 Рекомендуем проверить статус товара через некоторое время."
                )
                bot.reply_to(message, success_text)
                log_action(message.chat.id, 'wb', 'return_discount', product_id)
            else:
                bot.reply_to(message, f"❌ Не удалось вернуть скидку для товара с ID {product_id} на Wildberries.")
        else:
            bot.reply_to(message, "❗ Не удалось получить данные для доступа к API Wildberries. Пожалуйста, проверьте настройки интеграции.")
    except Exception as e:
        logger.error(f"Error in return_wb_discount: {e}")
        bot.reply_to(message, "❌ Произошла ошибка при возврате скидки. Пожалуйста, попробуйте позже.")

@bot.message_handler(commands=['feedback'])
def send_feedback(message):
    try:
        feedback_text = (
            "📝 <b>Отправка отзыва</b>\n\n"
            "Мы ценим ваше мнение и постоянно работаем над улучшением нашего сервиса.\n"
            "Пожалуйста, напишите ваш отзыв или предложение в следующем сообщении.\n\n"
            "🌟 Ваш отзыв поможет нам сделать бот еще лучше!"
        )
        msg = bot.reply_to(message, feedback_text, parse_mode="HTML")
        bot.register_next_step_handler(msg, process_feedback)
    except Exception as e:
        logger.error(f"Error in send_feedback: {e}")
        bot.reply_to(message, "❌ Произошла ошибка. Пожалуйста, попробуйте отправить отзыв позже.")

def process_feedback(message):
    try:
        feedback = message.text
        # Здесь можно сохранить отзыв в базу данных или отправить администратору
        cursor.execute("INSERT INTO feedback (user_id, feedback, date) VALUES (?, ?, datetime('now'))", 
                       (message.chat.id, feedback))
        conn.commit()
        thank_you_text = (
            "🙏 Спасибо за ваш отзыв!\n\n"
            "Мы внимательно изучим ваше сообщение и учтем его в нашей работе.\n"
            "Ваше мнение очень важно для нас и помогает улучшать качество сервиса.\n\n"
            "💬 Если у вас возникнут дополнительные вопросы или предложения, не стесняйтесь обращаться к нам снова!"
        )
        bot.reply_to(message, thank_you_text)
    except Exception as e:
        logger.error(f"Error in process_feedback: {e}")
        bot.reply_to(message, "❌ Произошла ошибка при обработке отзыва. Пожалуйста, попробуйте позже.")

# 🔄 Функция для периодического мониторинга и уведомлений
def scheduled_monitoring():
    try:
        cursor.execute("""
            SELECT chat_id, ozon_api_key, ozon_client_id, wb_api_key, auto_cancel_enabled 
            FROM users 
            WHERE subscription_end >= date('now') AND monitoring_enabled = 1
        """)
        active_users = cursor.fetchall()
        
        for user in active_users:
            chat_id, ozon_api_key, ozon_client_id, wb_api_key, auto_cancel_enabled = user
            
            logger.info(f"Processing user {chat_id}")
            
            # Мониторинг Ozon
            if ozon_api_key and ozon_client_id:
                try:
                    ozon_actions = get_ozon_actions(ozon_api_key, ozon_client_id)
                    update_ozon_actions(chat_id, ozon_actions)
                    for action in ozon_actions:
                        if action['is_participating']:
                            ozon_products = get_ozon_promo_products(ozon_api_key, ozon_client_id, action['id'])
                            process_ozon_products(chat_id, ozon_products, action, auto_cancel_enabled)
                except Exception as e:
                    logger.error(f"Error processing Ozon actions for user {chat_id}: {e}")
            
            # Мониторинг Wildberries
            if wb_api_key:
                try:
                    wb_actions = get_wb_actions(wb_api_key)
                    update_wb_actions(chat_id, wb_actions)
                    for action in wb_actions:
                        if action['isActive']:
                            wb_products = get_wb_promo_products(wb_api_key, action['id'])
                            process_wb_products(chat_id, wb_products, action, auto_cancel_enabled)
                except Exception as e:
                    logger.error(f"Error processing Wildberries actions for user {chat_id}: {e}")

    except Exception as e:
        logger.error(f"Error in scheduled_monitoring: {e}")

def process_ozon_products(chat_id, products, action, auto_cancel_enabled):
    if products and 'items' in products:
        ignored_products = get_ignored_products(chat_id, "ozon")
        for product in products['items']:
            if product['product_id'] not in ignored_products:
                message = (
                    f"🛍 <b>Товар Ozon в акции \"{action['title']}\":</b>\n\n"
                    f"🆔 ID: {product['product_id']}\n"
                    f"📦 Название: {product.get('name', 'Нет названия')}\n"
                    f"💰 Цена: {product.get('price', 'Не указана')}\n"
                    f"🏷 Цена со скидкой: {product.get('discount_price', 'Не указана')}\n\n"
                    "Выберите действие:"
                )
                keyboard = InlineKeyboardMarkup()
                keyboard.add(InlineKeyboardButton("🚫 Удалить из акции", callback_data=f"remove_ozon_{product['product_id']}"))
                keyboard.add(InlineKeyboardButton("🙈 Игнорировать товар", callback_data=f"ignore_ozon_{product['product_id']}"))
                keyboard.add(InlineKeyboardButton("📊 Подробная статистика", callback_data=f"stats_ozon_{product['product_id']}"))
                try:
                    bot.send_message(chat_id, message, reply_markup=keyboard, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Error sending Ozon message to user {chat_id}: {e}")
                
                if auto_cancel_enabled:
                    add_pending_action(chat_id, 'ozon', product['product_id'], 'remove_from_promo')

def process_wb_products(chat_id, products, action, auto_cancel_enabled):
    if products:
        ignored_products = get_ignored_products(chat_id, "wb")
        for product in products:
            if str(product.get('nmId', '')) not in ignored_products:
                message = (
                    f"🛒 <b>Товар Wildberries в акции \"{action['name']}\":</b>\n\n"
                    f"🆔 ID: {product.get('nmId', 'Нет ID')}\n"
                    f"📦 Название: {product.get('name', 'Нет названия')}\n"
                    f"💰 Цена: {product.get('price', 'Не указана')}\n"
                    f"🏷 Скидка: {product.get('discount', 'Не указана')}%\n\n"
                    "Выберите действие:"
                )
                keyboard = InlineKeyboardMarkup()
                keyboard.add(InlineKeyboardButton("🔄 Вернуть скидку", callback_data=f"return_wb_{product.get('nmId', '')}"))
                keyboard.add(InlineKeyboardButton("🙈 Игнорировать товар", callback_data=f"ignore_wb_{product.get('nmId', '')}"))
                keyboard.add(InlineKeyboardButton("📊 Подробная статистика", callback_data=f"stats_wb_{product.get('nmId', '')}"))
                try:
                    bot.send_message(chat_id, message, reply_markup=keyboard, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Error sending Wildberries message to user {chat_id}: {e}")
                
                if auto_cancel_enabled:
                    add_pending_action(chat_id, 'wb', str(product.get('nmId', '')), 'return_discount')

# 🕒 Функция для обработки отложенных действий
def process_pending_actions():
    try:
        pending_actions = get_pending_actions()
        for action in pending_actions:
            action_id, user_id, marketplace, product_id, action_type = action
            
            if marketplace == 'ozon':
                ozon_credentials = get_marketplace_credentials(user_id, 'ozon')
                if ozon_credentials:
                    ozon_api_key, ozon_client_id = ozon_credentials['api_key'], ozon_credentials['client_id']
                    if remove_ozon_product_from_promo(ozon_api_key, ozon_client_id, product_id):
                        bot.send_message(user_id, f"✅ Товар с ID {product_id} автоматически удален из акции Ozon.")
                        log_action(user_id, 'ozon', 'auto_remove_from_promo', product_id)
                    else:
                        bot.send_message(user_id, f"❌ Не удалось автоматически удалить товар с ID {product_id} из акции Ozon.")
            elif marketplace == 'wb':
                wb_credentials = get_marketplace_credentials(user_id, 'wb')
                if wb_credentials:
                    wb_api_key = wb_credentials['api_key']
                    product_data = {
                        "nmId": int(product_id),
                        "discount": 0
                    }
                    if update_wb_product_discount(wb_api_key, product_data):
                        bot.send_message(user_id, f"✅ Скидка для товара с ID {product_id} автоматически возвращена на Wildberries.")
                        log_action(user_id, 'wb', 'auto_return_discount', product_id)
                    else:
                        bot.send_message(user_id, f"❌ Не удалось автоматически вернуть скидку для товара с ID {product_id} на Wildberries.")
            
            remove_pending_action(action_id)
    except Exception as e:
        logger.error(f"Error in process_pending_actions: {e}")

# 🚀 Запуск бота
if __name__ == "__main__":
    import threading
    import schedule
    import time

    def run_schedule():
        while True:
            schedule.run_pending()
            time.sleep(1)

    # Запланировать выполнение мониторинга каждые 30 минут
    schedule.every(10).minutes.do(scheduled_monitoring)
    
    # Запланировать обработку отложенных действий каждые 10 минут
    schedule.every(10).minutes.do(process_pending_actions)

    # Запустить планировщик в отдельном потоке
    schedule_thread = threading.Thread(target=run_schedule)
    schedule_thread.start()

    # Запустить бота
    while True:
        try:
            bot.polling(none_stop=True)
        except Exception as e:
            logger.error(f"Bot polling error: {e}")
            time.sleep(15)
