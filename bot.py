# -*- coding: utf-8 -*-
"""
Telegram service-sales bot for Pydroid 3.
Library: python-telegram-bot 22.x
Set BOT_TOKEN below on your own device. Never share it publicly.
"""

import json
import logging
import os
import asyncio
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InputMediaPhoto,
)
from telegram.error import Forbidden, BadRequest, TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    TypeHandler,
    filters,
)

# ====== SETTINGS ======
# Set these in your environment or replace BOT_TOKEN locally with a NEW token.
# The token previously included in the uploaded file should be revoked in @BotFather.
BOT_TOKEN = os.getenv("BOT_TOKEN", "PASTE_NEW_BOT_TOKEN_HERE")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8928341236"))
DB_FILE = Path(__file__).with_name("orders.json")
MARKET_FILE = Path(__file__).with_name("game_account_listings.json")
SECRETARY_FILE = Path(__file__).with_name("secretary_settings.json")
ADMINS_FILE = Path(__file__).with_name("admins.json")
DISCOUNT_FILE = Path(__file__).with_name("discount_settings.json")
USERS_FILE = Path(__file__).with_name("users.json")
ACCESS_FILE = Path(__file__).with_name("access_settings.json")
SECTION_FILE = Path(__file__).with_name("section_settings.json")
PRICE_FILE = Path(__file__).with_name("price_settings.json")
PLAN_FILE = Path(__file__).with_name("plan_settings.json")
TEST_FILE = Path(__file__).with_name("test_accounts.json")
WALLET_FILE = Path(__file__).with_name("wallet.json")
# Serializes test-pool updates so two nearly simultaneous requests cannot take the same link.
TEST_ACCOUNTS_LOCK = asyncio.Lock()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Public prices seen in the screenshots. Verify/update these before accepting payments.
# Turkey VIP server was discontinued and is intentionally removed from the shop.
PRODUCTS = {
    "🎮 سرور وایرگاد گیمینگ VIP": [
        ("هر گیگابایت", 8000),
    ],
    "🌐 سرور وب‌گردی V2Ray": [
        ("هر گیگابایت", 5000),
    ],
    "♾️ سرور نامحدود VIP": [
        ("۱ ماه", 150000),
        ("۲ ماه", 300000),
        ("۳ ماه", 450000),
        ("۴ ماه", 600000),
        ("۵ ماه", 750000),
    ],
}

# Each panel has its own admin-controlled availability switch.
PANEL_SECTION_KEYS = {
    "🎮 سرور وایرگاد گیمینگ VIP": "gaming",
    "🌐 سرور وب‌گردی V2Ray": "v2ray",
    "♾️ سرور نامحدود VIP": "unlimited",
}


def load_price_overrides():
    """Load saved unit prices without changing the existing product structure."""
    if not PRICE_FILE.exists():
        return
    try:
        with PRICE_FILE.open("r", encoding="utf-8") as f:
            saved = json.load(f)
        for product, tiers in saved.items():
            if product not in PRODUCTS or not isinstance(tiers, dict):
                continue
            existing = {label: int(price) for label, price in PRODUCTS[product]}
            # Keep current default order, apply saved prices, then append admin-created tiers.
            rebuilt = [(label, int(tiers.get(label, price))) for label, price in PRODUCTS[product]]
            known = {label for label, _ in rebuilt}
            for label, price in tiers.items():
                if label not in known:
                    rebuilt.append((str(label), int(price)))
            PRODUCTS[product] = rebuilt
        # Exact plan structure preserves admin additions, renames and deletions across restarts.
        if PLAN_FILE.exists():
            with PLAN_FILE.open("r", encoding="utf-8") as f:
                saved_plans = json.load(f)
            if isinstance(saved_plans, dict):
                for product, tiers in saved_plans.items():
                    if product in PRODUCTS and isinstance(tiers, list) and tiers:
                        valid = []
                        for item in tiers:
                            if isinstance(item, dict) and "label" in item and "price" in item:
                                valid.append((str(item["label"]), int(item["price"])))
                        if valid:
                            PRODUCTS[product] = valid
    except Exception:
        logger.exception("Could not load saved price/plan overrides")


def save_price_overrides():
    data = {
        product: {label: int(price) for label, price in tiers}
        for product, tiers in PRODUCTS.items()
    }
    tmp = PRICE_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(PRICE_FILE)
    # Keep exact plan ordering/structure so add, rename and delete survive restart.
    plan_data = {product: [{"label": label, "price": int(price)} for label, price in tiers]
                 for product, tiers in PRODUCTS.items()}
    plan_tmp = PLAN_FILE.with_suffix(".tmp")
    with plan_tmp.open("w", encoding="utf-8") as f:
        json.dump(plan_data, f, ensure_ascii=False, indent=2)
    plan_tmp.replace(PLAN_FILE)


load_price_overrides()

MAIN_MENU = [
    ["🚀 خرید سرویس جدید", "🧪 اکانت تست"],
    ["💰 تعرفه سرویس‌ها"],
    ["📱 سرویس‌های من", "♻️ تمدید سرویس"],
    ["💡 آموزش استفاده"],
    ["🎗️ کاربران برتر", "👥 معرفی به دوستان"],
    ["🧑🏻‍💻 تماس با پشتیبانی"],
    ["🤝 درخواست نمایندگی"],
    ["🎮 شاپ اکانت بازی‌ها"],
    ["💎 خدمات مجازی"],
    ["🔙 بازگشت به انتخاب سرور", "🔙 منوی اصلی"],
]
MAIN_MARKUP = ReplyKeyboardMarkup(
    MAIN_MENU, resize_keyboard=True, one_time_keyboard=True, is_persistent=False
)




def load_admin_ids():
    """Return primary admin plus extra admin IDs saved in admins.json."""
    ids = {ADMIN_ID}
    if ADMINS_FILE.exists():
        try:
            with ADMINS_FILE.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            ids.update(int(value) for value in payload.get("admin_ids", []) if str(value).isdigit())
        except Exception:
            logger.exception("Could not read admins.json; using primary admin only")
    return ids


def save_admin_ids(ids):
    ids = {int(value) for value in ids}
    ids.add(ADMIN_ID)  # The primary admin cannot be removed.
    tmp = ADMINS_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump({"admin_ids": sorted(ids)}, f, ensure_ascii=False, indent=2)
    tmp.replace(ADMINS_FILE)


def is_admin(user_id):
    return int(user_id) in load_admin_ids()


def load_db():
    if not DB_FILE.exists():
        return {"next_id": 1001, "orders": {}}
    try:
        with DB_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if "next_id" not in data or "orders" not in data:
            raise ValueError("Invalid database format")
        # شماره نمایشی سفارش برای همه مشتریان به‌صورت سراسری و پیوسته است: 1، 2، 3...
        # شناسه داخلی id جدا می‌ماند تا سفارش‌های قبلی و دستورات ادمین خراب نشوند.
        changed = False
        all_orders = sorted(data["orders"].values(), key=lambda item: int(item.get("id", 0)))
        for number, order in enumerate(all_orders, start=1):
            if order.get("order_number") != number:
                order["order_number"] = number
                changed = True
        if changed:
            save_db(data)
        return data
    except Exception:
        logger.exception("Could not read orders.json")
        raise RuntimeError(
            "فایل orders.json قابل خواندن نیست. برای جلوگیری از حذف سفارش‌ها، "
            "فایل را پاک نکنید؛ محتوای آن را بررسی کنید."
        )


def save_db(data):
    tmp = DB_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(DB_FILE)


def load_wallet():
    """Persistent wallet balances and top-up requests, independent from orders.json."""
    if not WALLET_FILE.exists():
        return {"balances": {}, "requests": {}, "next_request_id": 1, "transactions": []}
    try:
        with WALLET_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("balances", {})
        data.setdefault("requests", {})
        data.setdefault("next_request_id", 1)
        data.setdefault("transactions", [])
        return data
    except Exception:
        logger.exception("Could not read wallet.json")
        raise RuntimeError("فایل wallet.json قابل خواندن نیست؛ برای جلوگیری از از دست رفتن اعتبار، آن را پاک نکنید.")


def save_wallet(data):
    tmp = WALLET_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(WALLET_FILE)


def wallet_balance(data, user_id):
    try:
        return max(0, int(data.get("balances", {}).get(str(user_id), 0)))
    except (TypeError, ValueError):
        return 0


def normalize_digits(value):
    return str(value).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))


def money(amount):
    return f"{amount:,} تومان"


def load_discount_percent():
    """Read the global config/service discount percentage (0..100)."""
    if not DISCOUNT_FILE.exists():
        return 0
    try:
        with DISCOUNT_FILE.open("r", encoding="utf-8") as f:
            value = int(json.load(f).get("percent", 0))
        return max(0, min(100, value))
    except Exception:
        logger.exception("Could not read discount_settings.json; using no discount")
        return 0


def save_discount_percent(percent):
    tmp = DISCOUNT_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump({"percent": int(percent)}, f, ensure_ascii=False, indent=2)
    tmp.replace(DISCOUNT_FILE)


def load_user_discount_percent(user_id):
    """Return a customer-specific discount if set, otherwise the global discount."""
    try:
        if DISCOUNT_FILE.exists():
            with DISCOUNT_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
            users = data.get("users", {})
            key = str(int(user_id))
            if key in users:
                return max(0, min(100, int(users[key])))
    except Exception:
        logger.exception("Could not read customer discounts")
    return load_discount_percent()


def save_user_discount_percent(user_id, percent):
    """Persist a customer-specific discount while preserving the global setting."""
    data = {}
    if DISCOUNT_FILE.exists():
        try:
            with DISCOUNT_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    data.setdefault("percent", 0)
    data.setdefault("users", {})
    key = str(int(user_id))
    if int(percent) == 0:
        data["users"].pop(key, None)
    else:
        data["users"][key] = int(percent)
    tmp = DISCOUNT_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(DISCOUNT_FILE)


def discounted_price(price, percent=None):
    if percent is None:
        percent = load_discount_percent()
    return round(int(price) * (100 - int(percent)) / 100)


def load_users():
    """Load users known to the bot, including users found in historical orders."""
    ids = set()
    if USERS_FILE.exists():
        try:
            with USERS_FILE.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            ids.update(int(x) for x in payload.get("user_ids", []) if str(x).isdigit())
        except Exception:
            logger.exception("Could not read users.json")
    try:
        db = load_db()
        ids.update(int(o["user_id"]) for o in db.get("orders", {}).values()
                   if str(o.get("user_id", "")).isdigit())
    except Exception:
        logger.exception("Could not recover users from orders")
    return ids


def remember_user(user_id):
    ids = load_users()
    ids.add(int(user_id))
    tmp = USERS_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump({"user_ids": sorted(ids)}, f, ensure_ascii=False, indent=2)
    tmp.replace(USERS_FILE)


def load_access_data():
    defaults = {"blocked_users": [], "banned_until": {}, "maintenance": False}
    if not ACCESS_FILE.exists():
        return defaults
    try:
        with ACCESS_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        defaults.update(data if isinstance(data, dict) else {})
        defaults["blocked_users"] = [int(x) for x in defaults.get("blocked_users", [])]
        defaults["banned_until"] = defaults.get("banned_until", {})
        defaults["maintenance"] = bool(defaults.get("maintenance", False))
        return defaults
    except Exception:
        logger.exception("Could not read access_settings.json")
        return defaults


def save_access_data(data):
    tmp = ACCESS_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(ACCESS_FILE)


SECTION_NAMES = {
    "purchase": "خرید سرویس / انتخاب پنل و سرور",
    "gaming": "سرور تانل گیمینگ VIP",
    "v2ray": "سرور وب‌گردی V2Ray",
    "unlimited": "سرور نامحدود VIP",
    "market": "شاپ اکانت بازی‌ها",
    "virtual": "خدمات مجازی",
    "test": "اکانت تست",
    "tariffs": "تعرفه سرویس‌ها",
    "renew": "تمدید سرویس",
}


def load_section_settings():
    if not SECTION_FILE.exists():
        return {}
    try:
        with SECTION_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.exception("Could not read section settings")
        return {}


def save_section_settings(data):
    tmp = SECTION_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(SECTION_FILE)


def section_is_closed(key):
    return key in load_section_settings()


async def section_gate(message, key):
    """Tell the customer the admin's custom message if a section is closed."""
    setting = load_section_settings().get(key)
    if not setting:
        return False
    await message.reply_text(setting.get("message", "این قسمت موقتاً در دسترس نیست."))
    return True


async def section_close_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("⛔ این دستور فقط برای ادمین است.")
        return
    if len(context.args) < 2:
        keys = "\n".join(f"{key} — {name}" for key, name in SECTION_NAMES.items())
        await update.effective_message.reply_text(
            "فرمت:\n/section_close purchase این قسمت در حال آپدیت است\n\n"
            "بخش‌های قابل بستن (کلید انگلیسی):\n" + keys
        )
        return
    key = context.args[0].lower()
    if key not in SECTION_NAMES:
        await update.effective_message.reply_text("کلید بخش نامعتبر است. برای دیدن فهرست، /section_close را بفرستید.")
        return
    message = " ".join(context.args[1:]).strip()
    data = load_section_settings()
    data[key] = {"message": message}
    save_section_settings(data)
    await update.effective_message.reply_text(f"✅ بخش «{SECTION_NAMES[key]}» بسته شد.\nپیام مشتری: {message}\nبرای بازکردن: /section_open {key}")


async def section_open_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("⛔ این دستور فقط برای ادمین است.")
        return
    if not context.args:
        await update.effective_message.reply_text("فرمت: /section_open purchase")
        return
    key = context.args[0].lower()
    if key not in SECTION_NAMES:
        await update.effective_message.reply_text("کلید بخش نامعتبر است.")
        return
    data = load_section_settings()
    data.pop(key, None)
    save_section_settings(data)
    await update.effective_message.reply_text(f"✅ بخش «{SECTION_NAMES[key]}» دوباره باز شد.")


async def sections_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("⛔ این دستور فقط برای ادمین است.")
        return
    data = load_section_settings()
    lines = ["وضعیت بخش‌های ربات:"]
    for key, name in SECTION_NAMES.items():
        status = f"🔴 بسته — {data[key].get('message', '')}" if key in data else "🟢 باز"
        lines.append(f"{key} | {name}: {status}")
    await update.effective_message.reply_text("\n".join(lines))


async def access_gate(update, context):
    """Return True when an ordinary user's request should be stopped."""
    user = update.effective_user
    message = update.effective_message
    if not user or not message or is_admin(user.id):
        return False
    data = load_access_data()
    if user.id in data.get("blocked_users", []):
        await message.reply_text("⛔ دسترسی شما به این ربات مسدود شده است.")
        return True
    until = data.get("banned_until", {}).get(str(user.id))
    if until:
        try:
            expiry = datetime.fromisoformat(until)
            if datetime.now() < expiry:
                await message.reply_text(f"⛔ دسترسی شما تا {expiry.strftime('%Y-%m-%d %H:%M')} محدود شده است.")
                return True
            data["banned_until"].pop(str(user.id), None)
            save_access_data(data)
        except Exception:
            data["banned_until"].pop(str(user.id), None)
            save_access_data(data)
    if data.get("maintenance"):
        await message.reply_text("🛠 ربات موقتاً در حال بروزرسانی است. لطفاً بعداً دوباره تلاش کنید.")
        return True
    return False



async def support_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Let an admin reply to a support/dealership request without typing /senduser."""
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("این گزینه فقط برای ادمین است.", show_alert=True)
        return
    try:
        target_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer("شناسه مشتری نامعتبر است.", show_alert=True)
        return
    context.user_data["support_reply_target"] = target_id
    context.user_data.pop("config_order_id", None)
    context.user_data.pop("pending_config_delivery", None)
    await query.answer()
    await query.message.reply_text(
        f"✍️ حالت پاسخ مستقیم فعال شد.\nمشتری: {target_id}\n\n"
        "حالا فقط متن پاسخ را در همین چت بفرست تا مستقیم برای مشتری ارسال شود.\n"
        "برای لغو، کلمه «لغو» را بفرست."
    )


async def deliver_support_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Consume the next admin text as a direct customer reply."""
    target_id = context.user_data.get("support_reply_target")
    message = update.effective_message
    if not target_id or not message or not update.effective_user or not is_admin(update.effective_user.id):
        return False
    body = (message.text or "").strip()
    if body in ("لغو", "انصراف"):
        context.user_data.pop("support_reply_target", None)
        await message.reply_text("پاسخ مستقیم لغو شد.")
        return True
    if not body:
        await message.reply_text("لطفاً متن پاسخ را به‌صورت پیام متنی بفرستید.")
        return True
    try:
        await context.bot.send_message(chat_id=int(target_id), text=body)
    except TelegramError:
        logger.exception("Could not send direct support reply to %s", target_id)
        await message.reply_text("❌ پیام ارسال نشد. ممکن است مشتری ربات را شروع نکرده یا مسدود کرده باشد.")
        return True
    context.user_data.pop("support_reply_target", None)
    await message.reply_text(f"✅ پاسخ مستقیماً برای مشتری {target_id} ارسال شد.")
    return True


async def senduser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a private message to one user by numeric Telegram chat ID."""
    message = update.effective_message
    actor = update.effective_user
    if not message or not actor:
        return
    if not is_admin(actor.id):
        await message.reply_text("⛔ این دستور فقط برای ادمین است.")
        return
    if len(context.args) < 2 or not context.args[0].isdigit():
        await message.reply_text(
            "فرمت صحیح:\n/senduser آیدی_عددی_کاربر متن پیام\n\n"
            "مثال:\n/senduser 123456789 سلام، سفارش شما بررسی شد."
        )
        return
    target_id = int(context.args[0])
    text = " ".join(context.args[1:]).strip()
    if target_id <= 0 or not text:
        await message.reply_text("آیدی کاربر یا متن پیام معتبر نیست.")
        return
    try:
        await context.bot.send_message(chat_id=target_id, text=text)
    except Forbidden:
        await message.reply_text(
            "❌ پیام ارسال نشد. احتمالاً کاربر ربات را شروع نکرده یا ربات را مسدود کرده است. "
            "از کاربر بخواه وارد ربات شود و /start بزند."
        )
    except BadRequest as exc:
        logger.warning("senduser BadRequest target=%s: %s", target_id, exc)
        await message.reply_text(
            "❌ تلگرام پیام را نپذیرفت. آیدی عددی را بررسی کن و مطمئن شو کاربر قبلاً ربات را شروع کرده است."
        )
    except TelegramError as exc:
        logger.exception("senduser TelegramError target=%s", target_id)
        await message.reply_text(f"❌ خطای تلگرام هنگام ارسال پیام: {exc}")
    except Exception:
        logger.exception("Unexpected senduser failure target=%s", target_id)
        await message.reply_text("❌ خطای غیرمنتظره رخ داد. گزارش خطا در کنسول ربات ثبت شد.")
    else:
        await message.reply_text(f"✅ پیام با موفقیت برای کاربر {target_id} ارسال شد.")


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("این دستور فقط برای ادمین است.")
        return
    message_text = " ".join(context.args).strip()
    if not message_text:
        await update.effective_message.reply_text("فرمت: /broadcast متن پیام")
        return
    user_ids = sorted(load_users())
    if not user_ids:
        await update.effective_message.reply_text("هنوز کاربری برای ارسال پیام ثبت نشده است.")
        return
    success = failed = 0
    for user_id in user_ids:
        if user_id in load_access_data().get("blocked_users", []):
            continue
        try:
            await context.bot.send_message(chat_id=user_id, text=message_text)
            success += 1
        except Exception:
            failed += 1
            logger.warning("Broadcast failed for user_id=%s", user_id)
        await asyncio.sleep(0.04)
    await update.effective_message.reply_text(f"📣 ارسال همگانی تمام شد.\n✅ موفق: {success}\n❌ ناموفق: {failed}")


async def block_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("این دستور فقط برای ادمین است.")
        return
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.effective_message.reply_text("فرمت: /block آیدی_عددی_کاربر")
        return
    target = int(context.args[0])
    if target == ADMIN_ID or is_admin(target):
        await update.effective_message.reply_text("نمی‌توان ادمین را مسدود کرد.")
        return
    data = load_access_data()
    if target not in data["blocked_users"]:
        data["blocked_users"].append(target)
    save_access_data(data)
    await update.effective_message.reply_text(f"⛔ کاربر {target} مسدود شد.")


async def unblock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("این دستور فقط برای ادمین است.")
        return
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.effective_message.reply_text("فرمت: /unblock آیدی_عددی_کاربر")
        return
    target = int(context.args[0])
    data = load_access_data()
    data["blocked_users"] = [x for x in data["blocked_users"] if x != target]
    save_access_data(data)
    await update.effective_message.reply_text(f"✅ مسدودیت کاربر {target} برداشته شد.")


async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("این دستور فقط برای ادمین است.")
        return
    if len(context.args) != 2 or not context.args[0].isdigit() or not context.args[1].isdigit():
        await update.effective_message.reply_text("فرمت: /ban آیدی_کاربر مدت_دقیقه\nمثال: /ban 123456789 60")
        return
    target, minutes = int(context.args[0]), int(context.args[1])
    if target == ADMIN_ID or is_admin(target) or minutes < 1 or minutes > 525600:
        await update.effective_message.reply_text("آیدی نامعتبر است یا مدت باید بین 1 تا 525600 دقیقه باشد.")
        return
    data = load_access_data()
    data["banned_until"][str(target)] = datetime.now().isoformat(timespec="minutes") 
    from datetime import timedelta
    data["banned_until"][str(target)] = (datetime.now() + timedelta(minutes=minutes)).isoformat(timespec="minutes")
    save_access_data(data)
    await update.effective_message.reply_text(f"⏳ کاربر {target} به مدت {minutes} دقیقه محدود شد.")


async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("این دستور فقط برای ادمین است.")
        return
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.effective_message.reply_text("فرمت: /unban آیدی_عددی_کاربر")
        return
    data = load_access_data()
    data["banned_until"].pop(str(int(context.args[0])), None)
    save_access_data(data)
    await update.effective_message.reply_text("✅ محدودیت موقت کاربر برداشته شد.")


async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("این دستور فقط برای ادمین است.")
        return
    data = load_access_data()
    data["maintenance"] = True
    save_access_data(data)
    await update.effective_message.reply_text("🛠 حالت بروزرسانی فعال شد؛ کاربران عادی پیام اطلاع‌رسانی می‌بینند.")


async def online_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("این دستور فقط برای ادمین است.")
        return
    data = load_access_data()
    data["maintenance"] = False
    save_access_data(data)
    await update.effective_message.reply_text("✅ ربات به حالت عادی برگشت.")


def user_label(user):
    name = " ".join(x for x in [user.first_name, user.last_name] if x) or "بدون نام"
    username = f"@{user.username}" if user.username else "ندارد"
    return f"{name}\nیوزرنیم: {username}\nآیدی عددی: {user.id}"


def order_text(order):
    discount_line = ""
    if order.get("discount_percent", 0):
        discount_line = (
            f"\n🏷 تخفیف: {order['discount_percent']}٪"
            f"\n💵 مبلغ قبل از تخفیف: {money(order.get('original_amount', order['amount']))}"
            f"\n💸 مبلغ تخفیف: {money(order.get('discount_amount', 0))}"
        )
    return (
        f"🧾 سفارش شماره #{order['id']}\n"
        f"👤 مشتری: {order['customer_name']}\n"
        f"یوزرنیم: {order['username']}\n"
        f"آیدی عددی: {order['user_id']}\n"
        f"🌐 سرویس: {order['panel']}\n"
        f"🏷 نام انتخابی مشتری: {order.get('service_name', 'ثبت نشده')}\n"
        f"📦 محصول: {order['product']}\n"
        f"🔢 تعداد: {order['quantity']}\n"
        f"💵 مبلغ: {money(order['amount'])}{discount_line}\n"
        f"📌 وضعیت: {order['status']}\n"
        f"🕒 زمان ثبت: {order['created_at']}"
    )


def admin_order_actions(order_id):
    """Two clear actions for an admin order card."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("📤 ارسال سرور", callback_data=f"order_action:send:{order_id}"), InlineKeyboardButton("❌ رد خرید", callback_data=f"order_action:reject:{order_id}")]])


async def cancel_active_order(user_id, context):
    """Cancel the user's current unpaid order safely, if one exists."""
    order_id = context.user_data.get("active_receipt_order")
    if order_id is not None:
        db = load_db()
        order = db.get("orders", {}).get(str(order_id))
        if order and int(order.get("user_id", -1)) == int(user_id) and order.get("status") in ("در انتظار رسید", "رسید ارسال‌شده"):
            order["status"] = "لغو‌شده توسط مشتری"
            order["cancelled_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_db(db)
    context.user_data.pop("active_receipt_order", None)


async def global_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # Returning to the main menu cancels an unpaid order so it cannot remain active accidentally.
    await cancel_active_order(query.from_user.id, context)
    context.user_data.pop("quantity_waiting", None)
    context.user_data.pop("pending_order", None)
    context.user_data.pop("market_flow", None)
    context.user_data.pop("panel", None)
    context.user_data.pop("product", None)
    context.user_data.pop("unit_price", None)
    await query.message.reply_text("به منوی اصلی برگشتید.", reply_markup=MAIN_MARKUP)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        remember_user(update.effective_user.id)
    if await access_gate(update, context):
        return
    context.user_data.clear()
    await update.message.reply_text(
        "سلام، خوش آمدید 🌟\nاز منوی زیر گزینه موردنظرتان را انتخاب کنید.",
        reply_markup=MAIN_MARKUP,
    )


async def show_tariffs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    percent = load_user_discount_percent(update.effective_user.id)
    lines = ["💰 تعرفه سرویس‌ها\n"]
    if percent:
        lines.append(f"🏷 تخفیف فعال: {percent}٪\n")
    for panel, options in PRODUCTS.items():
        lines.append(f"\n{panel}")
        for product, price in options:
            final_price = discounted_price(price, percent)
            if percent:
                lines.append(f"• {product}: قیمت عادی {money(price)} | با تخفیف {money(final_price)}")
            else:
                lines.append(f"• {product}: {money(price)}")
    await update.message.reply_text("\n".join(lines), reply_markup=MAIN_MARKUP)


def server_selection_markup():
    keyboard = [[InlineKeyboardButton(name, callback_data=f"panel:{i}")]
                for i, name in enumerate(PRODUCTS)]
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back")])
    return InlineKeyboardMarkup(keyboard)


async def begin_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id) and await section_gate(update.effective_message, "purchase"):
        return
    await update.effective_message.reply_text(
        "🌍 لطفاً سرور موردنظر را انتخاب کنید:",
        reply_markup=server_selection_markup(),
    )


async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    # Check the section switch before answering/opening a panel. Use a Telegram
    # alert so the customer immediately sees the admin's custom maintenance text.
    async def deny_if_closed(key):
        if is_admin(query.from_user.id):
            return False
        setting = load_section_settings().get(key)
        if not setting:
            return False
        message = str(setting.get("message") or "این قسمت موقتاً در دسترس نیست.")
        await query.answer(text=message[:190], show_alert=True)
        return True

    # Handle section gates before the generic callback acknowledgement.
    if data.startswith("panel:"):
        if await deny_if_closed("purchase"):
            return
        panels = list(PRODUCTS)
        try:
            idx = int(data.split(":", 1)[1])
            selected_panel = panels[idx] if 0 <= idx < len(panels) else None
        except (ValueError, IndexError):
            selected_panel = None
        if selected_panel is None:
            await query.answer("گزینه نامعتبر است.", show_alert=True)
            return
        section_key = PANEL_SECTION_KEYS.get(selected_panel)
        if section_key and await deny_if_closed(section_key):
            return

    elif data.startswith("product:"):
        panel = context.user_data.get("panel")
        section_key = PANEL_SECTION_KEYS.get(panel)
        if section_key and await deny_if_closed(section_key):
            return

    await query.answer()

    if data == "back":
        await query.message.reply_text("به منوی اصلی برگشتید.", reply_markup=MAIN_MARKUP)
        return

    if data.startswith("panel:"):
        panels = list(PRODUCTS)
        idx = int(data.split(":")[1])
        if idx < 0 or idx >= len(panels):
            await query.message.reply_text("گزینه نامعتبر است.")
            return
        selected_panel = panels[idx]
        context.user_data["panel"] = selected_panel
        percent = load_user_discount_percent(query.from_user.id)
        keyboard = [
            [InlineKeyboardButton(
                f"{name} — {money(discounted_price(price, percent))}" + (f" (تخفیف {percent}٪)" if percent else ""),
                callback_data=f"product:{i}"
            )]
            for i, (name, price) in enumerate(PRODUCTS[panels[idx]])
        ]
        keyboard.append([InlineKeyboardButton("🔙 انتخاب پنل دیگر", callback_data="back_to_panels")])
        await query.message.reply_text(
            f"📦 محصول مورد نظر را انتخاب کنید:\n\n{panels[idx]}",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if data == "back_to_panels":
        await query.message.reply_text(
            "🌍 لطفاً سرور موردنظر را انتخاب کنید:",
            reply_markup=server_selection_markup(),
        )
        return

    if data.startswith("product:"):
        panel = context.user_data.get("panel")
        if panel not in PRODUCTS:
            await query.message.reply_text("از منوی اصلی دوباره خرید را شروع کنید.")
            return
        idx = int(data.split(":")[1])
        options = PRODUCTS[panel]
        if idx < 0 or idx >= len(options):
            await query.message.reply_text("گزینه نامعتبر است.")
            return
        product, unit_price = options[idx]
        context.user_data["product"] = product
        context.user_data["unit_price"] = unit_price
        context.user_data["quantity_waiting"] = True
        if product == "هر گیگابایت":
            prompt = "⚠️ توجه: حداقل خرید سرویس ۱۰ گیگابایت و حداکثر ۲۰۰ گیگابایت است.\n\nحجم موردنظر را با عدد انگلیسی بین 10 تا 200 بفرستید. مثال: 10"
        elif panel == "♾️ سرور نامحدود VIP":
            prompt = f"مدت انتخابی: {product}\nبرای ادامه و ثبت همین پلن، عدد 1 را بفرستید."
        else:
            prompt = "لطفاً تعداد موردنظر را وارد کنید (فعلاً از 1 تا 10)."
        await query.message.reply_text(prompt)
        return


VIRTUAL_PRODUCTS = [
    ("تلگرام پرمیوم — ۱ ماه", 1200000),
    ("تلگرام پرمیوم — ۳ ماه", 3900000),
    ("تلگرام پرمیوم — ۶ ماه", 8000000),
]


async def virtual_service_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id) and await section_gate(query.message, "virtual"):
        return
    try:
        index = int(query.data.split(":", 1)[1])
        if index < 0 or index >= len(VIRTUAL_PRODUCTS):
            raise IndexError("virtual product index out of range")
        product, amount = VIRTUAL_PRODUCTS[index]
    except (ValueError, IndexError):
        await query.message.reply_text("گزینه معتبر نیست؛ دوباره از منو انتخاب کنید.")
        return
    user = query.from_user
    db = load_db()
    order_id = db["next_id"]
    db["next_id"] += 1
    order_number = 1 + max((int(o.get("order_number", 0)) for o in db["orders"].values()), default=0)
    order = {
        "id": order_id, "order_number": order_number, "user_id": user.id,
        "customer_name": " ".join(x for x in [user.first_name, user.last_name] if x) or "بدون نام",
        "username": f"@{user.username}" if user.username else "ندارد",
        "panel": "💎 خدمات مجازی", "product": product, "quantity": 1,
        "amount": amount, "original_amount": amount, "discount_percent": 0,
        "discount_amount": 0, "status": "در انتظار رسید", "receipt_file_id": None,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "reviewed_by": None, "config_sent": False,
    }
    db["orders"][str(order_id)] = order
    save_db(db)
    context.user_data["active_receipt_order"] = order_id
    await query.message.reply_text(
        f"🧾 خلاصه سفارش خدمات مجازی\n\n💎 محصول: {product}\n💵 مبلغ قابل پرداخت: {money(amount)}\n\n"
        "💳 اطلاعات پرداخت:\n"
        "شماره کارت: 5022291620713105\n"
        "به نام: محمد امین یوسفی\n\n"
        "پس از پرداخت، عکس رسید را همین‌جا ارسال کنید تا برای ادمین ارسال شود.\n\n"
        "اگر منصرف شدید، دکمه «❌ لغو خرید» را بزنید.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ لغو خرید", callback_data=f"cancel_active_order:{order_id}")],
            [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="global_back")],
        ]),
    )


async def handle_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("quantity_waiting"):
        return False
    raw = (update.message.text or "").strip()
    # Accept Persian/Arabic numerals as well as English digits.
    raw = raw.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    try:
        quantity = int(raw)
    except ValueError:
        await update.message.reply_text("لطفاً فقط عدد صحیح انگلیسی بفرستید.")
        return True
    panel = context.user_data.get("panel")
    product = context.user_data.get("product")
    unit_price = context.user_data.get("unit_price")
    if panel not in PRODUCTS or not product or not isinstance(unit_price, int):
        context.user_data.pop("quantity_waiting", None)
        await update.message.reply_text("اطلاعات خرید پیدا نشد؛ دوباره از منو شروع کنید.")
        return True

    if product == "هر گیگابایت":
        if quantity < 10 or quantity > 200:
            await update.message.reply_text(
                "❌ حجم انتخابی نامعتبر است.\n\n"
                "⚠️ حداقل خرید ۱۰ گیگابایت و حداکثر خرید ۲۰۰ گیگابایت است.\n"
                "لطفاً عددی بین 10 تا 200 وارد کنید."
            )
            return True
    elif quantity < 1 or quantity > 10:
        await update.message.reply_text("تعداد باید بین 1 تا 10 باشد.")
        return True

    context.user_data["quantity_waiting"] = False
    original_amount = quantity * unit_price
    discount_percent = load_user_discount_percent(update.effective_user.id)
    amount = discounted_price(original_amount, discount_percent)
    discount_amount = original_amount - amount
    context.user_data["pending_order"] = {
        "panel": panel,
        "product": product,
        "quantity": quantity,
        "service_name": panel or "سرویس",
        "amount": amount,
        "original_amount": original_amount,
        "discount_percent": discount_percent,
        "discount_amount": discount_amount,
    }
    context.user_data["service_name_waiting"] = True
    await update.message.reply_text(
        "🏷 برای سرویس خود یک نام انتخاب کنید و بفرستید.\n\n"
        "مثال: سرور گیمینگ شماره ۵۰ یا سرور گوشی\n"
        "این نام در بخش «سرویس‌های من» نمایش داده می‌شود.",
        reply_markup=ReplyKeyboardMarkup([["❌ لغو خرید"]], resize_keyboard=True),
    )
    return True


async def wallet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    user = query.from_user
    if data.startswith("wallet:review:"):
        if not is_admin(user.id):
            await query.answer("فقط ادمین اجازه بررسی درخواست را دارد.", show_alert=True); return
        await query.answer()
        _, _, decision, request_id = data.split(":", 3)
        wallet = load_wallet(); request = wallet.get("requests", {}).get(request_id)
        if not request:
            await query.message.reply_text("درخواست شارژ پیدا نشد."); return
        if request.get("status") != "pending":
            await query.message.reply_text("این درخواست قبلاً بررسی شده است."); return
        uid = str(request["user_id"]); amount = int(request["amount"])
        if not request.get("receipt_file_id"):
            await query.message.reply_text("❌ برای این درخواست رسید پرداخت ثبت نشده؛ شارژ انجام نشد.")
            return
        if decision == "approve":
            wallet["balances"][uid] = wallet_balance(wallet, uid) + amount
            request["status"] = "approved"
            wallet.setdefault("transactions", []).append({"user_id": int(uid), "type": "topup", "amount": amount, "request_id": request_id, "by": user.id, "at": datetime.now().isoformat(timespec="seconds")})
            save_wallet(wallet)
            await context.bot.send_message(chat_id=int(uid), text=f"✅ درخواست شارژ تأیید شد.\n💰 مبلغ: {money(amount)}\n💳 اعتبار فعلی: {money(wallet_balance(wallet, uid))}")
            await query.message.reply_text(f"✅ شارژ درخواست #{request_id} تأیید شد.")
        elif decision == "reject":
            request["status"] = "rejected"; request["reviewed_by"] = user.id; save_wallet(wallet)
            await context.bot.send_message(chat_id=int(uid), text=f"❌ درخواست شارژ {money(amount)} رد شد. برای پیگیری با پشتیبانی تماس بگیرید.")
            await query.message.reply_text(f"درخواست شارژ #{request_id} رد شد.")
        try: await query.edit_message_reply_markup(reply_markup=None)
        except TelegramError: pass
        return


async def wallet_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("این دستور فقط برای ادمین است."); return
    args = context.args
    if len(args) < 2 or not args[0].isdigit() or not normalize_digits(args[1]).isdigit():
        await update.effective_message.reply_text("فرمت: /wallet_add آیدی_مشتری مبلغ_تومان [توضیح]\nمثال: /wallet_add 123456789 50000 هدیه"); return
    uid, amount = int(args[0]), int(normalize_digits(args[1]))
    if amount <= 0:
        await update.effective_message.reply_text("مبلغ باید بیشتر از صفر باشد."); return
    wallet = load_wallet(); wallet["balances"][str(uid)] = wallet_balance(wallet, uid) + amount
    wallet.setdefault("transactions", []).append({"user_id": uid, "type": "admin_add", "amount": amount, "by": update.effective_user.id, "note": " ".join(args[2:])[:200], "at": datetime.now().isoformat(timespec="seconds")}); save_wallet(wallet)
    await update.effective_message.reply_text(f"✅ اعتبار کاربر {uid} به اندازه {money(amount)} افزایش یافت.\n💳 اعتبار جدید: {money(wallet_balance(wallet, uid))}")
    try: await context.bot.send_message(chat_id=uid, text=f"🎁 مدیریت برای شما اعتبار شارژ کرد.\n➕ مبلغ: {money(amount)}\n💳 اعتبار فعلی: {money(wallet_balance(wallet, uid))}")
    except TelegramError: await update.effective_message.reply_text("اعتبار ثبت شد؛ اما اطلاع‌رسانی به مشتری انجام نشد.")


async def order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel_order":
        context.user_data.pop("pending_order", None)
        context.user_data.pop("service_name_waiting", None)
        await query.message.reply_text("سفارش لغو شد.", reply_markup=MAIN_MARKUP)
        return
    if query.data != "confirm_order":
        return
    pending = context.user_data.get("pending_order")
    if not pending:
        await query.message.reply_text("سفارشی برای ثبت پیدا نشد؛ دوباره خرید کنید.")
        return

    user = query.from_user
    db = load_db()
    order_id = db["next_id"]
    db["next_id"] += 1
    order_number = 1 + max(
        (int(o.get("order_number", 0)) for o in db["orders"].values()), default=0
    )
    order = {
        "id": order_id,
        "order_number": order_number,
        "user_id": user.id,
        "customer_name": " ".join(x for x in [user.first_name, user.last_name] if x) or "بدون نام",
        "username": f"@{user.username}" if user.username else "ندارد",
        **pending,
        "status": "در انتظار رسید",
        "receipt_file_id": None,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "reviewed_by": None,
        "config_sent": False,
    }
    db["orders"][str(order_id)] = order
    save_db(db)
    context.user_data["active_receipt_order"] = order_id
    context.user_data.pop("pending_order", None)
    await query.message.reply_text(
        f"✅ شماره سفارش: #{order_number}\n"
        f"🔐 شناسه داخلی سفارش: #{order_id}\n"
        "حالا لطفاً عکس رسید پرداخت را ارسال کنید.\n\n"
        "اگر منصرف شدید، می‌توانید خرید را لغو کنید.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ لغو خرید", callback_data=f"cancel_active_order:{order_id}")],
            [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="global_back")],
        ]),
    )


async def handle_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        remember_user(update.effective_user.id)
    if await access_gate(update, context):
        return
    photo = update.message.photo
    if not photo:
        return
    order_id = context.user_data.get("active_receipt_order")
    if not order_id:
        await update.message.reply_text(
            "برای ثبت رسید، ابتدا از منوی «خرید سرویس جدید» سفارش ثبت کنید."
        )
        return
    db = load_db()
    order = db["orders"].get(str(order_id))
    if not order or order["user_id"] != update.effective_user.id:
        context.user_data.pop("active_receipt_order", None)
        await update.message.reply_text("سفارش فعال پیدا نشد؛ از منو سفارش جدید بسازید.")
        return
    if order["status"] not in ("در انتظار رسید", "رسید ارسال‌شده"):
        await update.message.reply_text("این سفارش دیگر منتظر رسید نیست.")
        return

    file_id = photo[-1].file_id
    order["receipt_file_id"] = file_id
    order["status"] = "رسید ارسال‌شده؛ در انتظار بررسی"
    save_db(db)

    admin_keyboard = admin_order_actions(order_id)
    caption = "📥 سفارش جدید — رسید کارت‌به‌کارت پیوست است\n\n" + order_text(order) + "\n\nاگر رسید معتبر است «ارسال سرور» را بزنید؛ در غیر این صورت «رد خرید»."
    try:
        for admin_id in sorted(load_admin_ids()):
            await context.bot.send_photo(
                chat_id=admin_id,
                photo=file_id,
                caption=caption,
                reply_markup=admin_keyboard,
            )
        await update.message.reply_text(
            "✅ رسید پرداخت شما با موفقیت دریافت و جهت بررسی به واحد مدیریت ارسال شد.\n\n"
            "پس از بررسی، نتیجه از طریق همین ربات به اطلاع شما خواهد رسید.\n"
            "از شکیبایی شما سپاسگزاریم.",
            reply_markup=MAIN_MARKUP,
        )
        context.user_data.pop("active_receipt_order", None)
    except Exception:
        logger.exception("Failed to notify admin")
        await update.message.reply_text(
            "رسید دریافت شد، اما ارسال آن به ادمین انجام نشد. لطفاً کمی بعد دوباره تلاش کنید."
        )


async def cancel_active_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        order_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.message.reply_text("شناسه سفارش نامعتبر است.", reply_markup=MAIN_MARKUP)
        return
    db = load_db()
    order = db.get("orders", {}).get(str(order_id))
    if not order or int(order.get("user_id", -1)) != query.from_user.id:
        await query.message.reply_text("این سفارش پیدا نشد یا متعلق به شما نیست.", reply_markup=MAIN_MARKUP)
        return
    if order.get("status") not in ("در انتظار رسید", "رسید ارسال‌شده"):
        await query.message.reply_text("این سفارش دیگر قابل لغو نیست؛ وضعیت فعلی: " + str(order.get("status")), reply_markup=MAIN_MARKUP)
        return
    order["status"] = "لغو‌شده توسط مشتری"
    order["cancelled_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_db(db)
    if context.user_data.get("active_receipt_order") == order_id:
        context.user_data.pop("active_receipt_order", None)
    await query.message.reply_text(f"✅ سفارش #{order.get('order_number', order_id)} لغو شد. دیگر رسیدی برای این سفارش ثبت نمی‌شود.", reply_markup=MAIN_MARKUP)


async def order_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("این گزینه فقط برای ادمین است.", show_alert=True); return
    try:
        _, action, order_id = query.data.split(":", 2)
        order_id = str(int(order_id))
    except (ValueError, IndexError):
        await query.answer("شناسه سفارش نامعتبر است.", show_alert=True); return
    db = load_db(); order = db.get("orders", {}).get(order_id)
    if not order:
        await query.answer("سفارش پیدا نشد.", show_alert=True); return
    if action == "send":
        if order.get("status") not in ("رسید ارسال‌شده؛ در انتظار بررسی", "رسید تأییدشده؛ در انتظار کانفیگ"):
            await query.answer("این سفارش قابل تحویل نیست یا قبلاً نهایی شده است.", show_alert=True); return
        if order.get("status") == "رسید ارسال‌شده؛ در انتظار بررسی":
            order["status"] = "رسید تأییدشده؛ در انتظار کانفیگ"
            order["reviewed_by"] = query.from_user.id
            order["payment_reviewed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_db(db)
            try: await context.bot.send_message(chat_id=int(order["user_id"]), text=f"✅ پرداخت سفارش #{order.get('order_number', order_id)} تأیید شد. سرور شما در حال آماده‌سازی است.")
            except TelegramError: logger.warning("Could not notify customer about payment approval")
        context.user_data["config_order_id"] = order_id
        context.user_data.pop("pending_config_delivery", None)
        await query.answer("سفارش انتخاب شد")
        try: await query.edit_message_reply_markup(reply_markup=None)
        except TelegramError: pass
        await query.message.reply_text(f"📤 تحویل سفارش #{order.get('order_number', order_id)}\n👤 مشتری: {order.get('customer_name', '—')}\n🆔 آیدی عددی: {order.get('user_id')}\n📦 سرویس: {order.get('panel', '—')} — {order.get('product', '—')}\n🏷 نام انتخابی مشتری: {order.get('service_name', '—')}\n💵 مبلغ: {money(order.get('amount', 0))}\n\nمتن کانفیگ یا فایل سرور را همین‌جا بفرستید؛ مستقیماً برای همین مشتری ارسال می‌شود. برای لغو بنویسید «لغو»." )
        return
    if action == "reject":
        if order.get("status") in ("کانفیگ تحویل داده شد", "رد خرید", "لغو‌شده توسط مشتری"):
            await query.answer("این سفارش قبلاً نهایی شده است.", show_alert=True); return
        order["status"] = "رد خرید"; order["rejected_by"] = query.from_user.id
        order["rejected_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        refund_note = ""
        if order.get("payment_method") == "wallet" and not order.get("wallet_refunded"):
            wallet = load_wallet(); uid = str(order.get("user_id")); amount = int(order.get("amount", 0))
            wallet.setdefault("balances", {})[uid] = wallet_balance(wallet, uid) + amount
            wallet.setdefault("transactions", []).append({"user_id": int(uid), "type": "refund", "amount": amount, "order_id": int(order_id), "by": query.from_user.id, "at": datetime.now().isoformat(timespec="seconds")})
            save_wallet(wallet); order["wallet_refunded"] = True
            refund_note = f"\nمبلغ {money(amount)} به کیف پول مشتری برگشت داده شد."
        save_db(db)
        try: await context.bot.send_message(chat_id=int(order["user_id"]), text=f"❌ خرید سفارش #{order.get('order_number', order_id)} توسط مدیریت رد شد.{refund_note}\nبرای پیگیری با پشتیبانی تماس بگیرید.")
        except TelegramError: logger.warning("Could not notify customer about rejected order")
        context.user_data.pop("config_order_id", None)
        await query.answer("خرید رد شد")
        try: await query.edit_message_reply_markup(reply_markup=None)
        except TelegramError: pass
        await query.message.reply_text(f"❌ سفارش #{order.get('order_number', order_id)} رد شد.{refund_note}")
        return
    await query.answer("عملیات ناشناخته است.", show_alert=True)


async def review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    if not is_admin(user.id):
        await query.answer("فقط ادمین اجازه بررسی رسید را دارد.", show_alert=True)
        return
    await query.answer()
    _, decision, order_id = query.data.split(":")
    db = load_db()
    order = db["orders"].get(order_id)
    if not order:
        await query.message.reply_text("این سفارش پیدا نشد.")
        return
    if order["status"] != "رسید ارسال‌شده؛ در انتظار بررسی":
        await query.message.reply_text(f"این سفارش قبلاً تعیین تکلیف شده است: {order['status']}")
        return

    if decision == "approve":
        order["status"] = "رسید تأییدشده؛ در انتظار کانفیگ"
        order["reviewed_by"] = user.id
        save_db(db)
        await context.bot.send_message(
            chat_id=order["user_id"],
            text=(f"✅ پرداخت سفارش شماره #{order.get('order_number', order_id)} تأیید شد.\n\n"
                  "از خرید شما سپاسگزاریم. اطلاعات سرویس پس از آماده‌سازی توسط مدیریت ارسال خواهد شد.\n\n"
                  "در صورت تمایل، می‌توانید از بخش زیر خرید دیگری را آغاز کنید."),
            reply_markup=server_selection_markup(),
        )
        context.user_data.pop("config_order_id", None)
        context.user_data.pop("pending_config_delivery", None)
        customer_username = str(order.get("username", "")).lstrip("@")
        customer_url = f"https://t.me/{customer_username}" if customer_username and customer_username != "ندارد" else f"tg://user?id={order.get('user_id')}"
        config_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✍️ ۱. ارسال مستقیم متن/فایل کانفیگ", callback_data=f"config_start:{order_id}")],
            [InlineKeyboardButton("👤 ۲. رفتن به پیوی مشتری", url=customer_url)],
        ])
        await query.message.reply_text(
            f"✅ رسید سفارش #{order.get('order_number', order_id)} تأیید شد.\n"
            f"👤 مشتری: {order.get('customer_name', '—')} | 🆔 {order.get('user_id')}\n"
            f"📦 سرویس: {order.get('panel', '—')} — {order.get('product', '—')}\n\n"
            "یکی از گزینه‌های زیر را انتخاب کن:",
            reply_markup=config_keyboard,
        )
    elif decision == "reject":
        order["status"] = "رسید ردشده"
        order["reviewed_by"] = user.id
        save_db(db)
        try:
            await context.bot.send_message(
                chat_id=order["user_id"],
                text=f"❌ رسید پرداخت سفارش #{order_id} توسط ادمین تأیید نشد.\n"
                     "لطفاً رسید را بررسی کنید یا با پشتیبانی تماس بگیرید.",
            )
        except Exception:
            logger.exception("Could not notify customer")
        await query.message.reply_text(f"رسید سفارش #{order_id} رد شد.")
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass


async def start_config_delivery_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start direct config delivery for the approved order attached to a button."""
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("این گزینه فقط برای ادمین است.", show_alert=True)
        return
    try:
        order_id = str(int(query.data.split(":", 1)[1]))
    except (ValueError, IndexError):
        await query.answer("شماره سفارش نامعتبر است.", show_alert=True)
        return
    db = load_db()
    order = db.get("orders", {}).get(order_id)
    if not order or order.get("status") != "رسید تأییدشده؛ در انتظار کانفیگ":
        await query.answer("این سفارش آماده تحویل کانفیگ نیست.", show_alert=True)
        return
    context.user_data["config_order_id"] = order_id
    context.user_data["config_delivery_step"] = "link"
    context.user_data.pop("config_delivery_link", None)
    context.user_data.pop("pending_config_delivery", None)
    context.user_data.pop("support_reply_target", None)
    await query.answer()
    await query.message.reply_text(
        f"📤 تحویل سرویس سفارش #{order.get('order_number', order_id)}\n"
        f"👤 مشتری: {order.get('customer_name', '—')} | 🆔 آیدی عددی: {order.get('user_id')}\n"
        f"📦 محصول: {order.get('panel', '—')} — {order.get('product', '—')}\n"
        f"🏷 نام انتخابی مشتری: {order.get('service_name') or 'سرویس'}\n\n"
        "مرحله ۱: لینک سرور یا متن کانفیگ را بفرست.\n"
        "مرحله ۲: عکس QR را جداگانه بفرست تا هر دو جدا برای مشتری ارسال و ذخیره شوند.\n"
        "اگر QR نداری، بعد از لینک بنویس «بدون QR». برای لغو بنویس «لغو»."
    )


async def deliver_config_content(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str):
    """Collect link/config and optional QR, then save and deliver them separately."""
    message = update.effective_message
    if not message or not update.effective_user or not is_admin(update.effective_user.id):
        return False
    order_id = context.user_data.get("config_order_id")
    if not order_id:
        return False
    step = context.user_data.get("config_delivery_step", "link")
    if kind == "text":
        body = (message.text or "").strip()
        if body in ("لغو", "انصراف", "/cancel"):
            for key in ("config_order_id", "config_delivery_step", "config_delivery_link"):
                context.user_data.pop(key, None)
            await message.reply_text("تحویل لغو شد؛ سفارش همچنان در انتظار تحویل باقی ماند.")
            return True
        if step == "qr":
            if body not in ("بدون QR", "ندارم", "skipqr", "/skipqr"):
                await message.reply_text("الان عکس QR را بفرست یا برای ادامه بدون QR بنویس «بدون QR».")
                return True
            return await _finish_config_delivery(update, context, order_id, None)
        if not body:
            await message.reply_text("لینک یا متن کانفیگ خالی است؛ دوباره بفرست.")
            return True
        context.user_data["config_delivery_link"] = body
        context.user_data["config_delivery_step"] = "qr"
        await message.reply_text("✅ لینک/متن کانفیگ دریافت شد. حالا عکس QR را جداگانه بفرست؛ اگر نداری بنویس «بدون QR».")
        return True
    if step != "qr":
        await message.reply_text("اول لینک یا متن کانفیگ را بفرست؛ بعد عکس QR را ارسال کن.")
        return True
    if not (message.photo or message.document):
        await message.reply_text("برای QR لطفاً عکس ارسال کن؛ یا بنویس «بدون QR».")
        return True
    qr_file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    return await _finish_config_delivery(update, context, order_id, qr_file_id)


async def _finish_config_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id, qr_file_id=None):
    message = update.effective_message
    db = load_db()
    order = db.get("orders", {}).get(str(order_id))
    if not order or order.get("status") != "رسید تأییدشده؛ در انتظار کانفیگ":
        for key in ("config_order_id", "config_delivery_step", "config_delivery_link"):
            context.user_data.pop(key, None)
        await message.reply_text("این سفارش دیگر آماده تحویل نیست.")
        return True
    link = (context.user_data.get("config_delivery_link") or "").strip()
    if not link:
        await message.reply_text("لینک/متن کانفیگ ثبت نشده؛ دوباره از دکمه «ارسال سرور» شروع کن.")
        return True
    customer_id = int(order["user_id"])
    service_name = str(order.get("service_name") or order.get("panel") or "سرویس").strip()[:50]
    try:
        await context.bot.send_message(chat_id=customer_id, text=f"🎉 سرویس «{service_name}» آماده است\n🧾 سفارش #{order.get('order_number', order_id)}")
        if link.startswith(("https://", "http://")):
            await context.bot.send_message(chat_id=customer_id, text=f"🔗 لینک سرویس «{service_name}»:\n{link}", disable_web_page_preview=True)
        else:
            await context.bot.send_message(chat_id=customer_id, text=f"🔗 متن کانفیگ سرویس «{service_name}»:\n{link}")
        if qr_file_id:
            await context.bot.send_photo(chat_id=customer_id, photo=qr_file_id, caption=f"📷 QR سرویس «{service_name}» — جدا از لینک")
        await context.bot.send_message(chat_id=customer_id, text="✅ سرویس در بخش «سرویس‌های من» ذخیره شد. برای تمدید، همان نام سرویس را انتخاب کن.")
    except Exception:
        logger.exception("Failed to deliver service info for order %s", order_id)
        await message.reply_text("❌ ارسال برای مشتری ناموفق بود. سفارش در انتظار تحویل ماند؛ مطمئن شو مشتری ربات را Start کرده باشد.")
        return True
    order["service_name"] = service_name
    order["server_link"] = link if link.startswith(("https://", "http://")) else ""
    order["config_text"] = link
    order["server_qr_file_id"] = qr_file_id
    order["status"] = "کانفیگ تحویل داده شد"
    order["config_sent"] = True
    order["config_sent_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    order["config_sent_by"] = update.effective_user.id
    save_db(db)
    for key in ("config_order_id", "config_delivery_step", "config_delivery_link", "pending_config_delivery"):
        context.user_data.pop(key, None)
    await message.reply_text(f"✅ سرویس «{service_name}» برای مشتری با آیدی عددی {customer_id} تحویل و ذخیره شد. لینک و QR جداگانه ارسال شدند.")
    return True


async def sendconfig_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Select an approved order for manual config delivery.

    Usage: /sendconfig <order_id> [customer_numeric_id]. The customer ID is
    optional; if supplied, it is validated against the stored order.
    """
    if not update.effective_user or not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("این دستور فقط برای ادمین است.")
        return
    if len(context.args) not in (1, 2):
        await update.effective_message.reply_text(
            "فرمت دستور:\n/sendconfig شماره_سفارش [آیدی_عددی_مشتری]\n"
            "مثال: /sendconfig 1001\n"
            "پس از اجرای دستور، متن یا فایل کانفیگ را ارسال کنید."
        )
        return
    try:
        order_id = str(int(context.args[0]))
        customer_id = int(context.args[1]) if len(context.args) == 2 else None
    except ValueError:
        await update.effective_message.reply_text("شماره سفارش و آیدی مشتری باید عدد باشند.")
        return
    db = load_db()
    order = db.get("orders", {}).get(order_id)
    if not order:
        await update.effective_message.reply_text("شماره سفارش پیدا نشد.")
        return
    if order.get("status") != "رسید تأییدشده؛ در انتظار کانفیگ":
        await update.effective_message.reply_text(
            f"این سفارش آماده تحویل کانفیگ نیست. وضعیت فعلی: {order.get('status', 'نامشخص')}"
        )
        return
    stored_customer_id = order.get("user_id")
    if customer_id is not None and str(stored_customer_id) != str(customer_id):
        await update.effective_message.reply_text(
            f"آیدی مشتری با سفارش مطابقت ندارد. آیدی درست: {stored_customer_id}"
        )
        return
    context.user_data["config_order_id"] = order_id
    context.user_data["config_delivery_step"] = "link"
    context.user_data.pop("config_delivery_link", None)
    context.user_data["config_delivery_step"] = "link"
    context.user_data.pop("config_delivery_link", None)
    context.user_data.pop("pending_config_delivery", None)
    context.user_data.pop("support_reply_target", None)
    customer_username = str(order.get("username", "")).lstrip("@")
    customer_url = f"https://t.me/{customer_username}" if customer_username and customer_username != "ندارد" else f"tg://user?id={stored_customer_id}"
    await update.effective_message.reply_text(
        f"✍️ ارسال مستقیم کانفیگ سفارش #{order.get('order_number', order_id)} فعال شد.\n"
        f"👤 مشتری: {order.get('customer_name', '—')} | 🆔 {stored_customer_id}\n"
        f"📦 سرویس: {order.get('panel', '—')} — {order.get('product', '—')}\n\n"
        "مرحله ۱: لینک/متن کانفیگ را بفرست. مرحله ۲: عکس QR را جداگانه بفرست یا بنویس «بدون QR». برای لغو بنویس «لغو».",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👤 رفتن به پیوی مشتری", url=customer_url)]])
    )


async def handle_config_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deliver admin's next text directly to the selected approved order."""
    return await deliver_config_content(update, context, "text")


async def handle_config_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deliver admin's next document/video directly to the selected approved order."""
    return await deliver_config_content(update, context, "media")


async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    db = load_db()
    mine = [
        o for o in db["orders"].values()
        if o.get("user_id") == update.effective_user.id
        and o.get("status") == "کانفیگ تحویل داده شد"
        and o.get("config_sent")
    ]
    mine.sort(key=lambda o: o.get("id", 0), reverse=True)
    if not mine:
        await update.effective_message.reply_text(
            "📱 هنوز سرویس تحویل‌داده‌شده‌ای ندارید.\nبعد از تحویل کانفیگ، سرویس در همین بخش نمایش داده می‌شود.",
            reply_markup=MAIN_MARKUP,
        )
        return
    page_size = 10
    total_pages = max(1, (len(mine) + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    selected = mine[page * page_size:(page + 1) * page_size]
    lines = [f"📱 سرویس‌های شما ({len(mine)} سرویس)\nصفحه {page + 1} از {total_pages}", "برای مشاهده یا تمدید، سرویس را انتخاب کنید:"]
    keyboard = []
    for order in selected:
        code = order.get("id", "—")
        customer_code = order.get("order_number", code)
        name = order.get("service_name") or order.get("panel", "سرویس")
        lines.append(f"\n• {name} — سفارش #{customer_code}\n  {order.get('product', '—')} | حجم/تعداد: {order.get('quantity', '—')}")
        keyboard.append([InlineKeyboardButton(f"📦 {name} | #{customer_code}", callback_data=f"myservice:{code}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ صفحه قبل", callback_data=f"myservices_page:{page-1}"))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton("صفحه بعد ➡️", callback_data=f"myservices_page:{page+1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🔙 منوی اصلی", callback_data="global_back")])
    await update.effective_message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))


async def my_service_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = load_db()
    try:
        order_id = str(int(query.data.split(":", 1)[1]))
    except (ValueError, IndexError):
        await query.message.reply_text("شناسه سرویس معتبر نیست.")
        return
    order = db.get("orders", {}).get(order_id)
    if not order or order.get("user_id") != query.from_user.id or order.get("status") != "کانفیگ تحویل داده شد" or not order.get("config_sent"):
        await query.message.reply_text("این سرویس پیدا نشد یا متعلق به شما نیست.")
        return
    code = order.get("order_number", order_id)
    name = order.get("service_name") or order.get("panel", "سرویس")
    text = (
        f"📱 مشخصات سرویس شما\n\n🏷 نام سرویس: {name}\n"
        f"📦 نوع سرویس: {order.get('panel', '—')}\n🔹 محصول: {order.get('product', '—')}\n"
        f"🧾 شماره سفارش: #{code}\n📊 حجم/تعداد: {order.get('quantity', '—')}\n"
        f"💵 مبلغ خرید: {money(order.get('amount', 0))}\n📌 وضعیت: تحویل داده شده"
    )
    await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("♻️ تمدید همین سرویس", callback_data=f"renew_service:{order_id}")],
        [InlineKeyboardButton("📋 دریافت دوباره اطلاعات سرویس", callback_data=f"service_info:{order_id}")],
        [InlineKeyboardButton("🔙 سرویس‌های من", callback_data="myservices_page:0")],
    ]))


async def service_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        order_id = str(int(query.data.split(":", 1)[1]))
    except (ValueError, IndexError):
        await query.message.reply_text("شناسه سرویس معتبر نیست.")
        return
    order = load_db().get("orders", {}).get(order_id)
    if not order or order.get("user_id") != query.from_user.id or not order.get("config_sent"):
        await query.message.reply_text("این سرویس پیدا نشد یا متعلق به شما نیست.")
        return
    name = order.get("service_name") or order.get("panel") or "سرویس"
    link = order.get("server_link") or ""
    config_text = order.get("config_text") or ""
    await query.message.reply_text(
        f"📱 اطلاعات ذخیره‌شده سرویس\n🏷 نام: {name}\n🧾 سفارش: #{order.get('order_number', order_id)}\n"
        f"📦 نوع: {order.get('panel', '—')}\n🔹 محصول: {order.get('product', '—')}\n"
        f"🔗 لینک: {'ذخیره شده' if link else 'متن کانفیگ ذخیره شده' if config_text else 'ثبت نشده'}\n📷 QR: {'ذخیره شده' if order.get('server_qr_file_id') else 'ثبت نشده'}"
    )
    if link:
        await context.bot.send_message(chat_id=query.from_user.id, text=f"🔗 لینک سرویس «{name}»:\n{link}", disable_web_page_preview=True)
    elif config_text:
        await context.bot.send_message(chat_id=query.from_user.id, text=f"🔗 متن کانفیگ سرویس «{name}»:\n{config_text}")
    if order.get("server_qr_file_id"):
        await context.bot.send_photo(chat_id=query.from_user.id, photo=order["server_qr_file_id"], caption=f"📷 QR سرویس «{name}»")


async def service_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        order_id = str(int(query.data.split(":", 1)[1]))
    except (ValueError, IndexError):
        await query.message.reply_text("شناسه سرویس معتبر نیست.")
        return
    order = load_db().get("orders", {}).get(order_id)
    if not order or order.get("user_id") != query.from_user.id or not order.get("config_sent"):
        await query.message.reply_text("این سرویس پیدا نشد یا متعلق به شما نیست.")
        return
    name = order.get("service_name") or order.get("panel") or "سرویس"
    link = order.get("server_link") or ""
    config_text = order.get("config_text") or ""
    await query.message.reply_text(
        f"📱 اطلاعات ذخیره‌شده سرویس\n🏷 نام: {name}\n🧾 سفارش: #{order.get('order_number', order_id)}\n"
        f"📦 نوع: {order.get('panel', '—')}\n🔹 محصول: {order.get('product', '—')}\n"
        f"🔗 لینک: {'ذخیره شده' if link else 'متن کانفیگ ذخیره شده' if config_text else 'ثبت نشده'}\n📷 QR: {'ذخیره شده' if order.get('server_qr_file_id') else 'ثبت نشده'}"
    )
    if link:
        await context.bot.send_message(chat_id=query.from_user.id, text=f"🔗 لینک سرویس «{name}»:\n{link}", disable_web_page_preview=True)
    elif config_text:
        await context.bot.send_message(chat_id=query.from_user.id, text=f"🔗 متن کانفیگ سرویس «{name}»:\n{config_text}")
    if order.get("server_qr_file_id"):
        await context.bot.send_photo(chat_id=query.from_user.id, photo=order["server_qr_file_id"], caption=f"📷 QR سرویس «{name}»")


async def my_services_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        page = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        page = 0
    # Reuse callback message as the destination while keeping the existing message intact.
    db = load_db()
    mine = [o for o in db["orders"].values() if o.get("user_id") == query.from_user.id and o.get("status") == "کانفیگ تحویل داده شد" and o.get("config_sent")]
    mine.sort(key=lambda o: o.get("id", 0), reverse=True)
    page_size = 10
    total_pages = max(1, (len(mine) + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    selected = mine[page * page_size:(page + 1) * page_size]
    lines = [f"📱 سرویس‌های شما ({len(mine)} سرویس)\nصفحه {page + 1} از {total_pages}", "برای مشاهده یا تمدید، سرویس را انتخاب کنید:"]
    keyboard = []
    for order in selected:
        code = order.get("id", "—")
        num = order.get("order_number", code)
        name = order.get("service_name") or order.get("panel", "سرویس")
        lines.append(f"\n• {name} — سفارش #{num}\n  {order.get('product', '—')} | حجم/تعداد: {order.get('quantity', '—')}")
        keyboard.append([InlineKeyboardButton(f"📦 {name} | #{num}", callback_data=f"myservice:{code}")])
    nav=[]
    if page > 0: nav.append(InlineKeyboardButton("⬅️ صفحه قبل", callback_data=f"myservices_page:{page-1}"))
    if page + 1 < total_pages: nav.append(InlineKeyboardButton("صفحه بعد ➡️", callback_data=f"myservices_page:{page+1}"))
    if nav: keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🔙 منوی اصلی", callback_data="global_back")])
    await query.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))


async def renew_service_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        source_id = str(int(query.data.split(":", 1)[1]))
    except (ValueError, IndexError):
        await query.message.reply_text("کد سرویس معتبر نیست.")
        return

    db = load_db()
    source = db["orders"].get(source_id)
    if (not source or source.get("user_id") != query.from_user.id
            or source.get("status") != "کانفیگ تحویل داده شد"
            or not source.get("config_sent")):
        await query.message.reply_text("این سرویس پیدا نشد یا هنوز تحویل داده نشده است.")
        return

    panel = source.get("panel")
    product = source.get("product")
    quantity = source.get("quantity")
    unit_price = next((price for name, price in PRODUCTS.get(panel, []) if name == product), None)
    if unit_price is None:
        await query.message.reply_text(
            "قیمت فعلی این سرویس در فهرست تعرفه‌ها پیدا نشد. لطفاً با پشتیبانی تماس بگیرید."
        )
        return

    try:
        quantity = int(quantity)
    except (ValueError, TypeError):
        await query.message.reply_text("حجم/تعداد سرویس قبلی معتبر نیست؛ با پشتیبانی تماس بگیرید.")
        return

    original_amount = quantity * unit_price
    discount_percent = load_user_discount_percent(query.from_user.id)
    amount = discounted_price(original_amount, discount_percent)
    discount_amount = original_amount - amount
    order_id = db["next_id"]
    db["next_id"] += 1
    user = query.from_user
    order_number = 1 + max(
        (int(o.get("order_number", 0)) for o in db["orders"].values()), default=0
    )
    renewal = {
        "id": order_id,
        "order_number": order_number,
        "user_id": user.id,
        "customer_name": " ".join(x for x in [user.first_name, user.last_name] if x) or "بدون نام",
        "username": f"@{user.username}" if user.username else "ندارد",
        "panel": panel,
        "product": product,
        "quantity": quantity,
        "service_name": source.get("service_name") or source.get("panel", "سرویس"),
        "amount": amount,
        "original_amount": original_amount,
        "discount_percent": discount_percent,
        "discount_amount": discount_amount,
        "status": "در انتظار رسید",
        "receipt_file_id": None,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "reviewed_by": None,
        "config_sent": False,
        "renewal_of": int(source_id),
    }
    db["orders"][str(order_id)] = renewal
    save_db(db)
    context.user_data["active_receipt_order"] = order_id
    await query.message.reply_text(
        f"♻️ سفارش تمدید ثبت شد\n\n"
        f"📦 سرویس: {panel}\n"
        f"🔹 محصول: {product}\n"
        f"🧾 شماره سفارش: #{order_number}\n"
        f"🔐 شناسه داخلی سفارش: #{order_id}\n"
        f"🔁 تمدید سرویس با کد قبلی: #{source_id}\n"
        f"📊 حجم/تعداد: {quantity}\n"
        + (f"🏷 تخفیف: {discount_percent}٪\n" if discount_percent else "")
        + f"💵 مبلغ قابل پرداخت: {money(amount)}\n\n"
        "💳 پس از پرداخت، عکس رسید را همین‌جا ارسال کنید. بعد از تأیید پرداخت، ادمین تمدید را انجام می‌دهد.",
        reply_markup=MAIN_MARKUP,
    )

async def admin_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("این دستور فقط برای ادمین است.")
        return
    db = load_db()
    orders = sorted(db["orders"].values(), key=lambda o: o["id"], reverse=True)
    if not orders:
        await update.message.reply_text("هنوز سفارشی ثبت نشده است.")
        return
    lines = ["🗂 آخرین سفارش‌ها:"]
    for order in orders[:30]:
        lines.append(f"#{order['id']} | مشتری {order['user_id']} | {order['status']} | {money(order['amount'])}")
    await update.message.reply_text("\n".join(lines))


# ================= ONE-TIME TEST ACCOUNT POOL =================
def load_test_accounts():
    """Load queued test links and the persistent one-test-per-user ledger."""
    if not TEST_FILE.exists():
        return {"next_id": 1, "available": [], "claimed_users": {}}
    try:
        with TEST_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Invalid test account database")
        data.setdefault("next_id", 1)
        data.setdefault("available", [])
        data.setdefault("claimed_users", {})
        if not isinstance(data["available"], list) or not isinstance(data["claimed_users"], dict):
            raise ValueError("Invalid test account database fields")
        return data
    except Exception as exc:
        logger.exception("Could not read test account database")
        raise RuntimeError("فایل test_accounts.json خراب یا غیرقابل‌خواندن است؛ برای جلوگیری از ازدست‌رفتن اطلاعات آن را پاک نکنید.") from exc


def save_test_accounts(data):
    tmp = TEST_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(TEST_FILE)


async def test_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not is_admin(user.id):
        await update.effective_message.reply_text("⛔ این دستور فقط برای ادمین است.")
        return
    raw = " ".join(context.args or []).strip()
    if not raw or len(context.args or []) < 2:
        await update.effective_message.reply_text(
            "فرمت دستور:\n/test_add نام_سرور لینک_تست\n\n"
            "مثال:\n/test_add Turkey https://example.com/test-link\n\n"
            "هر بار فقط یک لینک اضافه کنید. نام سرور می‌تواند بدون فاصله یا با زیرخط باشد."
        )
        return
    server_name = context.args[0].replace("_", " ")[:80]
    link = " ".join(context.args[1:]).strip()
    if len(link) > 2000 or not (link.startswith("https://") or link.startswith("http://")):
        await update.effective_message.reply_text("لینک معتبر نیست؛ لینک باید با http:// یا https:// شروع شود.")
        return
    try:
        async with TEST_ACCOUNTS_LOCK:
            data = load_test_accounts()
            # Never re-queue a link that is waiting OR was already delivered.
            claimed_links = {
                str(record.get("link", "")).strip()
                for record in data["claimed_users"].values()
                if isinstance(record, dict)
            }
            if any(str(item.get("link", "")).strip() == link for item in data["available"]) or link in claimed_links:
                await update.effective_message.reply_text("⛔ این لینک قبلاً اضافه یا به مشتری تحویل شده است؛ برای جلوگیری از ارسال تکراری دوباره ثبت نشد.")
                return
            test_id = int(data["next_id"])
            data["next_id"] = test_id + 1
            data["available"].append({"id": test_id, "server": server_name, "link": link, "added_at": datetime.now().isoformat(timespec="seconds")})
            save_test_accounts(data)
            remaining = len(data["available"])
    except Exception:
        logger.exception("Could not add test link")
        await update.effective_message.reply_text("⚠️ ذخیره لینک تست ناموفق بود. فایل test_accounts.json را بررسی کن.")
        return
    await update.effective_message.reply_text(f"✅ لینک تست #{test_id} برای سرور «{server_name}» اضافه شد.\nتعداد لینک‌های آماده: {remaining}")


async def test_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not is_admin(user.id):
        await update.effective_message.reply_text("⛔ این دستور فقط برای ادمین است.")
        return
    try:
        async with TEST_ACCOUNTS_LOCK:
            data = load_test_accounts()
            available = list(data["available"])
            claimed = dict(data["claimed_users"])
    except Exception:
        logger.exception("Could not list test links")
        await update.effective_message.reply_text("⚠️ فایل اکانت تست قابل خواندن نیست.")
        return
    lines = [f"🧪 لینک‌های آماده: {len(available)}", f"👥 کاربران دریافت‌کننده: {len(claimed)}", ""]
    for item in available[:100]:
        lines.append(f"#{item.get('id')} — {item.get('server', 'سرور نامشخص')}")
    if not available:
        lines.append("صف لینک‌های تست خالی است. با /test_add لینک اضافه کنید.")
    await update.effective_message.reply_text("\n".join(lines))


async def test_request_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    if not user or not query.message:
        return
    if not is_admin(user.id) and await section_gate(query.message, "test"):
        return

    user_key = str(user.id)
    # Claim + save happen under one lock: each user gets one link, and each link
    # can be allocated to at most one user even if requests arrive together.
    try:
        async with TEST_ACCOUNTS_LOCK:
            data = load_test_accounts()
            if user_key in data["claimed_users"]:
                claimed = dict(data["claimed_users"][user_key])
                item = None
                remaining = len(data["available"])
            elif not data["available"]:
                claimed = None
                item = None
                remaining = 0
            else:
                item = data["available"].pop(0)  # consume exactly ONE next link
                data["claimed_users"][user_key] = {
                    "test_id": item.get("id"),
                    "server": item.get("server", "سرور نامشخص"),
                    "link": item.get("link", ""),
                    "claimed_at": datetime.now().isoformat(timespec="seconds"),
                }
                save_test_accounts(data)  # persist before sending, preventing duplicate delivery
                claimed = None
                remaining = len(data["available"])
    except Exception:
        logger.exception("Could not safely allocate test account")
        await query.message.reply_text(
            "⚠️ دریافت تست فعلاً انجام نشد چون ذخیره اطلاعات با خطا روبه‌رو شد. لطفاً به پشتیبانی اطلاع بده.",
            reply_markup=MAIN_MARKUP,
        )
        return

    if item is None and claimed is not None:
        await query.message.reply_text(
            "⛔ شما قبلاً اکانت تست دریافت کرده‌اید؛ هر کاربر فقط یک تست می‌تواند بگیرد.\n"
            f"سرور قبلی: {claimed.get('server', 'نامشخص')}",
            reply_markup=MAIN_MARKUP,
        )
        return
    if item is None:
        await query.message.reply_text(
            "😕 فعلاً لینک تست آماده نداریم. لطفاً بعداً مراجعه کن.",
            reply_markup=MAIN_MARKUP,
        )
        return

    try:
        await query.message.reply_text(
            f"🧪 اکانت تست شما\nسرور: {item.get('server', 'نامشخص')}\n\n{item['link']}\n\n"
            "✅ این تست به حساب شما ثبت شد. هر کاربر فقط یک تست می‌تواند دریافت کند. "
            "این لینک از صف حذف شد و به مشتری بعدی داده نمی‌شود؛ مشتری بعدی لینک بعدی صف را می‌گیرد.",
            reply_markup=MAIN_MARKUP,
            disable_web_page_preview=True,
        )
    except TelegramError:
        # Allocation remains consumed so it cannot accidentally be sent to another user.
        logger.exception("Could not deliver allocated test link to user %s", user.id)
        return

    for admin_id in sorted(load_admin_ids()):
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=(f"🧪 تست تحویل شد\nکاربر: {user.full_name}\nآیدی: {user.id}\n"
                      f"سرور: {item.get('server', 'نامشخص')}\nشناسه تست: #{item.get('id')}\n"
                      f"لینک‌های باقی‌مانده: {remaining}"),
            )
        except Exception:
            logger.exception("Could not notify admin about test claim")


async def menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.business_message:
        return
    if update.effective_user:
        remember_user(update.effective_user.id)
    if await access_gate(update, context):
        return
    txt = (update.message.text or "").strip()

    # Admin-only plan editor, broadcast and direct-message workflows.
    if update.effective_user and is_admin(update.effective_user.id):
        if txt in ("لغو", "انصراف", "❌ لغو") and any(k in context.user_data for k in ("admin_plan_flow", "admin_broadcast_waiting", "admin_sendone_stage")):
            for k in ("admin_plan_flow", "admin_broadcast_waiting", "admin_broadcast_draft", "admin_sendone_stage", "admin_sendone_target", "admin_sendone_draft"):
                context.user_data.pop(k, None)
            await update.message.reply_text("عملیات لغو شد.", reply_markup=admin_panel_markup())
            return
        plan_flow = context.user_data.get("admin_plan_flow")
        if plan_flow:
            stage = plan_flow.get("stage"); product = plan_flow.get("product")
            if product not in PRODUCTS:
                context.user_data.pop("admin_plan_flow", None)
                await update.message.reply_text("سرویس پیدا نشد؛ دوباره از پنل انتخاب کن.", reply_markup=admin_panel_markup()); return
            if stage in ("add_label", "edit_label"):
                label = txt.strip()
                if not label or len(label) > 60:
                    await update.message.reply_text("نام پلن باید بین ۱ تا ۶۰ نویسه باشد."); return
                if stage == "add_label":
                    if any(existing.lower() == label.lower() for existing, _ in PRODUCTS[product]):
                        await update.message.reply_text("این نام پلن از قبل وجود دارد؛ نام دیگری انتخاب کن."); return
                    plan_flow["new_label"] = label; plan_flow["stage"] = "add_price"
                    await update.message.reply_text(f"نام پلن: {label}\nحالا مبلغ این پلن را به تومان فقط با عدد بفرست.")
                    return
                ti = int(plan_flow.get("tier_index", -1))
                if not 0 <= ti < len(PRODUCTS[product]):
                    context.user_data.pop("admin_plan_flow", None); await update.message.reply_text("پلن پیدا نشد.", reply_markup=admin_panel_markup()); return
                if any(i != ti and existing.lower() == label.lower() for i, (existing, _) in enumerate(PRODUCTS[product])):
                    await update.message.reply_text("این نام از قبل برای پلن دیگری استفاده شده."); return
                old_label, old_price = PRODUCTS[product][ti]; PRODUCTS[product][ti] = (label, old_price)
                save_price_overrides(); context.user_data.pop("admin_plan_flow", None)
                await update.message.reply_text(f"✅ نام پلن تغییر کرد: {old_label} ← {label}", reply_markup=admin_plan_tiers_markup(int(plan_flow.get("product_index", 0))))
                return
            if stage in ("add_price", "edit_price"):
                raw = normalize_digits(txt).replace(",", "").replace("٬", "").replace(" ", "")
                if not raw.isdigit() or not 1 <= int(raw) <= 1000000000:
                    await update.message.reply_text("مبلغ باید عددی بین ۱ تا ۱٬۰۰۰٬۰۰۰٬۰۰۰ تومان باشد."); return
                amount = int(raw)
                if stage == "add_price":
                    label = plan_flow.get("new_label")
                    PRODUCTS[product].append((label, amount))
                    try: save_price_overrides()
                    except Exception:
                        PRODUCTS[product].pop(); logger.exception("Could not save new plan")
                        await update.message.reply_text("ذخیره پلن ناموفق بود؛ فضای ذخیره‌سازی را بررسی کن."); return
                    context.user_data.pop("admin_plan_flow", None)
                    pi = list(PRODUCTS).index(product)
                    await update.message.reply_text(f"✅ پلن «{label}» با قیمت {money(amount)} تومان اضافه شد.", reply_markup=admin_plan_tiers_markup(pi)); return
                ti = int(plan_flow.get("tier_index", -1))
                if not 0 <= ti < len(PRODUCTS[product]):
                    context.user_data.pop("admin_plan_flow", None); await update.message.reply_text("پلن پیدا نشد.", reply_markup=admin_panel_markup()); return
                label, old = PRODUCTS[product][ti]; PRODUCTS[product][ti] = (label, amount)
                try: save_price_overrides()
                except Exception:
                    PRODUCTS[product][ti] = (label, old); logger.exception("Could not save plan price")
                    await update.message.reply_text("ذخیره مبلغ ناموفق بود."); return
                context.user_data.pop("admin_plan_flow", None)
                await update.message.reply_text(f"✅ مبلغ پلن ذخیره شد: {label} — {money(old)} ← {money(amount)} تومان", reply_markup=admin_plan_tiers_markup(int(plan_flow.get("product_index", 0)))); return
        if context.user_data.get("admin_broadcast_waiting"):
            context.user_data.pop("admin_broadcast_waiting", None)
            if not txt:
                await update.message.reply_text("متن پیام خالی است؛ دوباره از پنل شروع کن.", reply_markup=admin_panel_markup()); return
            context.user_data["admin_broadcast_draft"] = txt
            await update.message.reply_text(f"پیش‌نمایش پیام همگانی برای {len(load_users())} عضو ثبت‌شده:\n\n{txt[:3000]}\n\nارسال شود؟", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ ارسال به همه", callback_data="adminpanel:broadcast_send"), InlineKeyboardButton("❌ لغو", callback_data="adminpanel:broadcast_cancel")]]))
            return
        sendone_stage = context.user_data.get("admin_sendone_stage")
        if sendone_stage == "user_id":
            normalized = normalize_digits(txt).strip()
            if not normalized.isdigit() or int(normalized) <= 0:
                await update.message.reply_text("آیدی عددی معتبر مشتری را بفرست؛ برای لغو بنویس لغو."); return
            target = int(normalized)
            if target not in load_users():
                await update.message.reply_text("این آیدی در فهرست اعضای شناخته‌شده ربات نیست؛ آیدی را بررسی کن یا از مشتری بخواه /start بزند."); return
            context.user_data["admin_sendone_target"] = target
            context.user_data["admin_sendone_stage"] = "message"
            await update.message.reply_text(f"✉️ آیدی مشتری: {target}\nحالا متن پیام را بفرست.")
            return
        if sendone_stage == "message":
            target = context.user_data.get("admin_sendone_target")
            if not txt:
                await update.message.reply_text("متن پیام خالی است؛ متن را بفرست یا لغو کن."); return
            context.user_data["admin_sendone_draft"] = txt
            context.user_data.pop("admin_sendone_stage", None)
            await update.message.reply_text(f"پیش‌نمایش پیام برای مشتری {target}:\n\n{txt[:3000]}\n\nارسال شود؟", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ ارسال پیام", callback_data="adminpanel:sendone_send"), InlineKeyboardButton("❌ لغو", callback_data="adminpanel:sendone_cancel")]]))
            return

    # Admin price editor: only the admin who selected a tariff can complete the edit.
    pending_price = context.user_data.get("admin_price_edit")
    if pending_price:
        if not update.effective_user or not is_admin(update.effective_user.id):
            context.user_data.pop("admin_price_edit", None)
            return
        if txt in ("لغو", "انصراف", "❌ لغو"):
            context.user_data.pop("admin_price_edit", None)
            await update.message.reply_text("تغییر قیمت لغو شد.", reply_markup=admin_panel_markup())
            return
        raw_price = normalize_digits(txt).replace(",", "").replace("٬", "").replace(" ", "")
        if not raw_price.isdigit():
            await update.message.reply_text("قیمت باید فقط عدد باشد؛ مثال: 8000. برای لغو بنویس: لغو")
            return
        new_price = int(raw_price)
        if not 1 <= new_price <= 1000000000:
            await update.message.reply_text("قیمت باید بین ۱ تا ۱٬۰۰۰٬۰۰۰٬۰۰۰ تومان باشد.")
            return
        product = pending_price.get("product")
        tier_index = pending_price.get("tier_index")
        if product not in PRODUCTS or not isinstance(tier_index, int) or not 0 <= tier_index < len(PRODUCTS[product]):
            context.user_data.pop("admin_price_edit", None)
            await update.message.reply_text("تعرفه پیدا نشد؛ دوباره از پنل انتخاب کن.", reply_markup=admin_panel_markup())
            return
        label, old_price = PRODUCTS[product][tier_index]
        PRODUCTS[product][tier_index] = (label, new_price)
        try:
            save_price_overrides()
        except Exception:
            PRODUCTS[product][tier_index] = (label, old_price)
            logger.exception("Could not save changed product price")
            await update.message.reply_text("ذخیره قیمت انجام نشد؛ دسترسی فایل‌ها را بررسی کن.")
            return
        context.user_data.pop("admin_price_edit", None)
        await update.message.reply_text(f"✅ قیمت ذخیره شد و بعد از راه‌اندازی مجدد هم باقی می‌ماند.\n{product} — {label}: {money(old_price)} ← {money(new_price)} تومان", reply_markup=admin_panel_markup())
        return

    # Admin discount wizard: ask for customer numeric ID first, then discount percent.
    discount_stage = context.user_data.get("admin_discount_stage")
    if discount_stage:
        if not update.effective_user or not is_admin(update.effective_user.id):
            context.user_data.pop("admin_discount_stage", None)
            context.user_data.pop("admin_discount_target", None)
            return
        if txt in ("لغو", "انصراف", "❌ لغو"):
            context.user_data.pop("admin_discount_stage", None)
            context.user_data.pop("admin_discount_target", None)
            await update.message.reply_text("تغییر تخفیف لغو شد.", reply_markup=admin_panel_markup())
            return
        normalized_txt = normalize_digits(txt).strip()
        if discount_stage == "user_id":
            if not normalized_txt.isdigit() or int(normalized_txt) <= 0:
                await update.message.reply_text("آیدی عددی مشتری را فقط با عدد معتبر بفرست. برای لغو بنویس: لغو")
                return
            target_id = int(normalized_txt)
            context.user_data["admin_discount_target"] = target_id
            context.user_data["admin_discount_stage"] = "percent"
            current = load_user_discount_percent(target_id)
            await update.message.reply_text(
                f"🏷 مشتری: {target_id}\nتخفیف فعلی مؤثر: {current}٪\n\n"
                "حالا درصد تخفیف را از ۰ تا ۱۰۰ بفرست.\n"
                "عدد ۰ تخفیف اختصاصی را حذف می‌کند و مشتری به تخفیف عمومی برمی‌گردد."
            )
            return
        if discount_stage == "percent":
            if not normalized_txt.isdigit():
                await update.message.reply_text("درصد را فقط به‌صورت عددی بین ۰ تا ۱۰۰ بفرست.")
                return
            percent = int(normalized_txt)
            if not 0 <= percent <= 100:
                await update.message.reply_text("درصد تخفیف باید بین ۰ تا ۱۰۰ باشد.")
                return
            target_id = context.user_data.get("admin_discount_target")
            if not isinstance(target_id, int) or target_id <= 0:
                context.user_data.pop("admin_discount_stage", None)
                context.user_data.pop("admin_discount_target", None)
                await update.message.reply_text("آیدی مشتری ثبت نشده؛ دوباره از پنل تخفیف را انتخاب کن.", reply_markup=admin_panel_markup())
                return
            try:
                save_user_discount_percent(target_id, percent)
            except Exception:
                logger.exception("Could not save customer discount")
                await update.message.reply_text("ذخیره تخفیف انجام نشد؛ فایل‌های ربات را بررسی کن.")
                return
            context.user_data.pop("admin_discount_stage", None)
            context.user_data.pop("admin_discount_target", None)
            if percent:
                result = (f"✅ تخفیف اختصاصی {percent}٪ برای مشتری {target_id} ذخیره شد.\n"
                          "از سفارش‌های جدید این مشتری اعمال می‌شود؛ سفارش‌های قبلی تغییر نمی‌کنند.")
            else:
                result = (f"✅ تخفیف اختصاصی مشتری {target_id} حذف شد.\n"
                          "از این پس تخفیف عمومی (در صورت فعال بودن) برای او محاسبه می‌شود.")
            await update.message.reply_text(result, reply_markup=admin_panel_markup())
            return

    # A selected support reply takes priority over config delivery and customer flows.
    if await deliver_support_reply(update, context):
        return

    # Important: prioritize an admin's direct config delivery before customer flows
    # (service naming, support, quantities, etc.) can intercept the message.
    if await handle_config_text(update, context):
        return

    if context.user_data.get("service_name_waiting"):
        if txt in ("❌ لغو خرید", "لغو"):
            context.user_data.pop("service_name_waiting", None)
            context.user_data.pop("pending_order", None)
            await update.message.reply_text("خرید لغو شد.", reply_markup=MAIN_MARKUP)
            return
        if not txt or len(txt) > 50:
            await update.message.reply_text("نام سرویس باید بین ۱ تا ۵۰ نویسه باشد. دوباره بفرستید.")
            return
        pending = context.user_data.get("pending_order")
        if not pending:
            context.user_data.pop("service_name_waiting", None)
            await update.message.reply_text("اطلاعات سفارش پیدا نشد؛ لطفاً خرید را دوباره شروع کنید.", reply_markup=MAIN_MARKUP)
            return
        pending["service_name"] = txt
        context.user_data["service_name_waiting"] = False
        percent = pending.get("discount_percent", 0)
        discount_line = (f"💵 مبلغ قبل از تخفیف: {money(pending['original_amount'])}\n🏷 تخفیف: {percent}٪\n" if percent else "")
        await update.message.reply_text(
            f"🧾 خلاصه سفارش\n\n🌐 سرویس: {pending['panel']}\n📦 محصول: {pending['product']}\n"
            f"🏷 نام انتخابی شما: {txt}\n📊 حجم/تعداد: {pending['quantity']}\n"
            f"{discount_line}💵 مبلغ قابل پرداخت: {money(pending['amount'])}\n\n"
            "💳 پس از ثبت سفارش، عکس رسید پرداخت را ارسال کنید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ پرداخت با رسید بانکی", callback_data="confirm_order")],
                [InlineKeyboardButton("❌ لغو خرید", callback_data="cancel_order")],
            ]),
        )
        return

    if txt in ("🔙 منوی اصلی", "🔙 بازگشت به منوی اصلی"):
        # If the user is in the payment/receipt stage, treat going back as cancelling that order.
        await cancel_active_order(update.effective_user.id, context)
        for key in ("quantity_waiting", "pending_order", "market_flow", "panel", "product", "unit_price", "config_flow", "contact_flow"):
            context.user_data.pop(key, None)
        await update.message.reply_text("به منوی اصلی برگشتید. عملیات نیمه‌کاره لغو شد.", reply_markup=MAIN_MARKUP)
        return

    if txt == "🔙 بازگشت به انتخاب سرور":
        context.user_data.pop("contact_flow", None)
        context.user_data.pop("quantity_waiting", None)
        context.user_data.pop("pending_order", None)
        context.user_data.pop("panel", None)
        context.user_data.pop("product", None)
        context.user_data.pop("unit_price", None)
        await begin_purchase(update, context)
        return

    # Support and dealership requests are forwarded to the configured admins.
    contact_flow = context.user_data.get("contact_flow")
    if contact_flow:
        if txt in ("لغو", "انصراف", "/cancel"):
            context.user_data.pop("contact_flow", None)
            await update.message.reply_text("عملیات لغو شد.", reply_markup=MAIN_MARKUP)
            return
        user = update.effective_user
        username = f"@{user.username}" if user and user.username else "ندارد"
        display_name = user.full_name if user else "نامشخص"
        if contact_flow == "support":
            subject = "📩 پیام جدید پشتیبانی"
            body = txt
        else:
            subject = "🤝 درخواست جدید نمایندگی"
            body = txt
        target_id = user.id if user else 0
        admin_text = (
            f"{subject}\n\n"
            f"👤 نام: {display_name}\n"
            f"🔗 نام کاربری: {username}\n"
            f"🆔 آیدی عددی: {target_id}\n\n"
            f"📝 متن درخواست:\n{body[:3500]}"
        )
        username_value = (user.username if user else None)
        private_url = f"https://t.me/{username_value}" if username_value else f"tg://user?id={target_id}"
        admin_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✍️ ۱. جواب دادن مستقیم", callback_data=f"support_reply:{target_id}")],
            [InlineKeyboardButton("👤 ۲. رفتن به پیوی مشتری", url=private_url)],
        ])
        sent = 0
        for admin_id in load_admin_ids():
            try:
                await context.bot.send_message(chat_id=admin_id, text=admin_text, reply_markup=admin_keyboard)
                sent += 1
            except Exception:
                logger.exception("Could not forward %s message from user %s to admin %s", contact_flow, user.id if user else None, admin_id)
        context.user_data.pop("contact_flow", None)
        if sent:
            await update.message.reply_text(
                "✅ درخواست شما ثبت و برای مدیریت ارسال شد. پاسخ پشتیبانی از همین ربات برایتان فرستاده می‌شود.",
                reply_markup=MAIN_MARKUP,
            )
        else:
            await update.message.reply_text(
                "⚠️ پیام شما فعلاً به مدیریت نرسید. لطفاً کمی بعد دوباره تلاش کنید یا مستقیماً به پشتیبانی پیام بدهید.",
                reply_markup=MAIN_MARKUP,
            )
        return

    if await handle_quantity(update, context):
        return

    if await market_text_input(update, context):
        return

    if txt == "🎮 شاپ اکانت بازی‌ها":
        if not is_admin(update.effective_user.id) and await section_gate(update.message, "market"):
            return
        await market_open(update, context)
    elif txt == "💎 خدمات مجازی":
        if not is_admin(update.effective_user.id) and await section_gate(update.message, "virtual"):
            return
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💎 تلگرام پرمیوم — ۱ ماه | ۱٬۲۰۰٬۰۰۰ تومان", callback_data="virtual:0")],
            [InlineKeyboardButton("💎 تلگرام پرمیوم — ۳ ماه | ۳٬۹۰۰٬۰۰۰ تومان", callback_data="virtual:1")],
            [InlineKeyboardButton("💎 تلگرام پرمیوم — ۶ ماه | ۸٬۰۰۰٬۰۰۰ تومان", callback_data="virtual:2")],
            [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="global_back")],
        ])
        await update.message.reply_text("💎 خدمات مجازی\n\nپلن موردنظر تلگرام پرمیوم را انتخاب کنید:", reply_markup=keyboard)
    elif txt == "🚀 خرید سرویس جدید":
        await begin_purchase(update, context)
    elif txt == "💰 تعرفه سرویس‌ها":
        if not is_admin(update.effective_user.id) and await section_gate(update.message, "tariffs"):
            return
        await show_tariffs(update, context)
    elif txt == "📱 سرویس‌های من":
        await my_orders(update, context)
    elif txt == "🧪 اکانت تست":
        if not is_admin(update.effective_user.id) and await section_gate(update.message, "test"):
            return
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎁 دریافت اکانت تست رایگان", callback_data="test:request")],
            [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="global_back")],
        ])
        await update.message.reply_text(
            "🧪 دریافت اکانت تست\n\nهر کاربر فقط یک‌بار می‌تواند تست دریافت کند. لینک‌ها به ترتیب توسط ادمین اضافه می‌شوند و هر لینک فقط یک‌بار از صف تحویل داده می‌شود.",
            reply_markup=keyboard,
        )
    elif txt == "♻️ تمدید سرویس":
        if not is_admin(update.effective_user.id) and await section_gate(update.message, "renew"):
            return
        await my_orders(update, context)
    elif txt == "💡 آموزش استفاده":
        await update.message.reply_text("آموزش استفاده فعلاً در حال آماده‌سازی است.", reply_markup=MAIN_MARKUP)
    elif txt == "🎗️ کاربران برتر":
        await update.message.reply_text("فهرست کاربران برتر فعلاً در دسترس نیست.", reply_markup=MAIN_MARKUP)
    elif txt == "👥 معرفی به دوستان":
        bot_username = context.bot_data.get("bot_username", "")
        await update.message.reply_text(
            f"لینک معرفی شما:\nhttps://t.me/{bot_username}?start={update.effective_user.id}"
            if bot_username else "لینک معرفی در دسترس نیست.",
            reply_markup=MAIN_MARKUP,
        )
    elif txt == "🧑🏻‍💻 تماس با پشتیبانی":
        context.user_data["contact_flow"] = "support"
        await update.message.reply_text(
            "🧑🏻‍💻 پیام خود را برای پشتیبانی بنویسید تا برای مدیریت ارسال شود.\n\n"
            "برای لغو، کلمه «لغو» را بفرستید.",
            reply_markup=MAIN_MARKUP,
        )
    elif txt == "🤝 درخواست نمایندگی":
        context.user_data["contact_flow"] = "representative"
        await update.message.reply_text(
            "🤝 درخواست نمایندگی\n\n"
            "لطفاً در یک پیام این اطلاعات را بنویسید: نام، شهر/کشور، روش جذب مشتری و سابقه فروش (در صورت وجود).\n\n"
            "درخواست شما برای مدیریت ارسال می‌شود. برای لغو، کلمه «لغو» را بفرستید.",
            reply_markup=MAIN_MARKUP,
        )


# ================= ONLINE GAME ACCOUNT MARKETPLACE =================
def load_market_listings():
    if not MARKET_FILE.exists():
        return {"next_id": 1, "listings": {}}
    try:
        with MARKET_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("next_id", 1)
        data.setdefault("listings", {})
        return data
    except Exception as exc:
        logger.exception("Could not read game account marketplace database")
        # Never silently replace a damaged marketplace database with an empty one.
        raise RuntimeError(
            "فایل game_account_listings.json قابل خواندن نیست؛ برای جلوگیری از گم‌شدن آگهی‌ها، "
            "فایل را حذف نکنید و ابتدا از آن نسخه پشتیبان بگیرید."
        ) from exc


def save_market_listings(data):
    tmp = MARKET_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(MARKET_FILE)


def market_menu_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍 مشاهده اکانت‌های ثبت‌شده", callback_data="market:browse:0")],
        [InlineKeyboardButton("➕ ثبت اکانت برای فروش", callback_data="market:sell")],
        [InlineKeyboardButton("📦 آگهی‌های من / حذف آگهی", callback_data="market:mine")],
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="market:home")],
    ])


async def market_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("market_flow", None)
    await update.effective_message.reply_text(
        "🎮 شاپ اکانت بازی‌های آنلاین\n\n"
        "اینجا می‌توانید برای بازی‌های آنلاین مختلف آگهی ثبت کنید یا آگهی‌های موجود را ببینید.\n"
        "برای ثبت آگهی حداقل ۵ عکس لازم است. خرید و پرداخت فقط پس از هماهنگی با پشتیبانی و بررسی جزئیات انجام شود؛ ربات پرداخت امانی یا تضمین معامله را به‌صورت خودکار انجام نمی‌دهد.",
        reply_markup=market_menu_markup(),
    )


async def market_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    flow = context.user_data.get("market_flow")
    if not flow or not update.message or not update.message.text:
        return False
    value = update.message.text.strip()
    if value in ("❌ لغو ثبت آگهی", "🔙 بازگشت به انتخاب سرور"):
        context.user_data.pop("market_flow", None)
        await update.message.reply_text("ثبت آگهی لغو شد.", reply_markup=MAIN_MARKUP)
        return True
    if flow.get("step") == "game":
        if len(value) < 2 or len(value) > 80:
            await update.message.reply_text("نام بازی را بین ۲ تا ۸۰ نویسه وارد کنید.")
            return True
        flow["game"] = value
        flow["step"] = "level"
        await update.message.reply_text("🎚 لول اکانت را وارد کنید (مثلاً ۶۵ یا «لول نامشخص»):")
        return True
    if flow.get("step") == "level":
        if len(value) > 60:
            await update.message.reply_text("لطفاً لول را کوتاه‌تر وارد کنید.")
            return True
        flow["level"] = value
        flow["step"] = "price"
        await update.message.reply_text("💰 قیمت درخواستی را به تومان و فقط با عدد انگلیسی وارد کنید (مثلاً 1500000):")
        return True
    if flow.get("step") == "price":
        try:
            price = int(value.replace(",", "").replace("٬", ""))
        except ValueError:
            await update.message.reply_text("قیمت باید عدد صحیح انگلیسی باشد؛ مثال: 1500000")
            return True
        if price < 1000 or price > 10_000_000_000:
            await update.message.reply_text("قیمت باید بین ۱٬۰۰۰ تا ۱۰٬۰۰۰٬۰۰۰٬۰۰۰ تومان باشد.")
            return True
        flow["price"] = price
        flow["step"] = "description"
        await update.message.reply_text("📝 توضیحات آگهی را بفرستید (آیتم‌ها، اسکین‌ها، رتبه و نکات مهم). اطلاعات ورود یا رمز را ارسال نکنید:")
        return True
    if flow.get("step") == "description":
        if len(value) > 800:
            await update.message.reply_text("توضیحات حداکثر ۸۰۰ نویسه باشد.")
            return True
        flow["description"] = value
        flow["step"] = "photos"
        flow["photos"] = []
        await update.message.reply_text(
            "📸 حالا حداقل ۵ عکس واضح از اکانت بفرستید. پس از ارسال ۵ عکس یا بیشتر، دکمه «اتمام ارسال عکس‌ها» را بزنید.",
            reply_markup=ReplyKeyboardMarkup([["✅ اتمام ارسال عکس‌ها"], ["❌ لغو ثبت آگهی"], ["🔙 منوی اصلی"]], resize_keyboard=True, one_time_keyboard=False),
        )
        return True
    if flow.get("step") == "photos" and value == "✅ اتمام ارسال عکس‌ها":
        if len(flow.get("photos", [])) < 5:
            await update.message.reply_text(f"هنوز فقط {len(flow.get('photos', []))} عکس دریافت شده؛ حداقل ۵ عکس لازم است.")
            return True
        flow["step"] = "confirm"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ انتشار آگهی", callback_data="market:publish")],
            [InlineKeyboardButton("❌ لغو", callback_data="market:cancel")],
        ])
        await update.message.reply_text(
            f"📋 پیش‌نمایش آگهی\nبازی: {flow['game']}\nلول: {flow['level']}\nقیمت: {money(flow['price'])}\nعکس‌ها: {len(flow['photos'])}\nتوضیحات: {flow['description']}\n\nبا انتشار آگهی، تأیید می‌کنید مالک/مجاز به فروش اکانت هستید و اطلاعات آگهی درست است.",
            reply_markup=keyboard,
        )
        return True
    return False


async def market_photo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await handle_config_media(update, context):
        return
    flow = context.user_data.get("market_flow")
    if flow and flow.get("step") == "photos" and update.message and update.message.photo:
        photos = flow.setdefault("photos", [])
        if len(photos) >= 10:
            await update.message.reply_text("حداکثر ۱۰ عکس برای هر آگهی پذیرفته می‌شود.")
            return
        photos.append(update.message.photo[-1].file_id)
        await update.message.reply_text(f"✅ عکس {len(photos)} ثبت شد. حداقل ۵ عکس لازم است؛ برای ادامه دکمه «اتمام ارسال عکس‌ها» را بزنید.")
        return
    await handle_receipt(update, context)


async def market_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user
    if not is_admin(user.id) and await section_gate(query.message, "market"):
        return
    if data == "market:home":
        context.user_data.pop("market_flow", None)
        await query.message.reply_text("به منوی اصلی برگشتید.", reply_markup=MAIN_MARKUP)
        return
    if data == "market:sell":
        context.user_data["market_flow"] = {"step": "game", "seller_id": user.id}
        await query.message.reply_text("🎮 نام بازی آنلاین را وارد کنید (مثلاً Free Fire، PUBG Mobile، Roblox، Fortnite یا هر بازی دیگر):", reply_markup=ReplyKeyboardMarkup([["❌ لغو ثبت آگهی"], ["🔙 منوی اصلی"]], resize_keyboard=True, one_time_keyboard=False))
        return
    if data == "market:cancel":
        context.user_data.pop("market_flow", None)
        await query.message.reply_text("ثبت آگهی لغو شد.", reply_markup=MAIN_MARKUP)
        return
    if data == "market:publish":
        flow = context.user_data.get("market_flow")
        if not flow or flow.get("step") != "confirm" or len(flow.get("photos", [])) < 5:
            await query.message.reply_text("اطلاعات آگهی کامل نیست؛ دوباره از شاپ اکانت شروع کنید.")
            return
        db = load_market_listings()
        listing_id = int(db["next_id"])
        db["next_id"] = listing_id + 1
        db["listings"][str(listing_id)] = {
            "id": listing_id, "seller_id": user.id,
            "seller_name": user.full_name[:100], "game": flow["game"],
            "level": flow["level"], "price": flow["price"],
            "description": flow["description"], "photos": flow["photos"],
            "status": "active", "created_at": datetime.now().isoformat(timespec="seconds")
        }
        save_market_listings(db)
        context.user_data.pop("market_flow", None)
        await query.message.reply_text(f"✅ آگهی #{listing_id} منتشر شد و در فهرست آگهی‌ها نمایش داده می‌شود. هر زمان خواستید از «آگهی‌های من / حذف آگهی» آن را بردارید.", reply_markup=MAIN_MARKUP)
        return
    if data == "market:mine":
        db = load_market_listings()
        mine = [x for x in db["listings"].values() if x.get("seller_id") == user.id and x.get("status") == "active"]
        if not mine:
            await query.message.reply_text("آگهی فعال ندارید.", reply_markup=market_menu_markup())
            return
        keyboard = [[InlineKeyboardButton(f"❌ حذف آگهی #{x['id']} — {x['game']} — {money(x['price'])}", callback_data=f"market:remove:{x['id']}")] for x in mine[:50]]
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="market:menu")])
        await query.message.reply_text("آگهی‌های فعال شما؛ برای برداشتن آگهی دکمه مربوط به آن را بزنید:", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    if data == "market:menu":
        await query.message.reply_text("🎮 شاپ اکانت بازی‌های آنلاین:", reply_markup=market_menu_markup())
        return
    if data.startswith("market:remove:"):
        listing_id = data.rsplit(":", 1)[1]
        db = load_market_listings()
        listing = db["listings"].get(listing_id)
        if not listing or listing.get("seller_id") != user.id:
            await query.message.reply_text("این آگهی متعلق به شما نیست یا پیدا نشد.")
            return
        listing["status"] = "removed"
        listing["removed_at"] = datetime.now().isoformat(timespec="seconds")
        save_market_listings(db)
        await query.message.reply_text(f"✅ آگهی #{listing_id} از فهرست عمومی برداشته شد.", reply_markup=market_menu_markup())
        return
    if data.startswith("market:browse:"):
        db = load_market_listings()
        active = sorted([x for x in db["listings"].values() if x.get("status") == "active"], key=lambda x: x.get("id", 0), reverse=True)
        if not active:
            await query.message.reply_text("فعلاً آگهی فعالی ثبت نشده است. بعداً دوباره سر بزنید.", reply_markup=market_menu_markup())
            return
        try:
            page = max(0, int(data.rsplit(":", 1)[1]))
        except (ValueError, IndexError):
            await query.message.reply_text("صفحه درخواستی معتبر نیست؛ فهرست از ابتدا باز می‌شود.", reply_markup=market_menu_markup())
            return
        page_size = 8
        max_page = max(0, (len(active) - 1) // page_size)
        page = min(page, max_page)
        subset = active[page * page_size:(page + 1) * page_size]
        keyboard = [[InlineKeyboardButton(f"{x['game']} | لول {x['level']} | {money(x['price'])}", callback_data=f"market:view:{x['id']}")] for x in subset]
        nav = []
        if page > 0: nav.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"market:browse:{page-1}"))
        if (page + 1) * page_size < len(active): nav.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"market:browse:{page+1}"))
        if nav: keyboard.append(nav)
        keyboard.append([InlineKeyboardButton("🔙 منوی شاپ اکانت", callback_data="market:menu")])
        await query.message.reply_text("🛍 آگهی‌های فعال (برای جزئیات روی آگهی بزنید):\n\nقیمت‌ها را فروشندگان تعیین می‌کنند؛ پیش از پرداخت، مشخصات را با پشتیبانی بررسی کنید.", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    if data.startswith("market:view:"):
        listing_id = data.rsplit(":", 1)[1]
        db = load_market_listings()
        listing = db["listings"].get(listing_id)
        if not listing or listing.get("status") != "active":
            await query.message.reply_text("این آگهی دیگر فعال نیست.")
            return
        await query.message.reply_text(
            f"🎮 آگهی #{listing_id}\nبازی: {listing['game']}\nلول: {listing['level']}\nقیمت درخواستی: {money(listing['price'])}\nتعداد عکس: {len(listing.get('photos', []))}\nتوضیحات: {listing.get('description', '—')}\n\nبرای خرید، درخواست را بزنید تا با پشتیبانی هماهنگ شود. تا زمان بررسی، پول یا اطلاعات ورود را مستقیم برای فروشنده نفرستید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🤝 درخواست خرید از طریق پشتیبانی", callback_data=f"market:buy:{listing_id}")],
                [InlineKeyboardButton("🔙 برگشت به آگهی‌ها", callback_data="market:browse:0")],
            ])
        )
        photos = listing.get("photos", [])[:10]
        if photos:
            try:
                await context.bot.send_media_group(chat_id=query.message.chat_id, media=[InputMediaPhoto(media=fid) for fid in photos])
            except Exception:
                for fid in photos:
                    try: await context.bot.send_photo(chat_id=query.message.chat_id, photo=fid)
                    except Exception: logger.exception("Could not display marketplace photo")
        return
    if data.startswith("market:buy:"):
        listing_id = data.rsplit(":", 1)[1]
        db = load_market_listings()
        listing = db["listings"].get(listing_id)
        if not listing or listing.get("status") != "active":
            await query.message.reply_text("این آگهی دیگر فعال نیست.")
            return
        if listing.get("seller_id") == user.id:
            await query.message.reply_text("این آگهی متعلق به خودتان است.")
            return
        text_msg = (f"🤝 درخواست واسطه‌گری خرید اکانت\nآگهی: #{listing_id}\nبازی: {listing['game']}\nلول: {listing['level']}\nقیمت: {money(listing['price'])}\nفروشنده ID: {listing['seller_id']}\nخریدار: {user.full_name} (ID: {user.id})\nیوزرنیم خریدار: @{user.username}" if user.username else f"🤝 درخواست واسطه‌گری خرید اکانت\nآگهی: #{listing_id}\nبازی: {listing['game']}\nلول: {listing['level']}\nقیمت: {money(listing['price'])}\nفروشنده ID: {listing['seller_id']}\nخریدار: {user.full_name} (ID: {user.id})\nخریدار یوزرنیم ندارد")
        sent = 0
        for admin_id in sorted(load_admin_ids()):
            try:
                await context.bot.send_message(chat_id=admin_id, text=text_msg)
                sent += 1
            except Exception:
                logger.exception("Could not notify marketplace support admin %s", admin_id)
        try:
            await context.bot.send_message(chat_id=listing["seller_id"], text=f"📩 برای آگهی #{listing_id} شما درخواست خرید ثبت شد. لطفاً تا هماهنگی پشتیبانی، اطلاعات ورود یا اکانت را تحویل ندهید.")
        except Exception:
            logger.exception("Could not notify marketplace seller")
        if sent:
            await query.message.reply_text("✅ درخواست شما ثبت شد و برای مدیریت ارسال شد؛ برای ادامه معامله منتظر پیام پشتیبانی بمانید. این ربات پرداخت امانی خودکار ندارد؛ تا تأیید شرایط، وجه یا اطلاعات ورود را ارسال نکنید.")
        else:
            await query.message.reply_text("⚠️ درخواست آماده شد، اما پیام به مدیریت ارسال نشد. لطفاً از بخش پشتیبانی به ما خبر دهید و فعلاً وجه یا اطلاعات ورود را ارسال نکنید.")
        return


async def setdiscount_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("دسترسی ندارید؛ فقط ادمین می‌تواند تخفیف را تغییر دهد.")
        return
    if len(context.args) != 1:
        await update.effective_message.reply_text(
            "فرمت: /setdiscount درصد\nمثال: /setdiscount 20\nبرای حذف تخفیف: /setdiscount 0"
        )
        return
    try:
        percent = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("درصد باید عدد صحیح بین ۰ تا ۱۰۰ باشد.")
        return
    if not 0 <= percent <= 100:
        await update.effective_message.reply_text("درصد تخفیف باید بین ۰ تا ۱۰۰ باشد.")
        return
    save_discount_percent(percent)
    if percent:
        await update.effective_message.reply_text(
            f"✅ تخفیف عمومی سرویس‌ها روی {percent}٪ تنظیم شد. قیمت‌های جدید در سفارش‌های بعدی اعمال می‌شوند."
        )
    else:
        await update.effective_message.reply_text("✅ تخفیف غیرفعال شد؛ قیمت‌ها به حالت عادی برگشتند.")


async def discount_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set or remove a discount for one customer only. /discount_user USER_ID PERCENT"""
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("⛔ این دستور فقط برای ادمین است.")
        return
    if len(context.args) != 2 or not context.args[0].isdigit() or not context.args[1].isdigit():
        await update.effective_message.reply_text(
            "فرمت دستور:\n/discount_user آیدی_مشتری درصد\n"
            "مثال: /discount_user 6278794309 20\n"
            "برای حذف تخفیف اختصاصی و برگشت به تخفیف عمومی: /discount_user 6278794309 0"
        )
        return
    user_id, percent = int(context.args[0]), int(context.args[1])
    if not 0 <= percent <= 100:
        await update.effective_message.reply_text("درصد باید بین ۰ تا ۱۰۰ باشد.")
        return
    save_user_discount_percent(user_id, percent)
    if percent:
        await update.effective_message.reply_text(
            f"✅ تخفیف اختصاصی {percent}٪ برای مشتری با آیدی {user_id} تنظیم شد.\n"
            "این تخفیف فقط برای سفارش‌های جدید این مشتری اعمال می‌شود."
        )
    else:
        await update.effective_message.reply_text(
            f"✅ تخفیف اختصاصی مشتری {user_id} حذف شد؛ از این پس تخفیف عمومی برای او اعمال می‌شود."
        )


async def discount_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("دسترسی ندارید.")
        return
    percent = load_discount_percent()
    await update.effective_message.reply_text(
        f"🏷 تخفیف فعلی: {percent}٪" if percent else "🏷 در حال حاضر تخفیفی فعال نیست."
    )


async def addadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only the primary admin configured in ADMIN_ID can grant/revoke admin access.
    if update.effective_user.id != ADMIN_ID:
        await update.effective_message.reply_text("فقط مدیر اصلی می‌تواند ادمین اضافه یا حذف کند.")
        return
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.effective_message.reply_text("فرمت: /addadmin آیدی_عددی\nمثال: /addadmin 123456789")
        return
    target_id = int(context.args[0])
    ids = load_admin_ids()
    if target_id in ids:
        await update.effective_message.reply_text("این کاربر از قبل ادمین است.")
        return
    ids.add(target_id)
    save_admin_ids(ids)
    await update.effective_message.reply_text(
        f"✅ ادمین اضافه شد: {target_id}\nبرای دریافت پیام‌های ربات، آن شخص باید ابتدا ربات را Start کند."
    )


async def removeadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.effective_message.reply_text("فقط مدیر اصلی می‌تواند ادمین اضافه یا حذف کند.")
        return
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.effective_message.reply_text("فرمت: /removeadmin آیدی_عددی")
        return
    target_id = int(context.args[0])
    if target_id == ADMIN_ID:
        await update.effective_message.reply_text("مدیر اصلی قابل حذف نیست.")
        return
    ids = load_admin_ids()
    if target_id not in ids:
        await update.effective_message.reply_text("این آیدی در فهرست ادمین‌ها نیست.")
        return
    ids.remove(target_id)
    save_admin_ids(ids)
    await update.effective_message.reply_text(f"✅ دسترسی ادمین {target_id} حذف شد.")


async def admin_panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Private, admin-only control panel. Never expose the keyboard to customers."""
    user = update.effective_user
    message = update.effective_message
    if not user or not is_admin(user.id):
        if message:
            await message.reply_text("⛔ این پنل فقط برای ادمین‌های مجاز است.")
        return
    await message.reply_text(
        "🛡 پنل مدیریت SpeedCon\n\n"
        "از گزینه‌ها برای مدیریت سرورها، تعرفه‌ها و وضعیت ربات استفاده کن.",
        reply_markup=admin_panel_markup(),
    )


def admin_panel_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖥 مدیریت پنل‌های سرور", callback_data="adminpanel:servers")],
        [InlineKeyboardButton("🧩 افزودن / ویرایش پلن‌ها", callback_data="adminpanel:plans")],
        [InlineKeyboardButton("💰 تغییر قیمت سرویس‌ها", callback_data="adminpanel:price_menu"), InlineKeyboardButton("📃 مشاهده تعرفه‌ها", callback_data="adminpanel:prices")],
        [InlineKeyboardButton("🏷 تخفیف اختصاصی مشتری", callback_data="adminpanel:discount_menu")],
        [InlineKeyboardButton("📣 ارسال پیام به همه اعضا", callback_data="adminpanel:broadcast_menu")],
        [InlineKeyboardButton("✉️ ارسال پیام به یک مشتری", callback_data="adminpanel:sendone_menu")],
        [InlineKeyboardButton("📦 سفارش‌های اخیر", callback_data="adminpanel:orders")],
        [InlineKeyboardButton("🔒 بستن همه پنل‌ها", callback_data="adminpanel:close_all"), InlineKeyboardButton("🔓 باز کردن همه پنل‌ها", callback_data="adminpanel:open_all")],
        [InlineKeyboardButton("🛠 فعال‌کردن حالت آپدیت", callback_data="adminpanel:update"), InlineKeyboardButton("🟢 آنلاین‌کردن ربات", callback_data="adminpanel:online")],
        [InlineKeyboardButton("📊 وضعیت فعلی", callback_data="adminpanel:sections")],
        [InlineKeyboardButton("👮 ادمین‌ها", callback_data="adminpanel:admins"), InlineKeyboardButton("✖️ بستن پنل", callback_data="adminpanel:close")],
    ])


def admin_servers_markup():
    settings = load_section_settings()
    rows = []
    for product, key in PANEL_SECTION_KEYS.items():
        closed = key in settings
        label = "🔓 بازکردن" if closed else "🔒 بستن"
        status = "🔴 بسته" if closed else "🟢 باز"
        rows.append([InlineKeyboardButton(f"{status} | {product}", callback_data=f"adminpanel:noop"),
                     InlineKeyboardButton(label, callback_data=f"adminpanel:toggle:{key}")])
    rows.append([InlineKeyboardButton("⬅️ بازگشت به پنل", callback_data="adminpanel:refresh")])
    return InlineKeyboardMarkup(rows)


def admin_price_markup():
    rows = []
    for product_index, (product, tiers) in enumerate(PRODUCTS.items()):
        for tier_index, (label, price) in enumerate(tiers):
            rows.append([InlineKeyboardButton(f"{product} | {label}: {money(price)} تومان", callback_data=f"adminpanel:price:{product_index}:{tier_index}")])
    rows.append([InlineKeyboardButton("⬅️ بازگشت به پنل", callback_data="adminpanel:refresh")])
    return InlineKeyboardMarkup(rows)


def admin_plan_products_markup():
    rows = []
    for i, product in enumerate(PRODUCTS):
        rows.append([InlineKeyboardButton(product, callback_data=f"adminpanel:plan_product:{i}")])
    rows.append([InlineKeyboardButton("⬅️ بازگشت به پنل", callback_data="adminpanel:refresh")])
    return InlineKeyboardMarkup(rows)


def admin_plan_tiers_markup(product_index):
    products = list(PRODUCTS.items())
    if not 0 <= product_index < len(products):
        return admin_plan_products_markup()
    product, tiers = products[product_index]
    rows = []
    for i, (label, price) in enumerate(tiers):
        rows.append([InlineKeyboardButton(f"✏️ نام: {label}", callback_data=f"adminpanel:plan_label:{product_index}:{i}"),
                     InlineKeyboardButton(f"💰 {money(price)} تومان", callback_data=f"adminpanel:plan_price:{product_index}:{i}")])
        rows.append([InlineKeyboardButton(f"🗑 حذف پلن «{label}»", callback_data=f"adminpanel:plan_delete:{product_index}:{i}")])
    rows.append([InlineKeyboardButton("➕ افزودن پلن به این سرویس", callback_data=f"adminpanel:plan_add:{product_index}")])
    rows.append([InlineKeyboardButton("⬅️ فهرست سرویس‌ها", callback_data="adminpanel:plans")])
    return InlineKeyboardMarkup(rows)


async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not is_admin(query.from_user.id):
        if query:
            await query.answer("این پنل فقط برای ادمین است.", show_alert=True)
        return
    await query.answer()
    action = query.data.split(":", 1)[1]

    if action == "plans":
        await query.edit_message_text("🧩 مدیریت پلن‌ها\n\nسرویسی را انتخاب کن تا پلن‌هایش را اضافه، ویرایش یا حذف کنی:", reply_markup=admin_plan_products_markup())
        return
    if action.startswith("plan_product:"):
        try:
            product_index = int(action.split(":")[1])
            product = list(PRODUCTS)[product_index]
        except (ValueError, IndexError):
            await query.edit_message_text("سرویس انتخاب‌شده معتبر نیست.", reply_markup=admin_plan_products_markup()); return
        await query.edit_message_text(f"🧩 پلن‌های سرویس\n{product}\n\nبرای تغییر نام یا مبلغ، دکمه مربوطه را بزن. برای پلن تازه، افزودن پلن را انتخاب کن.", reply_markup=admin_plan_tiers_markup(product_index))
        return
    if action.startswith("plan_add:"):
        try: product_index = int(action.split(":")[1]); product = list(PRODUCTS)[product_index]
        except (ValueError, IndexError):
            await query.edit_message_text("سرویس معتبر نیست.", reply_markup=admin_plan_products_markup()); return
        context.user_data["admin_plan_flow"] = {"stage": "add_label", "product": product}
        await query.edit_message_text(f"➕ افزودن پلن برای {product}\n\nنام پلن را بفرست؛ مثلاً «۱۰ گیگابایت» یا «۶ ماه». برای لغو بنویس: لغو")
        return
    if action.startswith("plan_label:") or action.startswith("plan_price:"):
        try:
            _, pi, ti = action.split(":")
            pi, ti = int(pi), int(ti)
            product = list(PRODUCTS)[pi]
            label, price = PRODUCTS[product][ti]
        except (ValueError, IndexError, KeyError):
            await query.edit_message_text("پلن معتبر نیست.", reply_markup=admin_plan_products_markup()); return
        if action.startswith("plan_label:"):
            context.user_data["admin_plan_flow"] = {"stage": "edit_label", "product": product, "tier_index": ti, "product_index": pi}
            prompt = f"✏️ نام جدید پلن را بفرست.\nفعلی: {label}\nبرای لغو بنویس: لغو"
        else:
            context.user_data["admin_plan_flow"] = {"stage": "edit_price", "product": product, "tier_index": ti, "product_index": pi}
            prompt = f"💰 مبلغ جدید پلن را به تومان فقط با عدد بفرست.\n{product} — {label}\nمبلغ فعلی: {money(price)} تومان\nبرای لغو بنویس: لغو"
        await query.edit_message_text(prompt)
        return
    if action.startswith("plan_delete:"):
        try:
            _, pi, ti = action.split(":"); pi, ti = int(pi), int(ti)
            product = list(PRODUCTS)[pi]
            if len(PRODUCTS[product]) <= 1:
                await query.answer("هر سرویس باید حداقل یک پلن داشته باشد.", show_alert=True); return
            removed = PRODUCTS[product].pop(ti)
            save_price_overrides()
            await query.edit_message_text(f"🗑 پلن «{removed[0]}» حذف شد.", reply_markup=admin_plan_tiers_markup(pi))
        except (ValueError, IndexError, KeyError):
            await query.edit_message_text("پلن معتبر نیست.", reply_markup=admin_plan_products_markup())
        return
    if action == "broadcast_menu":
        context.user_data["admin_broadcast_waiting"] = True
        context.user_data.pop("admin_sendone_target", None)
        await query.edit_message_text("📣 پیام همگانی\n\nمتن پیامی را که باید برای اعضای ثبت‌شده ربات ارسال شود بفرست. برای لغو بنویس: لغو")
        return
    if action == "sendone_menu":
        context.user_data["admin_sendone_stage"] = "user_id"
        context.user_data.pop("admin_sendone_target", None)
        await query.edit_message_text("✉️ ارسال پیام به یک مشتری\n\nابتدا آیدی عددی مشتری را بفرست. برای لغو بنویس: لغو")
        return
    if action == "broadcast_send":
        draft = context.user_data.pop("admin_broadcast_draft", None)
        if not draft:
            await query.edit_message_text("پیش‌نویس پیام پیدا نشد.", reply_markup=admin_panel_markup()); return
        user_ids = sorted(load_users()); success = failed = 0
        blocked = set(load_access_data().get("blocked_users", []))
        for user_id in user_ids:
            if user_id in blocked: continue
            try:
                await context.bot.send_message(chat_id=user_id, text=draft)
                success += 1
            except Exception:
                failed += 1
                logger.warning("Panel broadcast failed for %s", user_id)
            await asyncio.sleep(0.04)
        await query.edit_message_text(f"📣 ارسال همگانی تمام شد.\n👥 اعضای ثبت‌شده: {len(user_ids)}\n✅ موفق: {success}\n❌ ناموفق: {failed}", reply_markup=admin_panel_markup())
        return
    if action == "broadcast_cancel":
        context.user_data.pop("admin_broadcast_draft", None); context.user_data.pop("admin_broadcast_waiting", None)
        await query.edit_message_text("ارسال همگانی لغو شد.", reply_markup=admin_panel_markup()); return
    if action == "sendone_send":
        target = context.user_data.pop("admin_sendone_target", None)
        draft = context.user_data.pop("admin_sendone_draft", None)
        if not target or not draft:
            await query.edit_message_text("اطلاعات پیام کامل نیست.", reply_markup=admin_panel_markup()); return
        try:
            await context.bot.send_message(chat_id=int(target), text=draft)
            result = f"✅ پیام برای مشتری {target} ارسال شد."
        except Exception as exc:
            logger.warning("Panel direct message failed target=%s: %s", target, exc)
            result = "❌ پیام ارسال نشد؛ آیدی را بررسی کن و مطمئن شو مشتری قبلاً ربات را Start کرده است."
        await query.edit_message_text(result, reply_markup=admin_panel_markup()); return
    if action == "sendone_cancel":
        for k in ("admin_sendone_stage", "admin_sendone_target", "admin_sendone_draft"):
            context.user_data.pop(k, None)
        await query.edit_message_text("ارسال پیام لغو شد.", reply_markup=admin_panel_markup()); return

    if action == "noop":
        return
    if action == "close":
        try:
            await query.edit_message_text("پنل مدیریت بسته شد.", reply_markup=None)
        except Exception:
            pass
        return
    if action == "refresh":
        await query.edit_message_text("🛡 پنل مدیریت SpeedCon\n\nیک ابزار را انتخاب کن:", reply_markup=admin_panel_markup())
        return
    if action == "servers":
        await query.edit_message_text("🖥 مدیریت پنل‌های سرور\n\nوضعیت هر سرور را ببین و با دکمه کنارش باز یا بسته کن.", reply_markup=admin_servers_markup())
        return
    if action == "price_menu":
        await query.edit_message_text("💰 برای تغییر قیمت، سرویس و تعرفه موردنظر را انتخاب کن:", reply_markup=admin_price_markup())
        return
    if action == "discount_menu":
        context.user_data["admin_discount_stage"] = "user_id"
        context.user_data.pop("admin_discount_target", None)
        await query.edit_message_text(
            "🏷 تخفیف اختصاصی مشتری\n\n"
            "ابتدا آیدی عددی مشتری را بفرست.\n"
            "بعد از آن درصد تخفیف را می‌پرسم.\n\n"
            "برای حذف تخفیف اختصاصی، درصد ۰ را وارد کن. برای لغو بنویس: لغو",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="adminpanel:discount_cancel")]])
        )
        return
    if action == "discount_cancel":
        context.user_data.pop("admin_discount_stage", None)
        context.user_data.pop("admin_discount_target", None)
        await query.edit_message_text("تغییر تخفیف لغو شد.", reply_markup=admin_panel_markup())
        return
    if action.startswith("toggle:"):
        key = action.split(":", 1)[1]
        if key not in PANEL_SECTION_KEYS.values():
            await query.edit_message_text("⛔ بخش نامعتبر است.", reply_markup=admin_panel_markup())
            return
        settings = load_section_settings()
        if key in settings:
            settings.pop(key, None)
            status = "باز شد 🟢"
        else:
            settings[key] = {"message": "این پنل موقتاً بسته است. لطفاً بعداً دوباره تلاش کنید."}
            status = "بسته شد 🔒"
        save_section_settings(settings)
        await query.edit_message_text(f"✅ پنل {SECTION_NAMES.get(key, key)} {status}.", reply_markup=admin_servers_markup())
        return
    if action == "close_all":
        settings = load_section_settings()
        for key in PANEL_SECTION_KEYS.values():
            settings[key] = {"message": "پنل سرویس‌ها موقتاً در حال بروزرسانی است. لطفاً بعداً مراجعه کنید."}
        save_section_settings(settings)
        await query.edit_message_text("🔒 تمام پنل‌های سرور بسته شدند.", reply_markup=admin_panel_markup())
        return
    if action == "open_all":
        settings = load_section_settings()
        for key in PANEL_SECTION_KEYS.values():
            settings.pop(key, None)
        save_section_settings(settings)
        await query.edit_message_text("🔓 تمام پنل‌های سرور باز شدند.", reply_markup=admin_panel_markup())
        return
    if action.startswith("price:"):
        try:
            _, product_index, tier_index = action.split(":")
            product_index, tier_index = int(product_index), int(tier_index)
            product = list(PRODUCTS)[product_index]
            label, current_price = PRODUCTS[product][tier_index]
        except (ValueError, IndexError, KeyError):
            await query.edit_message_text("تعرفه انتخاب‌شده معتبر نیست.", reply_markup=admin_price_markup())
            return
        context.user_data["admin_price_edit"] = {"product": product, "tier_index": tier_index}
        await query.edit_message_text(
            f"✏️ تغییر قیمت\n\nسرویس: {product}\nتعرفه: {label}\nقیمت فعلی: {money(current_price)} تومان\n\nقیمت جدید را فقط با عدد به تومان بفرست. برای لغو بنویس: لغو",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو تغییر قیمت", callback_data="adminpanel:price_cancel")]])
        )
        return
    if action == "price_cancel":
        context.user_data.pop("admin_price_edit", None)
        await query.edit_message_text("تغییر قیمت لغو شد.", reply_markup=admin_panel_markup())
        return

    if action == "orders":
        db = load_db()
        orders = sorted(db.get("orders", {}).values(), key=lambda o: int(o.get("id", 0)), reverse=True)
        if not orders:
            result = "🗂 هنوز سفارشی ثبت نشده است."
        else:
            lines = [f"🗂 آخرین سفارش‌ها (حداکثر 15 مورد) | کل سفارش‌ها: {len(orders)}"]
            for order in orders[:15]:
                lines.append(f"#{order.get('order_number', order.get('id', '—'))} | مشتری {order.get('user_id', '—')} | {order.get('status', '—')} | {money(order.get('amount', 0))}")
            result = "\n".join(lines)
    elif action == "prices":
        lines = ["💰 تعرفه‌های فعلی:"]
        for product, tiers in PRODUCTS.items():
            lines.append("\n" + product)
            lines.extend(f"• {label}: {money(price)}" for label, price in tiers)
        result = "\n".join(lines)
    elif action == "update":
        data = load_access_data(); data["maintenance"] = True; save_access_data(data)
        result = "🛠 حالت آپدیت فعال شد؛ کاربران عادی پیام نگهداری می‌بینند."
    elif action == "online":
        data = load_access_data(); data["maintenance"] = False; save_access_data(data)
        result = "🟢 حالت آپدیت غیرفعال شد و ربات آنلاین است."
    elif action == "sections":
        data = load_section_settings()
        lines = ["📊 وضعیت فعلی ربات:", "حالت آپدیت: " + ("🔴 فعال" if load_access_data().get("maintenance") else "🟢 غیرفعال")]
        for key, name in SECTION_NAMES.items():
            lines.append(f"{'🔴 بسته' if key in data else '🟢 باز'} — {name}")
        result = "\n".join(lines)
    elif action == "admins":
        ids = sorted(load_admin_ids())
        result = "👮 ادمین‌های مجاز:\n" + "\n".join(f"{i}. {admin_id}" + (" (مدیر اصلی)" if admin_id == ADMIN_ID else "") for i, admin_id in enumerate(ids, 1))
    elif action == "broadcast":
        result = "📣 برای ارسال پیام همگانی دستور /broadcast متن پیام را در چت خصوصی ربات بفرست."
    elif action == "addadmin":
        result = "➕ افزودن ادمین دوم فقط توسط مدیر اصلی: /addadmin آیدی_عددی"
    else:
        result = "گزینه نامعتبر است."
    try:
        await query.edit_message_text(result, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بازگشت به پنل", callback_data="adminpanel:refresh")]]))
    except Exception:
        await query.message.reply_text(result, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بازگشت به پنل", callback_data="adminpanel:refresh")]]))


async def admins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("دسترسی ندارید.")
        return
    ids = sorted(load_admin_ids())
    lines = [f"{i}. {admin_id}" + (" (مدیر اصلی)" if admin_id == ADMIN_ID else "") for i, admin_id in enumerate(ids, 1)]
    await update.effective_message.reply_text("👮 فهرست ادمین‌ها:\n" + "\n".join(lines))


# ================= TELEGRAM BUSINESS SECRETARY =================
# Modes: auto (rules/FAQ), ai (requires a separate API key), hybrid (FAQ/rules then AI).
# Settings are stored separately so the existing orders.json is never overwritten.

def load_secretary_data():
    if not SECRETARY_FILE.exists():
        return {"connections": {}, "paused_chats": [], "faqs": [], "mode": "hybrid", "enabled": True, "history": {}}
    try:
        with SECRETARY_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("connections", {})
        data.setdefault("paused_chats", [])
        data.setdefault("faqs", [])
        data.setdefault("mode", "hybrid")
        data.setdefault("enabled", True)
        data.setdefault("history", {})
        return data
    except Exception:
        logger.exception("Could not read secretary_settings.json")
        raise RuntimeError("فایل secretary_settings.json خراب است؛ آن را حذف نکنید، ابتدا از آن نسخه پشتیبان بگیرید.")


def save_secretary_data(data):
    tmp = SECRETARY_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(SECRETARY_FILE)


def find_owner_connection(data, owner_id):
    matches = [c for c in data["connections"].values() if c.get("owner_id") == owner_id and c.get("is_enabled")]
    return matches[-1] if matches else None


def rule_answer(text, faqs):
    normalized = (text or "").strip().lower()
    for item in faqs:
        q = item.get("question", "").strip().lower()
        if q and (normalized == q or q in normalized):
            return item.get("answer", "")
    if any(x in normalized for x in ("سلام", "درود", "hello", "hi", "salam")):
        return "سلام، خوش اومدید 🌷 چطور می‌تونم کمکتون کنم؟"
    if any(x in normalized for x in ("قیمت", "تعرفه", "هزینه", "price", "cost")):
        return "برای اطلاع از تعرفه‌ها لطفاً نوع سرویس و حجم موردنظرتون رو بفرمایید تا راهنمایی‌تون کنیم."
    if any(x in normalized for x in ("خرید", "سفارش", "خریدن", "buy", "order")):
        return "برای ثبت سفارش لطفاً نوع سرویس و حجم موردنیازتون رو بفرمایید. اگر لازم باشه پشتیبانی ادامه کار رو پیگیری می‌کنه."
    if any(x in normalized for x in ("پشتیبانی", "ادمین", "انسان", "اپراتور", "support", "human")):
        return "پیامتون دریافت شد 🌷 در اولین فرصت توسط پشتیبانی بررسی می‌شه."
    if any(x in normalized for x in ("ممنون", "مرسی", "تشکر", "thanks", "thank you")):
        return "خواهش می‌کنم 🌹 هر سؤال دیگه‌ای داشتید در خدمتم."
    return None


def _call_ai_api(messages):
    if not OPENAI_API_KEY:
        return None
    payload = json.dumps({"model": OPENAI_MODEL, "messages": messages, "temperature": 0.6, "max_tokens": 500}).encode("utf-8")
    req = urllib.request.Request(
        OPENAI_BASE_URL,
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {OPENAI_API_KEY}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            result = json.loads(response.read().decode("utf-8"))
        return result["choices"][0]["message"]["content"].strip()
    except Exception:
        logger.exception("AI provider request failed")
        return None


async def ai_answer(data, history_key, customer_text):
    history = data["history"].get(history_key, [])
    messages = [{"role": "system", "content": (
        "تو منشی فارسی‌زبان و مؤدب یک کسب‌وکار هستی. کوتاه، دقیق و دوستانه پاسخ بده. "
        "قیمت، موجودی، پرداخت یا تحویل را جعل نکن. اگر مطمئن نیستی بگو پشتیبانی بررسی می‌کند. "
        "رمز، کد ورود یا اطلاعات بانکی حساس درخواست نکن. خودت را هوش مصنوعی معرفی کن اگر پرسیده شد."
    )}]
    messages.extend(history[-8:])
    messages.append({"role": "user", "content": customer_text[:3000]})
    answer = await asyncio.to_thread(_call_ai_api, messages)
    if answer:
        history.extend([{"role": "user", "content": customer_text[:1000]}, {"role": "assistant", "content": answer[:1500]}])
        data["history"][history_key] = history[-10:]
        save_secretary_data(data)
    return answer


async def business_connection_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    connection = update.business_connection
    if not connection:
        return
    data = load_secretary_data()
    previous = data["connections"].get(connection.id, {})
    data["connections"][connection.id] = {
        "owner_id": connection.user.id,
        "owner_name": connection.user.full_name,
        "user_chat_id": connection.user_chat_id,
        "is_enabled": bool(connection.is_enabled),
        "secretary_enabled": previous.get("secretary_enabled", True),
        "mode": previous.get("mode", "hybrid"),
        "rights": connection.rights.to_dict() if connection.rights else {},
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_secretary_data(data)
    try:
        status = "فعال شد" if connection.is_enabled else "قطع شد"
        await context.bot.send_message(
            chat_id=connection.user_chat_id,
            text=f"🔔 اتصال منشی تلگرام بیزینس {status}.\nبرای مدیریت تنظیمات از دستور /secretary استفاده کنید."
        )
    except Exception:
        logger.exception("Could not notify business account owner")


async def business_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.business_message
    if not message or not message.business_connection_id:
        return
    if message.chat.type != "private" or not message.text:
        return
    data = load_secretary_data()
    connection_id = message.business_connection_id
    connection = data["connections"].get(connection_id)
    if not connection or not connection.get("is_enabled") or not data.get("enabled", True) or not connection.get("secretary_enabled", True):
        return
    # Never auto-reply to messages sent by the connected account owner.
    if message.from_user and message.from_user.id == connection.get("owner_id"):
        return
    rights = connection.get("rights") or {}
    if not rights.get("can_reply", False):
        return
    pause_key = f"{connection_id}:{message.chat_id}"
    if pause_key in data.get("paused_chats", []):
        return

    text_value = message.text.strip()
    mode = connection.get("mode", data.get("mode", "hybrid"))
    answer = None
    if mode in ("auto", "hybrid"):
        answer = rule_answer(text_value, data.get("faqs", []))
    if not answer and mode in ("ai", "hybrid"):
        history_key = pause_key
        answer = await ai_answer(data, history_key, text_value)
    if not answer:
        answer = ("پیامتون رو دریافت کردم 🌷 برای اینکه اطلاعات اشتباه ندم، "
                  "موضوع رو برای پشتیبانی می‌فرستم تا بررسی کنه.")
    try:
        await context.bot.send_message(
            chat_id=message.chat_id,
            text=answer[:4000],
            business_connection_id=connection_id,
        )
    except Exception:
        logger.exception("Failed to send business reply")


async def secretary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = load_secretary_data()
    if not is_admin(user_id):
        conn = find_owner_connection(data, user_id)
        if not conn:
            await update.effective_message.reply_text(
                "هنوز حساب بیزینس شما به این منشی وصل نشده. ابتدا Telegram Premium و بخش Telegram Business را بررسی کنید و ربات را از قسمت Chatbots متصل کنید."
            )
            return
    await update.effective_message.reply_text(
        "🤖 پنل منشی تلگرام\n\n"
        f"وضعیت منشی: {'روشن' if (conn.get('secretary_enabled', True) if user_id != ADMIN_ID else data.get('enabled', True)) else 'خاموش'}\n"
        f"حالت: {(conn.get('mode', data.get('mode', 'hybrid')) if user_id != ADMIN_ID else data.get('mode', 'hybrid'))}\n"
        f"حساب‌های متصل: {sum(1 for c in data['connections'].values() if c.get('is_enabled'))}\n"
        f"پرسش‌وپاسخ‌های ذخیره‌شده: {len(data.get('faqs', []))}\n\n"
        "دستورها:\n/mode auto — پاسخ‌های خودکار و FAQ\n/mode ai — هوش مصنوعی (نیازمند API key جداگانه)\n/mode hybrid — ترکیبی\n/secretary_on — روشن کردن منشی\n/secretary_off — خاموش کردن منشی\n/faq_add سؤال | جواب — افزودن پاسخ آماده\n/faq_list — نمایش FAQها\n/faq_clear — پاک کردن همه FAQها\n/pause chat_id — توقف پاسخ خودکار یک گفتگو\n/resume chat_id — ادامه پاسخ خودکار\n\n"
        "مدیریت ادمین‌ها (فقط مدیر اصلی): /addadmin آیدی، /removeadmin آیدی، /admins\n\nنکته: دستورهای مدیریتی را در چت خصوصی خود ربات بفرستید."
    )


async def mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = load_secretary_data()
    conn = find_owner_connection(data, user_id)
    if not is_admin(user_id) and not conn:
        await update.effective_message.reply_text("ابتدا حساب Telegram Business خود را به ربات متصل کنید.")
        return
    if not context.args or context.args[0].lower() not in ("auto", "ai", "hybrid"):
        await update.effective_message.reply_text("استفاده: /mode auto یا /mode ai یا /mode hybrid")
        return
    mode = context.args[0].lower()
    if conn and not is_admin(user_id):
        # A connected account owner changes only their own secretary mode.
        conn["mode"] = mode
    else:
        data["mode"] = mode
    save_secretary_data(data)
    extra = "\nبرای حالت AI باید OPENAI_API_KEY جداگانه تنظیم شود؛ اشتراک تلگرام پریمیوم شامل API هوش مصنوعی نیست." if mode in ("ai", "hybrid") and not OPENAI_API_KEY else ""
    await update.effective_message.reply_text(f"✅ حالت منشی روی {mode} تنظیم شد.{extra}")


async def secretary_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = load_secretary_data()
    conn = find_owner_connection(data, user_id)
    is_on = update.effective_message.text.split()[0].split("@", 1)[0].endswith("_on")
    if not is_admin(user_id) and not conn:
        await update.effective_message.reply_text("ابتدا حساب Telegram Business خود را به ربات متصل کنید.")
        return
    if conn and not is_admin(user_id):
        conn["secretary_enabled"] = is_on
        state = conn["secretary_enabled"]
    else:
        data["enabled"] = is_on
        state = data["enabled"]
    save_secretary_data(data)
    await update.effective_message.reply_text("منشی روشن شد ✅" if state else "منشی خاموش شد ⏸️")


async def faq_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("این دستور فقط برای مدیر ربات است.")
        return
    raw = " ".join(context.args)
    if "|" not in raw:
        await update.effective_message.reply_text("فرمت: /faq_add سؤال | جواب\nمثال: /faq_add ساعت پاسخگویی؟ | هر روز از ۹ تا ۱۸")
        return
    question, answer = [part.strip() for part in raw.split("|", 1)]
    if not question or not answer:
        await update.effective_message.reply_text("سؤال و جواب نباید خالی باشند.")
        return
    data = load_secretary_data()
    data["faqs"].append({"question": question, "answer": answer})
    save_secretary_data(data)
    await update.effective_message.reply_text("✅ پرسش و پاسخ ذخیره شد.")


async def faq_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_secretary_data()
    if not is_admin(update.effective_user.id) and not find_owner_connection(data, update.effective_user.id):
        await update.effective_message.reply_text("دسترسی ندارید.")
        return
    faqs = data.get("faqs", [])
    if not faqs:
        await update.effective_message.reply_text("هنوز FAQ ثبت نشده است.")
        return
    lines = [f"{i}. {item['question']} → {item['answer']}" for i, item in enumerate(faqs, 1)]
    await update.effective_message.reply_text("📚 پرسش‌وپاسخ‌ها:\n" + "\n".join(lines)[:4000])


async def faq_clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("این دستور فقط برای مدیر ربات است.")
        return
    data = load_secretary_data()
    data["faqs"] = []
    save_secretary_data(data)
    await update.effective_message.reply_text("تمام پرسش‌وپاسخ‌های ذخیره‌شده پاک شدند.")


async def pause_resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("این دستور فقط برای مدیر ربات است.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("فرمت: /pause chat_id یا /resume chat_id\nبرای هر گفتگو باید chat_id عددی را داشته باشید.")
        return
    chat_id = int(context.args[0])
    data = load_secretary_data()
    conn = next((cid for cid, c in data["connections"].items() if c.get("is_enabled")), None)
    if not conn:
        await update.effective_message.reply_text("هیچ اتصال فعالی وجود ندارد.")
        return
    key = f"{conn}:{chat_id}"
    paused = set(data.get("paused_chats", []))
    if update.effective_message.text.startswith("/pause"):
        paused.add(key)
        message = "پاسخ خودکار برای این گفتگو متوقف شد."
    else:
        paused.discard(key)
        message = "پاسخ خودکار برای این گفتگو دوباره فعال شد."
    data["paused_chats"] = list(paused)
    save_secretary_data(data)
    await update.effective_message.reply_text(message)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled exception while processing update", exc_info=context.error)


async def post_init(application: Application):
    me = await application.bot.get_me()
    application.bot_data["bot_username"] = me.username or ""


def main():
    # Pydroid-friendly: if no token is configured, ask for it in the console.
    token = (BOT_TOKEN or "").strip()
    if not token or token == "PASTE_NEW_BOT_TOKEN_HERE":
        print("توکن جدید ربات را از @BotFather کپی کن و اینجا وارد کن.")
        print("توکن را در چت با هیچ‌کس به اشتراک نگذار؛ ورودی در کنسول نمایش داده می‌شود.")
        try:
            token = input("BOT_TOKEN: ").strip()
        except (EOFError, KeyboardInterrupt):
            raise SystemExit("ورودی توکن لغو شد.")
    if not token:
        raise SystemExit("توکن خالی است. فایل را دوباره اجرا کن و توکن جدید را وارد کن.")
    if ":" not in token or len(token) < 30:
        raise SystemExit("فرمت توکن درست به نظر نمی‌رسد. توکن کامل را از API Token در @BotFather کپی کن؛ فاصله یا کوتیشن اضافه نداشته باشد.")
    try:
        app = Application.builder().token(token).post_init(post_init).build()
    except Exception as exc:
        raise SystemExit(f"ساخت ربات ناموفق بود: {exc}. نسخه کتابخانه را بررسی کن.")

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler(["senduser", "send_user"], senduser_command))
    app.add_handler(CommandHandler("block", block_command))
    app.add_handler(CommandHandler("unblock", unblock_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("update", update_command))
    app.add_handler(CommandHandler("online", online_command))
    app.add_handler(CommandHandler("addadmin", addadmin_command))
    app.add_handler(CommandHandler("removeadmin", removeadmin_command))
    app.add_handler(CommandHandler("admins", admins_command))
    app.add_handler(CommandHandler("admin", admin_panel_command))
    app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern=r"^adminpanel:(orders|prices|update|online|sections|admins|broadcast|addadmin|refresh|close|servers|price_menu|discount_menu|discount_cancel|close_all|open_all|noop|toggle:(gaming|v2ray|unlimited)|price_cancel|price:\d+:\d+|plans|plan_product:\d+|plan_add:\d+|plan_label:\d+:\d+|plan_price:\d+:\d+|plan_delete:\d+:\d+|broadcast_menu|broadcast_send|broadcast_cancel|sendone_menu|sendone_send|sendone_cancel)$"))
    app.add_handler(CommandHandler("setdiscount", setdiscount_command))
    app.add_handler(CommandHandler("discount_user", discount_user_command))
    app.add_handler(CommandHandler("discount", discount_command))
    app.add_handler(CommandHandler("secretary", secretary_command))
    app.add_handler(CommandHandler("mode", mode_command))
    app.add_handler(CommandHandler("secretary_on", secretary_toggle, has_args=False))
    app.add_handler(CommandHandler("secretary_off", secretary_toggle, has_args=False))
    app.add_handler(CommandHandler("faq_add", faq_add_command))
    app.add_handler(CommandHandler("faq_list", faq_list_command))
    app.add_handler(CommandHandler("faq_clear", faq_clear_command))
    app.add_handler(CommandHandler("pause", pause_resume_command))
    app.add_handler(CommandHandler("resume", pause_resume_command))
    app.add_handler(CommandHandler("orders", admin_orders))
    app.add_handler(CommandHandler("sendconfig", sendconfig_command))
    app.add_handler(CommandHandler("wallet_add", wallet_admin_command))
    app.add_handler(CallbackQueryHandler(wallet_callback, pattern=r"^wallet:"))
    app.add_handler(CommandHandler("test_add", test_add_command))
    app.add_handler(CommandHandler("test_list", test_list_command))
    app.add_handler(CommandHandler("section_close", section_close_command))
    app.add_handler(CommandHandler("section_open", section_open_command))
    app.add_handler(CommandHandler("sections", sections_command))
    app.add_handler(CallbackQueryHandler(global_back_callback, pattern=r"^global_back$"))
    app.add_handler(CallbackQueryHandler(test_request_callback, pattern=r"^test:request$"))
    app.add_handler(CallbackQueryHandler(cancel_active_order_callback, pattern=r"^cancel_active_order:\d+$"))
    app.add_handler(CallbackQueryHandler(panel_callback, pattern=r"^(panel:\d+|back|back_to_panels|product:\d+)$"))
    app.add_handler(CallbackQueryHandler(order_callback, pattern=r"^(confirm_order|cancel_order)$"))
    app.add_handler(CallbackQueryHandler(my_service_callback, pattern=r"^myservice:\d+$"))
    app.add_handler(CallbackQueryHandler(service_info_callback, pattern=r"^service_info:\d+$"))
    app.add_handler(CallbackQueryHandler(service_info_callback, pattern=r"^service_info:\d+$"))
    app.add_handler(CallbackQueryHandler(my_service_callback, pattern=r"^service_info:\d+$"))
    app.add_handler(CallbackQueryHandler(my_services_page_callback, pattern=r"^myservices_page:\d+$"))
    app.add_handler(CallbackQueryHandler(renew_service_callback, pattern=r"^renew_service:\d+$"))
    app.add_handler(CallbackQueryHandler(order_action_callback, pattern=r"^order_action:(send|reject):\d+$"))
    app.add_handler(CallbackQueryHandler(review_callback, pattern=r"^review:(approve|reject):\d+$"))
    app.add_handler(CallbackQueryHandler(support_reply_callback, pattern=r"^support_reply:\d+$"))
    app.add_handler(CallbackQueryHandler(start_config_delivery_callback, pattern=r"^config_start:\d+$"))
    # Legacy confirmation callback removed: config is now sent directly after selection.
    app.add_handler(CallbackQueryHandler(market_callback, pattern=r"^market:"))
    app.add_handler(CallbackQueryHandler(virtual_service_callback, pattern=r"^virtual:\d+$"))
    app.add_handler(MessageHandler(filters.PHOTO, market_photo_input))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.ALL, handle_config_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_text))
    # Telegram Business updates are separate from normal bot-chat updates.
    app.add_handler(TypeHandler(Update, business_connection_update), group=1)
    app.add_handler(TypeHandler(Update, business_message_handler), group=2)
    app.add_error_handler(error_handler)

    print("Bot is running. Stop with Ctrl+C or the stop button in Pydroid.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
