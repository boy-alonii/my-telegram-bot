import logging
import sqlite3
import re
import asyncio
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.utils import executor
from instagrapi import Client
from instagrapi.exceptions import ClientError

# ======== تنظیمات ========
class Config:
    BOT_TOKEN = "7658527196:AAFR0CacXbVWCK8k8F1Y52GTRuZf5TcWToA"
    INSTAGRAM_USERNAME = "teka._.shop"
    INSTAGRAM_PASSWORD = "TEKA._.shop/A&T"
    TELEGRAM_CHANNEL = "@staart_telegram"
    INSTAGRAM_PAGE = "teka._.shop"
    ADMIN_IDS = [7217622690]  # لیست ادمین‌ها
    VERIFICATION_EXPIRE_DAYS = 30  # مدت اعتبار تأیید
    MAX_LOGIN_ATTEMPTS = 3  # حداکثر تلاش برای ورود به اینستاگرام
    REQUEST_TIMEOUT = 30  # زمان‌بندی درخواست‌ها

# ======== لاگینگ ========
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ======== راه‌اندازی ========
bot = Bot(token=Config.BOT_TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# ======== مدیریت اینستاگرام ========
class InstagramManager:
    def __init__(self):
        self.client = Client()
        self.login_attempts = 0
        self._login()

    def _login(self):
        try:
            self.client.login(
                Config.INSTAGRAM_USERNAME,
                Config.INSTAGRAM_PASSWORD,
                relogin=True
            )
            logger.info("✅ ورود موفق به اینستاگرام")
            return True
        except ClientError as e:
            logger.error(f"❌ خطای ورود به اینستاگرام: {e}")
            return False

    def check_follow(self, username: str) -> bool:
        """بررسی آیا کاربر پیج ما را دنبال کرده است"""
        try:
            your_id = self.client.user_id_from_username(Config.INSTAGRAM_PAGE)
            user_id = self.client.user_id_from_username(username)
            followers = self.client.user_followers(your_id)
            return str(user_id) in followers
        except ClientError as e:
            logger.error(f"خطای بررسی فالوورها: {e}")
            return False

instagram = InstagramManager()

# ======== مدیریت دیتابیس ========
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('users.db', check_same_thread=False)
        self._init_db()

    def _init_db(self):
        """ایجاد جداول دیتابیس"""
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    telegram_username TEXT,
                    instagram_username TEXT,
                    verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_activity TIMESTAMP
                )
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS verification_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    instagram_username TEXT,
                    attempt_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    success BOOLEAN,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                )
            """)

    def is_verified(self, user_id: int) -> bool:
        """بررسی وضعیت تأیید کاربر"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT 1 FROM users 
            WHERE user_id = ? AND 
            verified_at > datetime('now', ?)
        """, (user_id, f"-{Config.VERIFICATION_EXPIRE_DAYS} days"))
        return cursor.fetchone() is not None

    def add_verified_user(self, user_id: int, tg_username: str, ig_username: str) -> bool:
        """ثبت کاربر تأیید شده"""
        try:
            with self.conn:
                self.conn.execute("""
                    INSERT OR REPLACE INTO users 
                    (user_id, telegram_username, instagram_username, last_activity)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                """, (user_id, tg_username or "بدون_یوزرنیم", ig_username))
                
                self.conn.execute("""
                    INSERT INTO verification_attempts 
                    (user_id, instagram_username, success)
                    VALUES (?, ?, ?)
                """, (user_id, ig_username, True))
            return True
        except sqlite3.Error as e:
            logger.error(f"خطای دیتابیس: {e}")
            return False

    def log_failed_attempt(self, user_id: int, ig_username: str) -> None:
        """ثبت تلاش ناموفق"""
        try:
            with self.conn:
                self.conn.execute("""
                    INSERT INTO verification_attempts 
                    (user_id, instagram_username, success)
                    VALUES (?, ?, ?)
                """, (user_id, ig_username, False))
        except sqlite3.Error as e:
            logger.error(f"خطای ثبت لاگ: {e}")

db = Database()

# ======== دستورات ربات ========
async def check_telegram_membership(user_id: int) -> bool:
    """بررسی عضویت در کانال تلگرام"""
    try:
        member = await bot.get_chat_member(Config.TELEGRAM_CHANNEL, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.error(f"خطای بررسی عضویت: {e}")
        return False

@dp.message_handler(commands=['start', 'help'])
async def cmd_start(message: types.Message):
    """دستور شروع ربات"""
    user = message.from_user
    
    if db.is_verified(user.id):
        await message.reply("✅ شما قبلاً تأیید شده‌اید و می‌توانید از ربات استفاده کنید.")
        return

    is_member = await check_telegram_membership(user.id)
    if not is_member:
        await message.reply(
            f"⚠️ برای استفاده از ربات، لطفاً در کانال ما عضو شوید:\n"
            f"{Config.TELEGRAM_CHANNEL}\n\n"
            "پس از عضویت، دوباره /start را ارسال کنید."
        )
        return
    
    await message.reply(
        f"سلام {user.first_name} 👋\n\n"
        f"📌 برای ادامه:\n"
        f"1. پیج اینستاگرام ما را دنبال کنید:\n"
        f"https://instagram.com/{Config.INSTAGRAM_PAGE}\n\n"
        "2. یوزرنیم اینستاگرام خود را ارسال کنید (بدون @):"
    )

@dp.message_handler(content_types=types.ContentTypes.TEXT)
async def process_username(message: types.Message):
    """پردازش یوزرنیم اینستاگرام"""
    user = message.from_user
    ig_username = message.text.strip().replace("@", "").lower()
    
    # اعتبارسنجی یوزرنیم
    if not re.match(r"^[a-zA-Z0-9._]{3,30}$", ig_username):
        await message.reply("❌ یوزرنیم نامعتبر! فقط از حروف انگلیسی و اعداد استفاده کنید.")
        return
    
    if db.is_verified(user.id):
        await message.reply("✅ شما قبلاً تأیید شده‌اید.")
        return
    
    await message.reply("🔍 در حال بررسی اطلاعات... لطفاً صبر کنید")
    
    # بررسی عضویت در کانال
    if not await check_telegram_membership(user.id):
        await message.reply("⚠️ شما از کانال خارج شده‌اید. لطفاً دوباره عضو شوید.")
        return
    
    # بررسی فالو اینستاگرام
    if instagram.check_follow(ig_username):
        if db.add_verified_user(user.id, user.username, ig_username):
            await message.reply(
                "🎉 تأیید شما با موفقیت انجام شد!\n\n"
                "اکنون می‌توانید از امکانات ربات استفاده کنید."
            )
        else:
            await message.reply("❌ خطای سیستم! لطفاً بعداً تلاش کنید.")
    else:
        db.log_failed_attempt(user.id, ig_username)
        await message.reply(
            "❌ یا پیج ما را دنبال نکرده‌اید یا یوزرنیم اشتباه است.\n\n"
            "لطفاً:\n"
            f"1. مطمئن شوید @{Config.INSTAGRAM_PAGE} را دنبال کرده‌اید\n"
            "2. یوزرنیم خود را دقیق وارد کنید\n"
            "3. دوباره تلاش کنید"
        )

# ======== اجرای ربات ========
async def on_startup(dp):
    """فعالیت‌های هنگام راه‌اندازی"""
    logger.info("🚀 ربات در حال راه‌اندازی...")
    for admin_id in Config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, "🤖 ربات با موفقیت راه‌اندازی شد")
        except Exception as e:
            logger.error(f"خطا در ارسال به ادمین {admin_id}: {e}")

async def on_shutdown(dp):
    """فعالیت‌های هنگام خاموشی"""
    logger.info("🛑 ربات در حال خاموش شدن...")
    await dp.storage.close()
    await dp.storage.wait_closed()
    await bot.close()

if __name__ == "__main__":
    try:
        logger.info("🚀 شروع ربات تلگرام...")
        executor.start_polling(
            dp,
            skip_updates=True,
            on_startup=on_startup,
            on_shutdown=on_shutdown,
            timeout=60,
            relax=0.5
        )
    except Exception as e:
        logger.critical(f"🔥 خطای بحرانی: {e}")
    finally:
        logger.info("🛑 ربات متوقف شد")