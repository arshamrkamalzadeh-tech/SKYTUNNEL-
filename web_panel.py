import os
import re
import json
import hmac
import string
import hashlib
import secrets
import html as html_lib
import time
import threading
from datetime import datetime, timedelta, timezone
from functools import wraps

import requests
import turso_serverless
from flask import Flask, request, session, redirect, url_for, flash, get_flashed_messages, abort

try:
    from zoneinfo import ZoneInfo
    TEHRAN = ZoneInfo("Asia/Tehran")
except Exception:                      # بعضی ایمیج‌های سبک tzdata ندارن
    TEHRAN = timezone(timedelta(hours=3, minutes=30))

# ---------------------------------------------------------------------------
# تنظیمات (از Environment Variables می‌خونه، دقیقاً هم‌نام با bot.py)
# ---------------------------------------------------------------------------

TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "libsql://skytunnel-mikekamalzadeh-sys.aws-eu-west-1.turso.io")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3ODkwNzE5MDcsImlkIjoiMDFhMDhjZmQtMmMwMS03YWViLTlmYzQtOWYzMTkwNzEwMjA0Iiwia2lkIjoiNmltOXd5bGxUd2luNkVHWEJWNHVJUE01ZWNPM2JyZmJ3NzFqWTFIanFCTSIsInJpZCI6ImU5N2NmZmQwLTgxZDYtNDA3Yi1hZGQ4LTEzMTRjY2MyZTkxYyJ9.tZj3mmc_tNCVRPsLkwuWdrGsXZXmFCcvRCEPcN0iclAMk0QrHWfZxZiGqB5otvhlZaT9fs_WzsO6kTS_gnk1Bw")

BOT_TOKEN = os.getenv("BOT_TOKEN", "70578965:nZ8qtHO0j8BTSEcAghcWvq75m_-2PLEZVw8")
BASE_URL = "https://api.splus.ir/bot" + BOT_TOKEN

PANEL_USERNAME = os.getenv("PANEL_USERNAME", "admin")
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "change-me-please")
_DEFAULT_SECRET_KEY = "x7Kp9mZq2vLwR4tYbN8jFcH1"
SECRET_KEY = os.getenv("SECRET_KEY", _DEFAULT_SECRET_KEY)
INSECURE_DEFAULTS = (PANEL_PASSWORD == "change-me-please") or (SECRET_KEY == _DEFAULT_SECRET_KEY)

# مقادیر پیش‌فرض (fallback) قیمت/کارت/حداقل شارژ — دقیقاً هم‌نام با کلیدهایی
# که bot.py هم به‌عنوان fallback استفاده می‌کنه. مقدار واقعی و قابل‌تغییر از
# صفحه‌ی «تنظیمات ربات» همین پنل ذخیره می‌شه و چون جدول settings بین این پنل و
# bot.py مشترکه، تغییر از اینجا فوراً روی خود ربات هم اثر می‌ذاره.
DEFAULT_PRICE_PER_GB_WIREGUARD = os.getenv("PRICE_PER_GB_WIREGUARD", "3500")
DEFAULT_PRICE_PER_GB_CONFIG = os.getenv("PRICE_PER_GB_CONFIG", "3500")
DEFAULT_PRICE_PER_GB_BOTH = os.getenv("PRICE_PER_GB_BOTH", "5500")
DEFAULT_PRICE_PER_GB_OPENVPN = os.getenv("PRICE_PER_GB_OPENVPN", "4000")
DEFAULT_PRICE_PER_GB_DNS = os.getenv("PRICE_PER_GB_DNS", "4000")
DEFAULT_CARD_NUMBER = os.getenv("CARD_NUMBER", "6219861957006504")
DEFAULT_CARD_OWNER = os.getenv("CARD_OWNER", "کمالزاده")
DEFAULT_MIN_TOPUP = os.getenv("MIN_TOPUP", "10000")

DEFAULT_DONITO_PAGE_URL = os.getenv("DONITO_PAGE_URL", "https://donito.me/skytunnel")
DEFAULT_RESELLER_PANEL_URL = os.getenv("RESELLER_PANEL_URL", "https://web-production-bfd2e.up.railway.app")

# هر آیتم: (کلید settings، عنوان، مقدار پیش‌فرض، نوع). نوع: number | float | text | url | tiers
# ⚠️ پیش‌فرض‌ها باید با fallback های bot.py یکی باشن. خالی‌گذاشتن فیلد = برگشت به پیش‌فرض.
CONFIG_GROUPS = [
    ("💰 قیمت‌گذاری و اطلاعات پرداخت", [
        ("price_wireguard", "قیمت هر گیگ — فقط وایرگارد (تومان)", DEFAULT_PRICE_PER_GB_WIREGUARD, "number"),
        ("price_config", "قیمت هر گیگ — فقط کانفیگ (تومان)", DEFAULT_PRICE_PER_GB_CONFIG, "number"),
        ("price_both", "قیمت هر گیگ — هر دو (تومان)", DEFAULT_PRICE_PER_GB_BOTH, "number"),
        ("price_openvpn", "قیمت هر گیگ — فقط OpenVPN (تومان)", DEFAULT_PRICE_PER_GB_OPENVPN, "number"),
        ("price_dns", "قیمت هر گیگ — فقط DNS بازی (تومان)", DEFAULT_PRICE_PER_GB_DNS, "number"),
        ("card_number", "شماره کارت", DEFAULT_CARD_NUMBER, "text"),
        ("card_owner", "نام صاحب کارت", DEFAULT_CARD_OWNER, "text"),
        ("min_topup", "حداقل مبلغ شارژ کارت‌به‌کارت — ریالی (تومان)", DEFAULT_MIN_TOPUP, "number"),
        ("min_topup_crypto", "حداقل مبلغ شارژ با رمزارز (تومان) — روی معادل تومانیِ مقداری که کاربر اعلام می‌کنه چک می‌شه", DEFAULT_MIN_TOPUP, "number"),
        ("min_topup_donito", "حداقل مبلغ شارژ ریالی خودکار — دونیتو (تومان)", DEFAULT_MIN_TOPUP, "number"),
        ("donito_page_url", "آدرس صفحه‌ی دونیت (لینکی که ربات به کاربر می‌ده)", DEFAULT_DONITO_PAGE_URL, "url"),
        ("donito_window_min", "مدت اعتبار هر درخواست شارژ دونیتو (دقیقه) — بعد از این مدت پرداخت دیگه تطبیق داده نمی‌شه", "180", "number"),
        ("donito_poll_sec", "هر چند ثانیه یک‌بار دونیت‌ها چک بشن (حداقل ۱۰)", "20", "number"),
        ("crypto_auto_confirm", "تأیید خودکار واریز رمزارز||روشن باشه: کاربر مقدار واریزی (مثلاً 0.2 TON) رو تو بات می‌نویسه؛ اگه همون مقدار (با اختلاف خیلی کم) تو حساب نوبیتکس خودت پیدا بشه، یا هشی که کاربر می‌فرسته با یه واریز بخوره و کوین/مقدارش درست باشه، شارژ خودکار تأیید می‌شه. اگه چند کاربر مقدار هم‌اندازه اعلام کنن، فقط با هش یا تأیید دستی ادمین. بات هیچ‌وقت خودش رد نمی‌کنه؛ رد کردن فقط با ادمینه", "0", "toggle"),
        ("crypto_max_shortfall_toman", "حداکثر کسریِ مجاز واریز رمزارز نسبت به مقدار مورد انتظار (تومان). مثلاً 6000 یعنی تا ۶ هزار تومان کمتر هم خودکار تأیید می‌شه", "6000", "number"),
        ("topup_multiplier", "ضریب واریزی (مثلاً 2 یعنی دو برابر مبلغ واریزی به کیف پول اضافه شود)", "1", "float"),
    ]),
    ("🧪 تست رایگان و خرید", [
        ("trial_gb", "حجم تست رایگان (گیگ — اعشاری مجاز، مثل 0.1)", "0.1", "float"),
        ("trial_days", "مدت تست رایگان (روز)", "1", "number"),
        ("trial_label", "پیشوند اسم کانفیگ تست رایگان — شماره‌ی ترتیبی خودکار بهش اضافه می‌شه (مثلاً FREE-TEST-1، FREE-TEST-2، ...)", "FREE-TEST", "text"),
        ("trial_max_per_user", "حداکثر تعداد تست رایگان برای هر کاربر (0 = نامحدود)", "1", "number"),
        ("trial_cooldown_hours", "حداقل فاصله‌ی بین دو تست رایگان یک کاربر (ساعت — اعشاری مجاز؛ 0 = بدون فاصله)", "0", "float"),
        ("trial_new_users_only", "تست رایگان فقط برای کاربرانی که هنوز خرید نکرده‌اند||روشن باشه: کسی که قبلاً حتی یک خرید داشته، دیگه تست نمی‌گیره", "0", "toggle"),
        ("trial_proto", "نوع سرویس تست رایگان — یکی از: both (هر دو) / xray (فقط کانفیگ) / wireguard / openvpn / dns", "both", "text"),
        ("default_gb", "حجم پیش‌فرض صفحه‌ی خرید (گیگ)", "1", "number"),
        ("default_days", "مدت پیش‌فرض صفحه‌ی خرید (روز)", "30", "number"),
        ("refund_ratio", "نسبت بازگشت وجه هنگام حذف کانفیگ (بین 0 تا 1؛ مثلاً 0.5 یعنی نصف ارزش باقی‌مانده)", "0.5", "float"),
    ]),
    ("🏪 فروشندگی (پنل فروشنده)", [
        ("reseller_panel_url", "آدرس پنل فروشندگی — فقط وقتی سرویس آدرس نداد به‌عنوان جایگزین نشون داده می‌شه. متن‌ها و دکمه‌های این بخش: منوی «متن‌ها» ← گروه «🏪 فروشندگی»", DEFAULT_RESELLER_PANEL_URL, "url"),
    ]),
    ("🎁 دعوت دوستان (رفرال)", [
        ("referral_enabled", "سیستم دعوت دوستان", "0", "toggle"),
        ("referral_reward_inviter", "پاداش دعوت‌کننده — به کیف پولش اضافه می‌شه (تومان)", "10000", "number"),
        ("referral_reward_invitee", "هدیه‌ی کاربر دعوت‌شده — به کیف پول خودش اضافه می‌شه (تومان؛ 0 = بدون هدیه)", "0", "number"),
        ("referral_require_channel", "پاداش فقط بعد از عضویت کاربر دعوت‌شده در کانال(های) اجباری||روشن باشه: تا وقتی کاربر دعوت‌شده عضو همه‌ی کانال‌های عضویت اجباری نشده، به دعوت‌کننده پاداشی داده نمی‌شه؛ بعد از عضویت و اولین بار که شرط پاداش پیش بیاد پرداخت می‌شه. اگه عضویت اجباری خاموش یا بدون کانال باشه، شرطی اعمال نمی‌شه", "1", "toggle"),
        ("referral_on_join", "پرداخت پاداش به‌محض ورود کاربر دعوت‌شده||خاموش = بعد از اولین خرید کاربر دعوت‌شده؛ روشن = به‌محض ورود به ربات", "0", "toggle"),
    ]),
    ("📲 لینک‌های دانلود اپ", [
        ("app_link_android", "لینک اندروید", os.getenv("APP_LINK_ANDROID", "https://play.google.com/store/apps/details?id=com.v2pro.client"), "url"),
        ("app_link_ios", "لینک iOS", os.getenv("APP_LINK_IOS", "https://apps.apple.com/us/app/v2pro/id6801607092"), "url"),
        ("app_link_windows", "لینک ویندوز", os.getenv("APP_LINK_WINDOWS", "https://su.randomatic.ir/v2pro/1.1.2/V2Pro-Setup-x64.exe"), "url"),
        ("app_link_mac", "لینک مک", os.getenv("APP_LINK_MAC", "https://su.randomatic.ir/v2pro/1.1.2/v2pro-macos-universal.zip"), "url"),
        ("app_link_linux", "لینک لینوکس", os.getenv("APP_LINK_LINUX", "https://su.randomatic.ir/v2pro/1.1.2/v2pro-linux-x64.tar.gz"), "url"),
    ]),
    ("🛠 مدیریت و نگهداری ربات", [
        ("admin_id", "آیدی عددی ادمین (تیکت‌ها و رسیدهای شارژ برای این آیدی میاد)", os.getenv("ADMIN_ID", "48985781"), "number"),
        ("maintenance_text", "پیامی که تو «حالت تعمیر» به کاربران نشون داده می‌شه",
         "🛠 ربات موقتاً در حال بروزرسانی است. لطفاً کمی بعد دوباره تلاش کنید.", "text"),
    ]),
    ("⚙️ تنظیمات پیشرفته ربات (بدون نیاز به ری‌استارت)", [
        ("bot_username", "یوزرنیم ربات برای لینک دعوت (بدون @)", os.getenv("BOT_USERNAME", "SKYTUNNELbot"), "text"),
        ("gate_enabled", "عضویت اجباری کانال||خاموش = هیچ‌کس برای استفاده از ربات مجبور به عضویت نیست (کانال‌ها از داخل خود ربات، دکمه‌ی ادمین، مدیریت می‌شن)", "1", "toggle"),
        ("gate_fail_open", "اگه چک عضویت جواب نداد، کاربر رد بشه||روشن = وقتی اکانت گیت وصل نیست یا چک خطا داد، کاربر وارد ربات می‌شه؛ خاموش = تا چک موفق نشه وارد نمی‌شه", "1", "toggle"),
        ("gate_cache_ttl", "مدت اعتبار عضویتِ تاییدشده (ثانیه، حداقل 5)", "60", "number"),
        ("gate_sync_interval", "فاصله‌ی تازه‌سازی لیست اعضای کانال (ثانیه، حداقل 5؛ عدد کمتر = فشار بیشتر روی API سروش)", "30", "number"),
        ("divider", "خط جداکننده‌ی پیام‌های ربات", "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄", "text"),
    ]),
    ("⌨️ توضیح دستورات منوی «/» (تا ~۱ دقیقه بعد روی تلگرام اعمال می‌شه)", [
        ("cmd_start", "/start", "🏠 شروع و منوی اصلی", "text"),
        ("cmd_buy", "/buy", "🛍 خرید کانفیگ", "text"),
        ("cmd_test", "/test", "🧪 تست رایگان", "text"),
        ("cmd_wallet", "/wallet", "💠 شارژ کیف پول", "text"),
        ("cmd_myconfigs", "/myconfigs", "🗂 کانفیگ‌های من", "text"),
        ("cmd_delconfig", "/delconfig", "🗑 حذف کانفیگ", "text"),
        ("cmd_account", "/account", "👤 حساب من", "text"),
        ("cmd_support", "/support", "🎧 پشتیبانی", "text"),
        ("cmd_guide", "/guide", "📲 اپ مخصوص کانفیگ‌ها", "text"),
        ("cmd_invite", "/invite", "🎁 دعوت دوستان", "text"),
    ]),
]
# نسخه‌ی تخت برای اعتبارسنجی/ذخیره
TOGGLE_DEFAULTS = {k: default for _title, items in CONFIG_GROUPS for k, _l, default, kind in items if kind == "toggle"}
CONFIG_SETTINGS = [(k, label, default, kind) for _title, items in CONFIG_GROUPS for k, label, default, kind in items]

# (متن‌های ربات از «رجیستری» که خود bot.py موقع استارت تو دیتابیس می‌نویسه خونده می‌شن؛ صفحه‌ی /texts)

# متن دکمه‌های منوی اصلی: (کلید داخلی ثابت, عنوان تو پنل, متن پیش‌فرض دکمه)
BOT_BUTTONS = [
    ("buy", "دکمه‌ی خرید کانفیگ", "🛍 خرید کانفیگ"),
    ("trial", "دکمه‌ی تست رایگان", "🧪 تست رایگان"),
    ("topup", "دکمه‌ی شارژ کیف پول", "💠 شارژ کیف پول"),
    ("exchange", "دکمه‌ی صرافی", "💱 صرافی"),
    ("account", "دکمه‌ی حساب من", "👤 حساب من"),
    ("myconfigs", "دکمه‌ی کانفیگ‌های من", "🗂 کانفیگ‌های من"),
    ("delete", "دکمه‌ی حذف کانفیگ", "🗑 حذف کانفیگ"),
    ("support", "دکمه‌ی پشتیبانی", "🎧 پشتیبانی"),
    ("guide", "دکمه‌ی اپ مخصوص کانفیگ‌ها", "📲 اپ مخصوص کانفیگ‌ها"),
    ("language", "دکمه‌ی تغییر زبان", "🌐 تغییر زبان"),
    ("reseller", "دکمه‌ی دریافت پنل فروشندگی", "🏪 دریافت پنل فروشندگی"),
    ("referral", "دکمه‌ی دعوت دوستان", "🎁 دعوت دوستان"),
]
MAIN_MENU_KEYS = [key for key, _label, _default in BOT_BUTTONS]

# دکمه‌های صفحه‌ی «انتخاب نوع سرویس» (همون‌جایی که موقع خرید، وایرگارد/کانفیگ/
# هر دو/OpenVPN رو انتخاب می‌کنید). کلیدها دقیقاً باید با CONFIG_TYPES خودِ
# bot.py یکی باشن، چون هم اسم دکمه (ctype_label_<key>) و هم ترتیبش
# (menu_order_buytypes) از همین جدول settings مشترک خونده می‌شه.
CONFIG_TYPE_BUTTONS = [
    ("wireguard", "دکمه‌ی «فقط وایرگارد»", "🔒 فقط وایرگارد"),
    ("config", "دکمه‌ی «فقط کانفیگ»", "⚙️ فقط کانفیگ"),
    ("both", "دکمه‌ی «هر دو»", "🔀 هر دو"),
    ("openvpn", "دکمه‌ی «فقط OpenVPN»", "📱 فقط OpenVPN"),
    ("dns", "دکمه‌ی «فقط DNS بازی»", "🎮 فقط DNS بازی"),
]
CONFIG_TYPE_KEYS = [key for key, _label, _default in CONFIG_TYPE_BUTTONS]


def get_ordered_keys(setting_key, default_keys, settings_dict=None):
    """ترتیب فعلی یه گروه دکمه رو از جدول settings برمی‌گردونه. هر کلیدی که
    قبلاً ذخیره نشده (یا نامعتبره) رو نادیده می‌گیره و هر کلید جدیدی که تازه
    به default_keys اضافه شده رو ته لیست می‌چسبونه، تا اضافه‌شدن یه دکمه‌ی جدید
    تو کد هیچ‌وقت باعث گم‌شدنش تو پنل نشه. اگه settings_dict (خروجی
    get_all_settings) داده بشه، از همون خونده می‌شه و کوئری‌ی جدا به دیتابیس
    زده نمی‌شه."""
    if settings_dict is not None:
        raw = settings_dict.get(setting_key, ",".join(default_keys))
    else:
        raw = get_setting(setting_key, ",".join(default_keys))
    order = [k.strip() for k in raw.split(",") if k.strip()]
    order = [k for k in order if k in default_keys]
    for k in default_keys:
        if k not in order:
            order.append(k)
    return order

app = Flask(__name__)
app.secret_key = SECRET_KEY

FEATURES = {
    "buy": "🛍 خرید کانفیگ",
    "trial": "🧪 تست رایگان",
    "topup": "💠 شارژ کیف پول",
    "exchange": "💱 صرافی (محاسبه‌ی خرید ارز)",
    "delete_config": "🗑 حذف کانفیگ",
    "support": "🎧 پشتیبانی",
    "reseller": "🏪 دریافت پنل فروشندگی",
    "guide": "📲 اپ مخصوص کانفیگ‌ها",
}

USERS_PAGE_SIZE = 20

SESSION = requests.Session()


def esc(value):
    """escape برای هر مقداری که از کاربر/دیتابیس تو HTML پنل چاپ می‌شه."""
    return html_lib.escape('' if value is None else str(value), quote=True)


# ---------------------------------------------------------------------------
# دیتابیس (همون Turso که bot.py و admin_sky_bot.py استفاده می‌کنن)
# ---------------------------------------------------------------------------

_db_local = threading.local()


def get_conn():
    conn = getattr(_db_local, "conn", None)
    if conn is None:
        conn = turso_serverless.connect(TURSO_DATABASE_URL, auth_token=TURSO_AUTH_TOKEN)
        conn.close = lambda: None
        _db_local.conn = conn
    return conn


def reset_conn():
    _db_local.conn = None


def with_db_retry(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            msg = str(e).lower()
            if "stream not found" in msg or "stream_expired" in msg or ("404" in msg and "stream" in msg):
                reset_conn()
                return func(*args, **kwargs)
            raise
    return wrapper


@with_db_retry
def ensure_settings_table():
    conn = get_conn()
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()


@with_db_retry
def get_setting(key, default="1"):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    res = c.fetchone()
    conn.close()
    return res[0] if res else default


@with_db_retry
def get_all_settings():
    """کل جدول settings رو با یه کوئری می‌خونه و به‌صورت dict برمی‌گردونه.
    صفحاتی مثل «تنظیمات ربات» یا «متن‌ها و ظاهر ربات» ده‌ها مقدار جدا از هم
    لازم دارن؛ قبلاً هرکدوم یه get_setting() جدا صدا می‌زدن که یعنی هرکدوم یه
    رفت‌وبرگشت شبکه‌ی جدا به دیتابیس بود (روی دیتابیس سرورلس مثل Turso این
    خیلی کند می‌شه، چون هر رفت‌وبرگشت خودش تاخیر داره). این تابع همون کار رو
    با یه رفت‌وبرگشت انجام می‌ده."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT key, value FROM settings")
    rows = c.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}


@with_db_retry
def set_setting(key, value):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


@with_db_retry
def delete_setting(key):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM settings WHERE key=?", (key,))
    conn.commit()
    conn.close()


@with_db_retry
def load_text_registry():
    """لیست متن‌های پیش‌فرض بات (که خود bot.py موقع استارت تو جدول bot_registry می‌نویسه)."""
    conn = get_conn()
    c = conn.cursor()
    row = None
    try:
        c.execute("SELECT value FROM bot_registry WHERE name='texts'")
        row = c.fetchone()
    except Exception as e:
        msg = str(e).lower()
        if "stream" in msg:  # بذار with_db_retry هندلش کنه
            raise
    conn.close()
    if not row or not row[0]:
        return None
    try:
        return json.loads(row[0])
    except ValueError:
        return None


def template_fields(text):
    """اسم placeholder های یه قالب {…}. اگه آکولادها خراب باشن ValueError می‌ده."""
    fields = []
    for _lit, field, _spec, _conv in string.Formatter().parse(text):
        if field is not None:
            fields.append(field)
    return fields


def validate_template(value, allowed):
    """None اگه قالب سالمه، وگرنه پیام خطای فارسی. جلوی دو مشکل رو می‌گیره: placeholder
    ناشناخته (که بات رو مجبور می‌کنه بی‌صدا متن پیش‌فرض رو نشون بده) و تگ HTML بسته‌نشده
    (که تلگرام پیام رو رد می‌کنه)."""
    try:
        fields = template_fields(value)
    except ValueError:
        return "آکولاد { } ناقص یا اشتباهه (برای نمایش خودِ آکولاد از {{ و }} استفاده کنید)"
    if "" in fields:
        return "آکولاد خالی {} مجاز نیست؛ داخلش اسم placeholder بنویسید"
    base = {f.split(".")[0].split("[")[0] for f in fields}
    bad = base - set(allowed)
    if bad:
        return "placeholder ناشناخته: " + " ".join("{" + b + "}" for b in sorted(bad))
    for tag in ("b", "strong", "i", "em", "u", "s", "code", "pre", "a", "blockquote"):
        opens = len(re.findall(r"<%s(?:\s[^>]*)?>" % tag, value))
        closes = len(re.findall(r"</%s>" % tag, value))
        if opens != closes:
            return "تگ <%s> درست بسته نشده" % tag
    return None


def validate_tiers(raw):
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return "حداقل یک پله لازمه"
    for p in parts:
        if ":" not in p:
            return f"پله‌ی «{p}» قالب درست نداره (سقف:قیمت)"
        lim, rate = (x.strip() for x in p.split(":", 1))
        if not rate.isdigit():
            return f"قیمت در «{p}» باید عدد باشه"
        if lim != "*" and not lim.isdigit():
            return f"سقف در «{p}» باید عدد یا * باشه"
    return None


def normalize_setting(kind, raw):
    """(مقدار نرمال‌شده, پیام خطا). برای نوع‌های number/float/url/tiers/text."""
    if kind == "number":
        try:
            return str(max(0, int(float(raw)))), None
        except ValueError:
            return None, "باید عدد صحیح باشه"
    if kind == "float":
        try:
            return "%g" % max(0.0, float(raw)), None
        except ValueError:
            return None, "باید عدد باشه (اعشاری هم مجازه)"
    if kind == "url":
        if not re.match(r"^https?://\S+$", raw):
            return None, "باید با http:// یا https:// شروع بشه"
        return raw, None
    if kind == "tiers":
        err = validate_tiers(raw)
        return (None, err) if err else (raw.replace(" ", ""), None)
    return raw, None


@with_db_retry
def get_dashboard_stats():
    conn = get_conn()
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]

    c.execute("SELECT SUM(wallet) FROM users")
    total_wallet = c.fetchone()[0] or 0

    c.execute("SELECT COUNT(*), SUM(gb), SUM(price) FROM user_configs")
    row = c.fetchone()
    total_configs = row[0] or 0
    total_gb = row[1] or 0
    total_revenue = row[2] or 0

    c.execute("SELECT COUNT(*) FROM tickets WHERE status='open'")
    open_tickets = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM topup_requests WHERE status='pending'")
    pending_topups = c.fetchone()[0]

    conn.close()
    return {
        "total_users": total_users,
        "total_wallet": total_wallet,
        "total_configs": total_configs,
        "total_gb": total_gb or 0,
        "total_revenue": total_revenue,
        "open_tickets": open_tickets,
        "pending_topups": pending_topups,
    }


@with_db_retry
def update_wallet(user_id, amount):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, wallet) VALUES (?, ?)", (user_id, 0))
    c.execute("UPDATE users SET wallet = wallet + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()


@with_db_retry
def get_wallet(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT wallet FROM users WHERE user_id=?", (user_id,))
    res = c.fetchone()
    conn.close()
    return res[0] if res else None


@with_db_retry
def ensure_discount_table():
    conn = get_conn()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS discount_codes (
        code TEXT PRIMARY KEY,
        percent INTEGER,
        max_uses INTEGER,
        used_count INTEGER DEFAULT 0,
        active INTEGER DEFAULT 1,
        created_at TEXT
    )''')
    conn.commit()
    conn.close()


@with_db_retry
def create_discount_code(code, percent, max_uses):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO discount_codes (code, percent, max_uses, used_count, active, created_at) VALUES (?, ?, ?, 0, 1, ?)",
        (code.strip().upper(), percent, max_uses, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


@with_db_retry
def code_exists(code):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT 1 FROM discount_codes WHERE code=?", (code.strip().upper(),))
    res = c.fetchone()
    conn.close()
    return res is not None


@with_db_retry
def get_all_discount_codes():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT code, percent, max_uses, used_count, active FROM discount_codes ORDER BY created_at DESC")
    res = c.fetchall()
    conn.close()
    return res


@with_db_retry
def toggle_discount_code(code):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT active FROM discount_codes WHERE code=?", (code,))
    row = c.fetchone()
    if row:
        new_active = 0 if row[0] == 1 else 1
        c.execute("UPDATE discount_codes SET active=? WHERE code=?", (new_active, code))
        conn.commit()
    conn.close()


@with_db_retry
def delete_discount_code(code):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM discount_codes WHERE code=?", (code,))
    conn.commit()
    conn.close()


@with_db_retry
def get_all_user_ids():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE COALESCE(banned, 0) = 0")
    res = [r[0] for r in c.fetchall()]
    conn.close()
    return res


@with_db_retry
def get_tickets(status_filter=None, limit=50):
    conn = get_conn()
    c = conn.cursor()
    if status_filter:
        c.execute(
            "SELECT id, user_id, message, status, admin_reply, created_at FROM tickets WHERE status=? ORDER BY id DESC LIMIT ?",
            (status_filter, limit),
        )
    else:
        c.execute(
            "SELECT id, user_id, message, status, admin_reply, created_at FROM tickets ORDER BY id DESC LIMIT ?",
            (limit,),
        )
    res = c.fetchall()
    conn.close()
    return res


@with_db_retry
def get_ticket(ticket_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, user_id, message, status, admin_reply, created_at FROM tickets WHERE id=?", (ticket_id,))
    res = c.fetchone()
    conn.close()
    return res


@with_db_retry
def update_ticket_status(ticket_id, status, admin_reply=None):
    conn = get_conn()
    c = conn.cursor()
    if admin_reply:
        c.execute("UPDATE tickets SET status=?, admin_reply=? WHERE id=?", (status, admin_reply, ticket_id))
    else:
        c.execute("UPDATE tickets SET status=? WHERE id=?", (status, ticket_id))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# ساختار دیتابیس: ستون‌های جدید (idempotent — اگه بات قبلاً ساخته باشه، بی‌خطا رد می‌شه)
# ---------------------------------------------------------------------------

_schema_ready = False
_schema_lock = threading.Lock()


def ensure_schema():
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        ok = True
        conn = get_conn()
        c = conn.cursor()
        for stmt in (
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)",
            "ALTER TABLE users ADD COLUMN last_active TEXT",
            "ALTER TABLE users ADD COLUMN last_action TEXT",
            "ALTER TABLE users ADD COLUMN username TEXT",
            "ALTER TABLE users ADD COLUMN first_name TEXT",
            "ALTER TABLE users ADD COLUMN joined_at TEXT",
            "ALTER TABLE users ADD COLUMN lang TEXT",
            "ALTER TABLE free_trials ADD COLUMN trial_count INTEGER DEFAULT 1",
            "ALTER TABLE free_trials ADD COLUMN last_at TEXT",
            "ALTER TABLE user_configs ADD COLUMN base_gb REAL",
            "ALTER TABLE user_configs ADD COLUMN base_days INTEGER",
            "ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0",
        ):
            try:
                c.execute(stmt)
            except Exception as e:
                msg = str(e).lower()
                if "duplicate column" in msg or "already exists" in msg or "no such table" in msg:
                    continue
                print("⚠️ ensure_schema:", e)
                ok = False
        try:
            conn.commit()
        except Exception:
            pass
        ensure_discount_table()
        _schema_ready = ok


# ---------------------------------------------------------------------------
# توابع کمکی عمومی
# ---------------------------------------------------------------------------

def to_int(value, default=None):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(value):
    return str(value).translate(_FA_DIGITS)


def g2j(gy, gm, gd):
    """تاریخ میلادی → شمسی."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy, gy = 979, gy - 1600
    else:
        jy, gy = 0, gy - 621
    gy2 = gy + 1 if gm > 2 else gy
    days = 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 - 80 + gd + g_d_m[gm - 1]
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return jy, jm, jd


def parse_ts(value):
    """رشته‌ی ISO → datetime آگاه از timezone (اگه offset نداشته باشه UTC فرض می‌شه)."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fmt_dt(value, with_time=True):
    dt = parse_ts(value)
    if not dt:
        return "—"
    dt = dt.astimezone(TEHRAN)
    jy, jm, jd = g2j(dt.year, dt.month, dt.day)
    out = f"{jy:04d}/{jm:02d}/{jd:02d}"
    if with_time:
        out += f" {dt.hour:02d}:{dt.minute:02d}"
    return fa(out)


def rel_time(value):
    dt = parse_ts(value)
    if not dt:
        return "هنوز فعالیتی ثبت نشده"
    secs = int((datetime.now(timezone.utc) - dt).total_seconds())
    if secs < 0:
        secs = 0
    if secs < 60:
        return "همین الان"
    if secs < 3600:
        return fa(f"{secs // 60} دقیقه پیش")
    if secs < 86400:
        return fa(f"{secs // 3600} ساعت پیش")
    if secs < 86400 * 30:
        return fa(f"{secs // 86400} روز پیش")
    if secs < 86400 * 365:
        return fa(f"{secs // (86400 * 30)} ماه پیش")
    return fa(f"{secs // (86400 * 365)} سال پیش")


def activity_state(value):
    """online (<۵ دقیقه) / today (<۲۴ ساعت) / old / none"""
    dt = parse_ts(value)
    if not dt:
        return "none"
    secs = (datetime.now(timezone.utc) - dt).total_seconds()
    return "online" if secs < 300 else ("today" if secs < 86400 else "old")


BTN_TITLES = {key: default for key, _label, default in BOT_BUTTONS}
CB_LABELS = {
    "menu": "بازگشت به منوی اصلی",
    "setlang_fa": "تغییر زبان به فارسی",
    "setlang_en": "تغییر زبان به انگلیسی",
    "skip_label": "رد شدن از انتخاب اسم کانفیگ",
    "reseller_activate": "شروع فعال‌سازی فروشندگی",
}
CB_PREFIXES = (
    ("cbtn_", "دکمه‌ی سفارشی"), ("reply_ticket_", "پاسخ به تیکت"), ("close_ticket_", "بستن تیکت"),
    ("topup_acc_", "تایید شارژ"), ("topup_rej_", "رد شارژ"),
)
STEP_LABELS = {
    "ask_label": "در حال انتخاب اسم کانفیگ", "confirm_buy": "در صفحه‌ی تایید خرید",
    "buy_enter_discount": "در حال وارد کردن کد تخفیف", "waiting_receipt": "در حال ارسال رسید شارژ",
    "admin_reply": "در حال پاسخ به تیکت",
    "crypto_declare_amount": "در حال نوشتن مقدار واریز رمزارزی", "crypto_send_hash": "در حال ارسال هش تراکنش",
    "exchange_amount": "در صفحه‌ی صرافی",
}


def tgl_btn(on, formaction=None):
    """دکمه‌ی روشن/خاموش: وضعیت فعلی رو روی خودش می‌نویسه («روشن است» / «خاموش است») و با هر بار زدن عوض می‌شه."""
    fa = f' formaction="{formaction}" formnovalidate' if formaction else ''
    return (f'<button type="submit" class="tgl {"on" if on else "off"}"{fa}>'
            f'{"✅ روشن است" if on else "⛔ خاموش است"}</button>')


def action_label(raw):
    """ترجمه‌ی مقدار خام last_action (که بات ثبت می‌کنه) به متن فارسی خوانا."""
    if not raw:
        return "—"
    kind, _, val = str(raw).partition(":")
    if kind == "cmd":
        return f"دستور {val}"
    if kind == "btn":
        return "دکمه‌ی " + BTN_TITLES.get(val, val)
    if kind == "cb":
        if val.startswith("menu_"):
            k = val[5:]
            return "دکمه‌ی " + BTN_TITLES.get(k, k)
        if val in CB_LABELS:
            return CB_LABELS[val]
        for prefix, label in CB_PREFIXES:
            if val.startswith(prefix):
                return label
        return "دکمه‌ی داخل پیام (" + val + ")"
    if kind == "photo":
        return "ارسال عکس"
    if kind == "step":
        return STEP_LABELS.get(val, "در حال مرحله‌ی «" + val + "»")
    if kind == "text":
        return "ارسال پیام متنی"
    return str(raw)


def user_display(first_name, username, user_id):
    parts = []
    if first_name:
        parts.append(f"<b>{esc(first_name)}</b>")
    if username:
        parts.append(f'<span class="muted" dir="ltr">@{esc(username)}</span>')
    return " ".join(parts) if parts else f'<span class="muted">کاربر {user_id}</span>'


# ---------------------------------------------------------------------------
# کوئری‌های جدید (کاربران / آمار / فروشندگان)
# ---------------------------------------------------------------------------

USER_SORTS = {
    "active": "last_active IS NULL, last_active DESC, user_id DESC",
    "joined": "joined_at IS NULL, joined_at DESC, user_id DESC",
    "wallet": "wallet DESC, user_id DESC",
}


def _users_where(search, only_recent, only_banned=False):
    where, params = [], []
    if only_banned:
        where.append("banned = 1")
    if search:
        like = f"%{search}%"
        where.append("(CAST(user_id AS TEXT) LIKE ? OR username LIKE ? OR first_name LIKE ?)")
        params += [like, like, like]
    if only_recent:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
        where.append("last_active >= ?")
        params.append(cutoff)
    return (("WHERE " + " AND ".join(where)) if where else ""), params


@with_db_retry
def get_users_count(search=None, only_recent=False, only_banned=False):
    conn = get_conn()
    c = conn.cursor()
    where, params = _users_where(search, only_recent, only_banned)
    c.execute(f"SELECT COUNT(*) FROM users {where}", params)
    total = c.fetchone()[0]
    conn.close()
    return total


@with_db_retry
def get_users_page(offset=0, limit=USERS_PAGE_SIZE, search=None, sort="active", only_recent=False, only_banned=False):
    conn = get_conn()
    c = conn.cursor()
    where, params = _users_where(search, only_recent, only_banned)
    order = USER_SORTS.get(sort, USER_SORTS["active"])
    c.execute(
        f"""SELECT user_id, username, first_name, wallet, joined_at, last_active, last_action
            FROM users {where} ORDER BY {order} LIMIT ? OFFSET ?""",
        params + [limit, offset],
    )
    res = c.fetchall()
    conn.close()
    return res


@with_db_retry
def get_user(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name, wallet, joined_at, last_active, last_action, lang "
              "FROM users WHERE user_id=?", (user_id,))
    res = c.fetchone()
    conn.close()
    return res


@with_db_retry
def get_banned_ids(ids):
    """مجموعه‌ی آیدی‌های مسدود بین ids."""
    ids = [int(i) for i in ids if i]
    if not ids:
        return set()
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("SELECT user_id FROM users WHERE banned=1 AND user_id IN (%s)" % ",".join("?" * len(ids)), ids)
        res = {r[0] for r in c.fetchall()}
    except Exception as e:
        if "stream" in str(e).lower():
            raise
        res = set()
    conn.close()
    return res


@with_db_retry
def set_user_banned(user_id, banned):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET banned=? WHERE user_id=?", (1 if banned else 0, user_id))
    conn.commit()
    conn.close()


@with_db_retry
def get_trial_info(user_id):
    """(تعداد تست‌های گرفته‌شده, زمان آخرین تست). اگه کاربر تست نگرفته (0, None)."""
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("SELECT COALESCE(trial_count, 1), last_at FROM free_trials WHERE user_id=?", (user_id,))
        row = c.fetchone()
    except Exception:
        row = None
    conn.close()
    return (int(row[0] or 0), row[1]) if row else (0, None)


@with_db_retry
def reset_trial(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM free_trials WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


@with_db_retry
def get_user_configs(user_id, limit=50):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT label, type, gb, days, price, status, created_at, expires_at "
              "FROM user_configs WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))
    res = c.fetchall()
    conn.close()
    return res


@with_db_retry
def get_extra_stats():
    """فعال ۲۴ ساعت اخیر، عضو جدید ۷ روز اخیر و سری‌های روزانه‌ی ۱۴ روز اخیر (درآمد و عضویت)."""
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now(timezone.utc)
    c.execute("SELECT COUNT(*) FROM users WHERE last_active >= ?",
              ((now - timedelta(hours=24)).isoformat(timespec="seconds"),))
    active_24h = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM users WHERE last_active >= ?",
              ((now - timedelta(minutes=5)).isoformat(timespec="seconds"),))
    online_now = c.fetchone()[0] or 0

    today = datetime.now().date()
    days = [today - timedelta(days=i) for i in range(13, -1, -1)]
    since = days[0].isoformat()
    revenue, joins = {}, {}
    try:
        c.execute("SELECT substr(created_at,1,10), COUNT(*), COALESCE(SUM(price),0) FROM orders "
                  "WHERE created_at >= ? GROUP BY 1", (since,))
        for d, cnt, total in c.fetchall():
            revenue[d] = (cnt, total)
    except Exception as e:
        if "stream" in str(e).lower():
            raise
    try:
        c.execute("SELECT substr(joined_at,1,10), COUNT(*) FROM users WHERE joined_at >= ? GROUP BY 1", (since,))
        for d, cnt in c.fetchall():
            joins[d] = cnt
    except Exception as e:
        if "stream" in str(e).lower():
            raise
    conn.close()
    series_rev = [(d, revenue.get(d.isoformat(), (0, 0))[1], revenue.get(d.isoformat(), (0, 0))[0]) for d in days]
    series_join = [(d, joins.get(d.isoformat(), 0)) for d in days]
    new_7d = sum(v for _d, v in series_join[-7:])
    return {"active_24h": active_24h, "online_now": online_now, "new_7d": new_7d,
            "rev": series_rev, "joins": series_join}


@with_db_retry
def get_topups(limit=60):
    """(id, user_id, amount, status, created_at, method, coin_symbol, coin_qty, tx_hash, matched_tx)
    درخواست‌های در انتظار اول می‌آن."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, user_id, amount, status, created_at, method, coin_symbol, coin_qty, tx_hash, matched_tx, user_note "
              "FROM topup_requests ORDER BY (CASE WHEN status='pending' THEN 0 ELSE 1 END), id DESC LIMIT ?", (limit,))
    res = c.fetchall()
    conn.close()
    return res


@with_db_retry
def get_topup_row(req_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, user_id, amount, status, method, matched_tx FROM topup_requests WHERE id=?", (req_id,))
    row = c.fetchone()
    conn.close()
    return row


@with_db_retry
def claim_topup(req_id, new_status):
    """اتمیک: فقط اگه هنوز pending باشه وضعیت رو عوض می‌کنه و True برمی‌گردونه.
    این‌طوری حتی اگه همزمان از بات (دکمه‌ی تلگرام) هم تایید بشه، فقط یکی‌شون برنده می‌شه و شارژ دوبار انجام نمی‌شه."""
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("UPDATE topup_requests SET status=? WHERE id=? AND status='pending' RETURNING id", (new_status, req_id))
        won = c.fetchone() is not None
    except Exception as e:
        if "stream" in str(e).lower():
            raise
        c.execute("UPDATE topup_requests SET status=? WHERE id=? AND status='pending'", (new_status, req_id))
        won = (c.rowcount or 0) > 0
    conn.commit()
    conn.close()
    return won


@with_db_retry
def mark_deposit_used(tx, req_id):
    if not tx:
        return
    conn = get_conn()
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS crypto_deposits_used (tx TEXT PRIMARY KEY, req_id INTEGER, created_at TEXT)")
    c.execute("INSERT OR IGNORE INTO crypto_deposits_used (tx, req_id, created_at) VALUES (?, ?, ?)",
              (tx, req_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()


_TOPUP_TEXTS = {
    "fa": {
        "topup_approved": "✅ کیف پول شما به مبلغ <b>{credited}</b> تومان شارژ شد.",
        "topup_approved_mult": "✅ کیف پول شما به مبلغ <b>{credited}</b> تومان شارژ شد (واریزی {amount} تومان × ضریب {multiplier}).",
        "topup_rejected": "❌ رسید واریز شما رد شد. لطفاً با پشتیبانی در ارتباط باشید.",
    },
    "en": {
        "topup_approved": "✅ Your wallet was topped up by <b>{credited}</b> Toman.",
        "topup_approved_mult": "✅ Your wallet was topped up by <b>{credited}</b> Toman (deposit {amount} Toman × multiplier {multiplier}).",
        "topup_rejected": "❌ Your deposit receipt was rejected. Please contact support.",
    },
}


def topup_user_text(user_id, key, **kwargs):
    """همون متنی که بات می‌فرسته (با احترام به متن‌های ویرایش‌شده از پنل و زبان کاربر)."""
    u = None
    try:
        u = get_user(user_id)
    except Exception:
        pass
    lang = (u[7] if u and u[7] in ("fa", "en") else "fa")
    text = _TOPUP_TEXTS[lang][key]
    override = get_setting("ui_%s_%s" % (lang, key), None)
    for cand in ((override, text) if override else (text,)):
        try:
            return cand.format(**kwargs)
        except Exception:
            continue
    return text


def panel_approve_topup(req_id):
    """(ok, پیام). منطق دقیقاً مثل approve_topup_request توی بات: رمزارز بدون ضریب، کارت‌به‌کارت با ضریب واریزی."""
    req = get_topup_row(req_id)
    if not req:
        return False, "درخواست پیدا نشد."
    _id, user_id, amount, status, method, matched_tx = req
    if status != "pending":
        return False, "این درخواست قبلاً بررسی شده."
    multiplier = 1.0
    if (method or "card") != "crypto":
        try:
            multiplier = float(get_setting("topup_multiplier", "1"))
        except (TypeError, ValueError):
            multiplier = 1.0
    credited = int(round((amount or 0) * multiplier))
    if not claim_topup(req_id, "approved"):
        return False, "این درخواست همین الان جای دیگه (مثلاً تو بات) بررسی شد."
    update_wallet(user_id, credited)
    try:
        mark_deposit_used(matched_tx, req_id)
    except Exception as e:
        print("⚠️ ثبت واریز استفاده‌شده ناموفق:", e)
    if multiplier != 1:
        msg = topup_user_text(user_id, "topup_approved_mult", credited=f"{credited:,}",
                              amount=f"{int(amount or 0):,}", multiplier=("%g" % multiplier))
    else:
        msg = topup_user_text(user_id, "topup_approved", credited=f"{credited:,}")
    sent = send_telegram_message(user_id, msg)
    return True, (f"درخواست #{req_id} تایید شد و {credited:,} تومان به کیف پول کاربر اضافه شد."
                  + ("" if sent else " ⚠️ ولی ارسال پیام به کاربر ناموفق بود."))


def panel_reject_topup(req_id):
    req = get_topup_row(req_id)
    if not req:
        return False, "درخواست پیدا نشد."
    if req[3] != "pending":
        return False, "این درخواست قبلاً بررسی شده."
    if not claim_topup(req_id, "rejected"):
        return False, "این درخواست همین الان جای دیگه (مثلاً تو بات) بررسی شد."
    sent = send_telegram_message(req[1], topup_user_text(req[1], "topup_rejected"))
    return True, f"درخواست #{req_id} رد شد." + ("" if sent else " ⚠️ ولی ارسال پیام به کاربر ناموفق بود.")


RESELLER_PASSWORD_MIN, RESELLER_PASSWORD_MAX = 6, 64


def secret_widget(value, label_hint=""):
    """رمز مخفی‌شده + دکمه‌ی نمایش و کپی."""
    v = esc(value)
    return (f'<span class="secret"><code class="masked" data-v="{v}">••••••••</code>'
            f'<button type="button" class="mini" onclick="revealSecret(this)" title="نمایش / مخفی" aria-label="نمایش رمز">👁</button>'
            f'<button type="button" class="mini" data-copy="{v}" onclick="copyFrom(this)" title="کپی" aria-label="کپی رمز">📋</button></span>')


def copy_widget(value):
    v = esc(value)
    return (f'<span class="secret"><code>{v}</code>'
            f'<button type="button" class="mini" data-copy="{v}" onclick="copyFrom(this)" title="کپی" aria-label="کپی">📋</button></span>')


def login_info_text(username, password):
    panel = get_setting("reseller_panel_url", DEFAULT_RESELLER_PANEL_URL)
    return f"پنل: {panel}\nنام کاربری: {username}\nرمز عبور: {password}"


# ---------------------------------------------------------------------------
# فروشندگان روی سرویس (Seller API → resale/subs)
# حجم، قیمت، وضعیت و رمز هر فروشنده مستقیم روی سرویس اصلی خونده و تغییر داده می‌شه؛
# ---------------------------------------------------------------------------

SELLER_API_BASE = (os.getenv("SELLER_API_BASE", "").strip() or "https://su.randomatic.ir/api/v1").rstrip("/")
SELLER_API_KEY = (os.getenv("SELLER_API_KEY", "").strip()
                  or "sk_live_iIlB6uH_KSibQMUTnq2Ef6UcgWYztoQL")


def seller_api(method, path, payload=None, params=None):
    """درخواست به Seller API. خروجی: success / data  یا  success=False / status / error_code / message."""
    if not SELLER_API_KEY:
        return {"success": False, "status": 0, "error_code": None, "message": "SELLER_API_KEY تنظیم نشده"}
    try:
        res = SESSION.request(method, SELLER_API_BASE + path,
                              headers={"Authorization": "Bearer " + SELLER_API_KEY},
                              json=payload, params=params, timeout=20)
        try:
            data = res.json()
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        if res.status_code in (200, 201) and data.get("ok", True) is not False:
            return {"success": True, "data": data}
        return {"success": False, "status": res.status_code,
                "error_code": data.get("error") or str(res.status_code),
                "message": data.get("message") or ""}
    except Exception as e:
        return {"success": False, "status": 0, "error_code": None, "message": str(e)}


def seller_reason(res):
    """متن فارسی دلیل خطا برای نمایش تو پنل."""
    msg = (res.get("message") or "").strip()
    st = res.get("status")
    if st == 0:
        return "ارتباط با سرویس برقرار نشد؛ کمی بعد دوباره تلاش کنید."
    if st == 404:
        return "این فروشنده تو سرویس پیدا نشد."
    if st == 429:
        return "تعداد درخواست‌ها زیاد بود؛ چند ثانیه بعد دوباره تلاش کنید."
    if st in (401, 403):
        return "کلید سرویس معتبر نیست یا دسترسی نداره."
    return (msg[:200] or f"خطای سرویس ({st} {res.get('error_code')})")


_SUBS_CACHE = {"at": 0.0, "rows": None}


def invalidate_subs_cache():
    _SUBS_CACHE["rows"] = None


def fetch_service_subs(force=False):
    """لیست کامل زیرمجموعه‌های سرویس (rows)، یا None اگه سرویس جواب نداد. ۱۵ ثانیه کش می‌شه."""
    if not force and _SUBS_CACHE["rows"] is not None and time.time() - _SUBS_CACHE["at"] < 15:
        return _SUBS_CACHE["rows"]
    rows, skip = [], 0
    for _ in range(200):
        res = seller_api("GET", "/resale/subs", params={"skip": skip, "limit": 50})
        if not res["success"]:
            print("⚠️ گرفتن لیست زیرمجموعه‌ها ناموفق:", res)
            return None
        part = res["data"].get("rows") or []
        rows.extend(p for p in part if isinstance(p, dict))
        skip += len(part)
        total = to_int(res["data"].get("total"), 0) or 0
        if not part or skip >= total:
            break
    _SUBS_CACHE["rows"], _SUBS_CACHE["at"] = rows, time.time()
    return rows


@with_db_retry
def get_seller_accounts():
    """[(telegram_id, sub_user_id, username, panel_url, password)] از جدول seller_accounts بات."""
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT user_id, sub_user_id, username, panel_url, password FROM seller_accounts")
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        if "no such table" in str(e).lower():
            return []
        raise


@with_db_retry
def get_tg_users(ids):
    ids = [int(i) for i in ids if i]
    if not ids:
        return {}
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name FROM users WHERE user_id IN (%s)" % ",".join("?" * len(ids)), ids)
    res = {r[0]: (r[1], r[2]) for r in c.fetchall()}
    conn.close()
    return res


@with_db_retry
def save_seller_password_local(tg_id, sub_id, username, panel_url, password):
    """رمز (متن ساده) رو تو seller_accounts بات هم نگه می‌داره تا فروشنده تو بات ببینتش."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO seller_accounts (user_id, sub_user_id, username, panel_url, created_at, password) "
              "VALUES (?, ?, ?, ?, ?, ?) "
              "ON CONFLICT(user_id) DO UPDATE SET sub_user_id=excluded.sub_user_id, username=excluded.username, "
              "panel_url=COALESCE(seller_accounts.panel_url, excluded.panel_url), password=excluded.password",
              (tg_id, sub_id, username, panel_url, datetime.now().isoformat(), password))
    conn.commit()
    conn.close()


def build_vendors():
    """(لیست فروشنده‌ها, سرویس_جواب_داد؟). هر فروشنده یه dict:
    key, sub_id, tg_id, name, status (active/suspended), credit, price, purchases, paid, panel_url,
    password, tg_user, tg_name, on_service. فقط فروشندگی جدید (seller_accounts + لیست زیرمجموعه‌های سرویس)."""
    subs = fetch_service_subs()
    accounts = get_seller_accounts()
    by_sub = {str(a[1]): a for a in accounts if a[1]}
    acc_by_tg = {a[0]: a for a in accounts}
    by_uname = {str(a[2]).lower(): a[0] for a in accounts if a[2]}
    vendors, used_tg = [], set()
    for s_ in (subs or []):
        sid = str(s_.get("userId") or "")
        name = str(s_.get("displayName") or "")
        a = by_sub.get(sid)
        tg = a[0] if a else by_uname.get(name.lower())
        if tg in used_tg:
            tg = None
        if tg:
            used_tg.add(tg)
        pw = a[4] if a and a[4] else None
        price = s_.get("gbTomanOverride") if s_.get("modeOverride") == "price" and s_.get("gbTomanOverride") else None
        vendors.append({
            "key": sid, "sub_id": sid, "tg_id": tg, "name": name,
            "status": "suspended" if s_.get("status") == "suspended" else "active",
            "credit": float(s_.get("creditGb") or 0), "price": price,
            "purchases": to_int(s_.get("purchases"), 0) or 0, "paid": to_int(s_.get("paidToman"), 0) or 0,
            "panel_url": (a[3] if a else None), "password": pw, "on_service": True,
        })
    for tg in sorted(set(acc_by_tg) - used_tg):
        a = acc_by_tg[tg]
        vendors.append({
            "key": f"tg{tg}", "sub_id": None, "tg_id": tg, "name": a[2] or "—",
            "status": "active", "credit": None, "price": None, "purchases": 0, "paid": 0,
            "panel_url": a[3], "password": a[4], "on_service": False,
        })
    tgu = get_tg_users([v["tg_id"] for v in vendors])
    for v in vendors:
        v["tg_user"], v["tg_name"] = tgu.get(v["tg_id"], (None, None)) if v["tg_id"] else (None, None)
    return vendors, subs is not None


def find_vendor(vkey):
    for v in build_vendors()[0]:
        if v["key"] == str(vkey):
            return v
    return None


def parse_gb_delta(raw):
    """«۲۰» یا «-5» یا «2,5» → float (یا None اگه نامعتبر بود)."""
    t = str(raw or "").strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    t = t.replace("٫", ".").replace(",", ".").replace("−", "-")
    try:
        v = float(t)
    except ValueError:
        return None
    return v if v == v and abs(v) != float("inf") else None


def vendor_login_text(v):
    panel = v.get("panel_url") or get_setting("reseller_panel_url", DEFAULT_RESELLER_PANEL_URL)
    return f"پنل: {panel}\nنام کاربری: {v['name']}\nرمز عبور: {v['password']}"


# ---------------------------------------------------------------------------
# اطلاعات ربات (getMe) + ارسال پیام
# ---------------------------------------------------------------------------

_BOT_INFO = {"ts": 0.0, "data": None}


def get_bot_info():
    if not BOT_TOKEN:
        return None
    if time.time() - _BOT_INFO["ts"] < 300:
        return _BOT_INFO["data"]
    data = None
    try:
        r = SESSION.get(BASE_URL + "/getMe", timeout=6).json()
        if r.get("ok"):
            data = r.get("result")
    except Exception:
        data = None
    _BOT_INFO.update(ts=time.time(), data=data)
    return data


def send_telegram_message(chat_id, text):
    if not BOT_TOKEN:
        return False
    try:
        res = SESSION.post(BASE_URL + "/sendMessage",
                           json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=15)
        return res.json().get("ok", False)
    except Exception:
        return False


BROADCAST = {"running": False, "sent": 0, "failed": 0, "total": 0, "started": None}


def broadcast_worker(text, user_ids):
    BROADCAST.update(running=True, sent=0, failed=0, total=len(user_ids), started=datetime.now(timezone.utc).isoformat())
    try:
        for uid in user_ids:
            if send_telegram_message(uid, text):
                BROADCAST["sent"] += 1
            else:
                BROADCAST["failed"] += 1
            time.sleep(0.05)
    finally:
        BROADCAST["running"] = False
        print(f"📣 پیام همگانی تمام شد: {BROADCAST['sent']} موفق، {BROADCAST['failed']} ناموفق")


# ---------------------------------------------------------------------------
# احراز هویت، CSRF و محدودیت تلاش ورود
# ---------------------------------------------------------------------------

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)

LOGIN_FAILS = {}          # ip -> [تعداد, زمان اولین خطا]
LOGIN_MAX_FAILS, LOGIN_LOCK_SECONDS = 6, 600


def _client_ip():
    return request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "?"


def login_locked():
    rec = LOGIN_FAILS.get(_client_ip())
    if not rec:
        return False
    if time.time() - rec[1] > LOGIN_LOCK_SECONDS:
        LOGIN_FAILS.pop(_client_ip(), None)
        return False
    return rec[0] >= LOGIN_MAX_FAILS


def login_failed():
    ip = _client_ip()
    rec = LOGIN_FAILS.get(ip)
    if not rec or time.time() - rec[1] > LOGIN_LOCK_SECONDS:
        LOGIN_FAILS[ip] = [1, time.time()]
    else:
        rec[0] += 1


def safe_equal(a, b):
    return hmac.compare_digest(str(a).encode("utf-8"), str(b).encode("utf-8"))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


_ENV_BOOT = {}
_ENV_LAST = {"ts": 0.0}
_ENV_OVERRIDES = (
    ("env_bot_token", "BOT_TOKEN"), ("env_seller_api_base", "SELLER_API_BASE"), ("env_seller_api_key", "SELLER_API_KEY"),
    ("env_config_api", "CONFIG_API"), ("env_config_key", "CONFIG_KEY"),
)


def apply_env_overrides(force=False):
    """مقدارهایی که از صفحه‌ی «متغیرهای محیطی» ذخیره شدن رو روی متغیرهای سراسری پنل اعمال می‌کنه (هر ~۱۰ ثانیه)."""
    if not force and time.time() - _ENV_LAST["ts"] < 10:
        return
    _ENV_LAST["ts"] = time.time()
    st = get_all_settings()
    g = globals()
    for skey, gname in _ENV_OVERRIDES:
        if gname not in g:      # مثلاً CONFIG_API پایین‌تر تعریف می‌شه؛ تا وقتی تعریف نشده رد می‌شیم
            continue
        _ENV_BOOT.setdefault(gname, g[gname])
        newv = (st.get(skey) or "").strip() or _ENV_BOOT[gname]
        if gname in ("SELLER_API_BASE", "CONFIG_API"):
            newv = str(newv).rstrip("/")
        if newv != g[gname]:
            g[gname] = newv
            if gname == "BOT_TOKEN":
                g["BASE_URL"] = "https://api.splus.ir/bot" + newv


@app.before_request
def _before_request():
    if request.endpoint in ("static", "panel_font"):
        return None
    try:
        apply_env_overrides()
    except Exception as e:
        print("⚠️ apply_env_overrides:", e)
    try:
        ensure_schema()
    except Exception as e:
        print("⚠️ ensure_schema:", e)
    if request.method == "POST" and request.endpoint != "login":
        sent = request.form.get("csrf", "")
        try:
            valid = bool(sent) and hmac.compare_digest(sent, session.get("csrf", ""))
        except TypeError:
            valid = False
        if not valid:
            flash("⚠️ نشست منقضی شده بود؛ دوباره تلاش کنید.")
            return redirect(url_for("dashboard") if session.get("logged_in") else url_for("login"))
    return None


@app.after_request
def _security_headers(resp):
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("Cache-Control", "no-store")
    return resp


# ---------------------------------------------------------------------------
# قالب پایه: طراحی جدید (RTL، تم روشن/تیره، سایدبار روی دسکتاپ و نوار پایین روی موبایل)
# ---------------------------------------------------------------------------

BASE_HTML = """<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<title>پنل مدیریت SkyTunnel</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script>
  (function () {
    var t = null;
    try { t = localStorage.getItem('sky-theme'); } catch (e) {}
    if (!t) t = 'dark';
    document.documentElement.setAttribute('data-theme', t);
  })();
</script>
<style>
  :root {
    --bg: #eef1fb; --surface: rgba(255,255,255,.78); --surface-2: rgba(240,243,255,.9); --border: rgba(99,102,241,.16); --ink: #121a3a; --muted: #62709a;
    --g1: #6d4aff; --g2: #00b8e6; --g3: #ff4fa3;
    --brand: #5b4bff; --brand-ink: #ffffff; --brand-dim: rgba(91,75,255,.12);
    --grad: linear-gradient(135deg, var(--g1), var(--g2));
    --side: #0c1230; --side-ink: #aab6e0; --side-active: rgba(255,255,255,.08); --sun: #ffb324;
    --ok: #0b8f67; --ok-dim: rgba(11,143,103,.13); --warn: #a45f00; --warn-dim: rgba(255,179,36,.22);
    --danger: #d23b57; --danger-dim: rgba(210,59,87,.11);
    --shadow: 0 1px 2px rgba(20,24,70,.05), 0 10px 30px rgba(60,60,160,.09);
    --glow: 0 6px 22px rgba(109,74,255,.35);
    --radius: 18px; --nav-h: 70px; --blur: blur(14px) saturate(140%);
  }
  [data-theme="dark"] {
    --bg: #060a1a; --surface: rgba(17,24,52,.66); --surface-2: rgba(28,38,78,.62); --border: rgba(130,150,255,.15); --ink: #eaf0ff; --muted: #8f9dc6;
    --g1: #8b6cff; --g2: #22d3ff; --g3: #ff5fae;
    --brand: #8b7bff; --brand-ink: #ffffff; --brand-dim: rgba(139,123,255,.18);
    --side: rgba(8,12,32,.82); --side-ink: #9eacd6; --side-active: rgba(255,255,255,.07);
    --ok: #3ddc97; --ok-dim: rgba(61,220,151,.14); --warn: #ffc457; --warn-dim: rgba(255,179,36,.15);
    --danger: #ff7b93; --danger-dim: rgba(255,123,147,.14);
    --shadow: 0 1px 2px rgba(0,0,0,.35), 0 12px 34px rgba(0,0,0,.32);
    --glow: 0 6px 26px rgba(139,108,255,.45);
  }
  * { box-sizing: border-box; }
  html { scroll-behavior: smooth; }
  body { margin: 0; font-family: 'Vazirmatn', Tahoma, sans-serif; font-size: 14.5px; line-height: 1.8; background: var(--bg); color: var(--ink); -webkit-text-size-adjust: 100%; min-height: 100vh; }
  body::before { content: ''; position: fixed; inset: 0; z-index: -2; pointer-events: none;
    background: radial-gradient(900px 520px at 88% -8%, rgba(109,74,255,.26), transparent 62%),
                radial-gradient(760px 520px at -4% 18%, rgba(0,184,230,.17), transparent 62%),
                radial-gradient(820px 620px at 55% 118%, rgba(255,79,163,.13), transparent 62%); }
  body::after { content: ''; position: fixed; inset: 0; z-index: -1; pointer-events: none; opacity: .5;
    background-image: linear-gradient(var(--border) 1px, transparent 1px), linear-gradient(90deg, var(--border) 1px, transparent 1px);
    background-size: 46px 46px; -webkit-mask-image: radial-gradient(ellipse at 50% 0%, #000 0%, transparent 70%); mask-image: radial-gradient(ellipse at 50% 0%, #000 0%, transparent 70%); }
  a { color: var(--brand); }
  ::selection { background: var(--g1); color: #fff; }
  :focus-visible { outline: 3px solid var(--brand); outline-offset: 2px; }
  code { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: .92em; background: var(--surface-2); padding: 1px 8px; border-radius: 8px; direction: ltr; unicode-bidi: embed; border: 1px solid var(--border); }
  h2, h3, h4 { margin: 0; }
  h3 { font-size: 16.5px; margin: 0 0 12px; font-weight: 700; }
  .muted, small.muted { color: var(--muted); }
  .num { font-variant-numeric: tabular-nums; }
  ::-webkit-scrollbar { width: 9px; height: 9px; }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 9px; }
  @keyframes fadeUp { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: none; } }
  @keyframes spin { to { transform: rotate(360deg); } }
  @keyframes floaty { 0%,100% { transform: translate(0,0) scale(1); } 50% { transform: translate(24px,-30px) scale(1.08); } }
  @keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(61,220,151,.55); } 100% { box-shadow: 0 0 0 9px rgba(61,220,151,0); } }

  /* ---------- سایدبار (دسکتاپ) ---------- */
  .sidebar { display: none; }
  @media (min-width: 1000px) {
    :root { --nav-h: 0px; }
    .sidebar { display: flex; flex-direction: column; position: fixed; top: 14px; right: 14px; bottom: 14px; width: 262px; background: var(--side); -webkit-backdrop-filter: var(--blur); backdrop-filter: var(--blur); color: var(--side-ink); padding: 20px 14px; overflow-y: auto; z-index: 30; border: 1px solid var(--border); border-radius: 24px; box-shadow: var(--shadow); }
    .shell { margin-right: 290px; }
    .bottom-nav, .topbar { display: none !important; }
    .app { padding-bottom: 48px !important; }
  }
  .brand { display: flex; align-items: center; gap: 12px; padding: 4px 8px 18px; }
  .mark { width: 40px; height: 40px; border-radius: 13px; background: var(--grad); position: relative; flex-shrink: 0; box-shadow: 0 0 24px rgba(124,92,255,.55); }
  .mark::after { content: ''; position: absolute; inset: 9px; border-radius: 50%; border: 2.5px solid rgba(255,255,255,.92); border-top-color: transparent; animation: spin 6s linear infinite; }
  .brand b { display: block; color: #fff; font-size: 18px; line-height: 1.3; letter-spacing: .3px; }
  .brand span { font-size: 12px; opacity: .85; display: flex; align-items: center; gap: 6px; }
  .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; background: #3ddc97; animation: pulse 1.8s infinite; }
  .dot.off { background: #7d8aab; animation: none; }
  .nav-group { font-size: 11px; font-weight: 700; letter-spacing: .6px; opacity: .5; padding: 16px 12px 6px; }
  .side-link { display: flex; align-items: center; gap: 12px; padding: 10px 12px; border-radius: 13px; color: var(--side-ink); text-decoration: none; font-weight: 500; font-size: 14.5px; transition: .18s; border: 1px solid transparent; }
  .side-link svg { width: 20px; height: 20px; flex-shrink: 0; }
  .side-link:hover { background: var(--side-active); color: #fff; transform: translateX(-3px); }
  .side-link.active { background: var(--grad); color: #fff; font-weight: 700; box-shadow: var(--glow); }
  .side-foot { margin-top: auto; padding-top: 16px; display: flex; gap: 8px; }
  .side-foot a, .side-foot button { flex: 1; text-align: center; padding: 9px 10px; border-radius: 12px; font-size: 13px; background: var(--side-active); color: #fff; border: 1px solid var(--border); text-decoration: none; cursor: pointer; font-family: inherit; font-weight: 600; box-shadow: none; }
  .side-foot a:hover, .side-foot button:hover { background: rgba(255,255,255,.14); filter: none; transform: none; }

  /* ---------- نوار بالا و پایین (موبایل) ---------- */
  .topbar { position: sticky; top: 0; z-index: 20; background: var(--side); -webkit-backdrop-filter: var(--blur); backdrop-filter: var(--blur); color: #fff; padding: calc(env(safe-area-inset-top, 0px) + 10px) 16px 10px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); }
  .topbar .brand { padding: 0; }
  .topbar .brand b { font-size: 17px; }
  .icon-btn { width: 38px; height: 38px; border-radius: 12px; border: 1px solid rgba(255,255,255,.16); background: rgba(255,255,255,.05); color: #dbe3f7; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; font-size: 17px; text-decoration: none; font-family: inherit; padding: 0; box-shadow: none; }
  .bottom-nav { position: fixed; bottom: 10px; left: 10px; right: 10px; z-index: 40; background: var(--side); -webkit-backdrop-filter: var(--blur); backdrop-filter: var(--blur); border: 1px solid var(--border); border-radius: 22px; margin-bottom: env(safe-area-inset-bottom, 0px); box-shadow: var(--shadow); }
  .nav-inner { max-width: 760px; margin: 0 auto; display: flex; }
  .bottom-nav a { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 9px 4px 8px; color: var(--side-ink); text-decoration: none; font-size: 11.5px; position: relative; }
  .bottom-nav a svg { width: 22px; height: 22px; }
  .bottom-nav a.active { color: #fff; font-weight: 700; }
  .bottom-nav a.active::before { content: ''; position: absolute; top: 0; width: 28px; height: 3px; border-radius: 3px; background: var(--grad); box-shadow: var(--glow); }
  .drawer-overlay { display: none; position: fixed; inset: 0; background: rgba(4,7,20,.65); -webkit-backdrop-filter: blur(4px); backdrop-filter: blur(4px); z-index: 50; }
  .drawer-overlay:target { display: block; }
  .drawer { position: absolute; bottom: 0; left: 50%; transform: translateX(-50%); width: 100%; max-width: 760px; background: var(--bg); border: 1px solid var(--border); border-radius: 26px 26px 0 0; padding: 10px 20px calc(env(safe-area-inset-bottom, 0px) + 24px); max-height: 84vh; overflow-y: auto; }
  .drawer .handle { width: 40px; height: 4px; background: var(--border); border-radius: 4px; margin: 8px auto 12px; }
  .drawer h4 { font-size: 12px; color: var(--muted); margin: 16px 0 2px; }
  .drawer a.dl { display: flex; align-items: center; gap: 12px; padding: 12px 2px; color: var(--ink); text-decoration: none; font-weight: 600; border-bottom: 1px solid var(--border); }
  .drawer a.dl svg { width: 20px; height: 20px; color: var(--brand); }

  /* ---------- محتوا ---------- */
  .app { max-width: 1140px; margin: 0 auto; padding: 22px 16px calc(var(--nav-h) + env(safe-area-inset-bottom, 0px) + 40px); animation: fadeUp .45s both; }
  @media (max-width: 999px) { .app { padding-bottom: calc(100px + env(safe-area-inset-bottom, 0px)); } }
  @media (min-width: 1000px) { .app { padding: 32px 30px 48px; } }
  .page-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 18px; }
  .page-title { font-size: 27px; font-weight: 800; line-height: 1.4; margin: 0; background: linear-gradient(90deg, var(--ink), var(--brand)); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; }
  .panel, .card { background: var(--surface); -webkit-backdrop-filter: var(--blur); backdrop-filter: var(--blur); border: 1px solid var(--border); border-radius: var(--radius); padding: 18px 20px; margin-bottom: 16px; box-shadow: var(--shadow); animation: fadeUp .5s both; transition: border-color .2s, transform .2s; }
  .card:hover { border-color: rgba(139,123,255,.38); }
  .panel > h3:first-child, .card > h3:first-child { margin-top: 0; }
  .grid { display: grid; gap: 14px; }
  .grid.cols-2 { grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-bottom: 16px; }
  .stat { background: var(--surface); -webkit-backdrop-filter: var(--blur); backdrop-filter: var(--blur); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px; box-shadow: var(--shadow); display: flex; flex-direction: column; gap: 2px; position: relative; overflow: hidden; animation: fadeUp .5s both; transition: transform .2s, border-color .2s; }
  .stat::before { content: ''; position: absolute; top: 0; right: 0; left: 0; height: 3px; background: var(--grad); opacity: .85; }
  .stat:hover { transform: translateY(-3px); border-color: rgba(139,123,255,.4); }
  .stat span { font-size: 12.5px; color: var(--muted); }
  .stat b { font-size: 23px; font-weight: 800; line-height: 1.4; }
  .stat small { color: var(--muted); font-size: 12px; }
  .hero { background: linear-gradient(135deg, #3a1fb8 0%, #1a2a8f 45%, #0a6fa3 100%); color: #fff; border-radius: 26px; padding: 26px; margin-bottom: 16px; position: relative; overflow: hidden; box-shadow: 0 14px 44px rgba(70,50,200,.38); animation: fadeUp .5s both; }
  .hero::before { content: ''; position: absolute; left: -60px; top: -80px; width: 260px; height: 260px; border-radius: 50%; background: radial-gradient(circle, rgba(255,79,163,.55), transparent 68%); animation: floaty 9s ease-in-out infinite; }
  .hero::after { content: ''; position: absolute; right: -40px; bottom: -90px; width: 240px; height: 240px; border-radius: 50%; background: radial-gradient(circle, rgba(34,211,255,.5), transparent 68%); animation: floaty 11s ease-in-out infinite reverse; }
  .hero > * { position: relative; z-index: 1; }
  .hero-label { font-size: 13px; color: #cdd6ff; }
  .hero-number { font-size: 46px; font-weight: 800; line-height: 1.3; margin: 2px 0 8px; text-shadow: 0 4px 24px rgba(0,0,0,.3); }
  .hero-unit { font-size: 16px; margin-right: 8px; color: #cdd6ff; font-weight: 500; }
  .hero-meta { display: flex; gap: 26px; flex-wrap: wrap; padding-top: 12px; border-top: 1px solid rgba(255,255,255,.2); }
  .hero-meta div { display: flex; flex-direction: column; }
  .hero-meta b { font-size: 18px; }
  .hero-meta span { font-size: 12px; color: #cdd6ff; }
  .ledger-row { display: flex; justify-content: space-between; gap: 12px; padding: 10px 0; border-bottom: 1px dashed var(--border); }
  .ledger-row:last-child { border-bottom: none; }
  .ledger-row span { color: var(--muted); }
  .row-link { display: flex; align-items: center; gap: 12px; padding: 11px 8px; margin: 0 -8px; border-radius: 12px; text-decoration: none; color: var(--ink); border-bottom: 1px solid var(--border); transition: background .15s; }
  .row-link:hover { background: var(--brand-dim); }
  .row-link:last-child { border-bottom: none; }
  .row-main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
  .row-main small { color: var(--muted); font-size: 12.5px; }
  .chev { color: var(--muted); font-size: 22px; }
  .icon-badge { width: 38px; height: 38px; border-radius: 12px; background: var(--warn-dim); display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
  .empty-note { color: var(--muted); margin: 4px 0 0; }
  .alert { background: var(--warn-dim); color: var(--warn); border: 1px solid rgba(255,179,36,.3); border-radius: 14px; padding: 12px 16px; margin-bottom: 16px; font-weight: 600; font-size: 13.5px; }
  .chart { width: 100%; height: auto; display: block; }
  .chart .bar { fill: var(--brand); filter: drop-shadow(0 0 6px rgba(139,123,255,.55)); transition: opacity .15s; }
  .chart .bar:hover { opacity: .7; }
  .chart text { fill: var(--muted); font-size: 10px; font-family: inherit; }
  .chart .gridline { stroke: var(--border); stroke-width: 1; stroke-dasharray: 3 4; }

  /* ---------- جدول ---------- */
  table { display: block; max-width: 100%; overflow-x: auto; border-collapse: collapse; background: var(--surface); -webkit-backdrop-filter: var(--blur); backdrop-filter: var(--blur); border-radius: 16px; border: 1px solid var(--border); margin-bottom: 14px; box-shadow: var(--shadow); }
  th, td { padding: 11px 14px; text-align: right; border-bottom: 1px solid var(--border); font-size: 13.5px; white-space: nowrap; vertical-align: middle; }
  th { background: var(--surface-2); color: var(--muted); font-weight: 600; font-size: 12.5px; }
  tr:last-child td { border-bottom: none; }
  tbody tr { transition: background .15s; }
  tbody tr:hover td { background: var(--brand-dim); }
  td.wrap { white-space: normal; min-width: 180px; }
  @media (max-width: 700px) {
    table.rt { display: block; border: none; background: none; box-shadow: none; overflow: visible; -webkit-backdrop-filter: none; backdrop-filter: none; }
    table.rt thead { display: none; }
    table.rt tbody, table.rt tr { display: block; }
    table.rt tr { background: var(--surface); -webkit-backdrop-filter: var(--blur); backdrop-filter: var(--blur); border: 1px solid var(--border); border-radius: 16px; margin-bottom: 10px; padding: 6px 14px; box-shadow: var(--shadow); }
    table.rt td { display: flex; justify-content: space-between; align-items: center; gap: 14px; border: none; padding: 7px 0; white-space: normal; text-align: left; }
    table.rt td::before { content: attr(data-label); color: var(--muted); font-size: 12px; flex-shrink: 0; text-align: right; }
    table.rt tbody tr:hover td { background: none; }
  }

  /* ---------- فرم‌ها ---------- */
  input[type=text], input[type=number], input[type=password], input[type=search], textarea, select {
    background: var(--surface-2); border: 1.5px solid var(--border); color: var(--ink); border-radius: 13px; padding: 10px 14px; font-size: 14.5px; width: 100%; font-family: inherit; transition: border-color .15s, box-shadow .15s; }
  input:focus, textarea:focus, select:focus { outline: none; border-color: var(--brand); box-shadow: 0 0 0 4px var(--brand-dim); }
  textarea { min-height: 110px; resize: vertical; }
  label { display: block; margin: 14px 0 6px; font-size: 13px; color: var(--muted); font-weight: 600; }
  input[type=radio], input[type=checkbox] { width: auto; accent-color: var(--brand); }
  .reorder-row { display: flex; align-items: flex-end; gap: 8px; }
  .reorder-row > div:first-child { flex: 1; min-width: 0; }
  .reorder-row label { margin-top: 0; }
  .reorder-arrows { display: flex; flex-direction: column; gap: 4px; margin-bottom: 1px; }
  .reorder-arrows button { padding: 4px 11px; font-size: 11px; line-height: 1.4; }
  button, .btn { background: var(--grad); color: var(--brand-ink); border: 1.5px solid transparent; border-radius: 13px; padding: 9px 18px; font-size: 14px; font-weight: 700; cursor: pointer; font-family: inherit; text-decoration: none; display: inline-block; line-height: 1.7; box-shadow: var(--glow); transition: transform .15s, filter .15s, box-shadow .15s; }
  button:hover, .btn:hover { filter: brightness(1.1); transform: translateY(-1px); }
  button:active, .btn:active { transform: translateY(0) scale(.98); }
  button.secondary, .btn.secondary { background: var(--surface-2); color: var(--ink); border-color: var(--border); box-shadow: none; }
  button.secondary:hover, .btn.secondary:hover { border-color: var(--brand); filter: none; }
  button.danger, .btn.danger { background: var(--danger-dim); color: var(--danger); border-color: transparent; box-shadow: none; }
  button.danger:hover, .btn.danger:hover { background: var(--danger); color: #fff; filter: none; }
  button.sm, .btn.sm { padding: 4px 12px; font-size: 12.5px; border-radius: 10px; }
  .btn.block, button.block { width: 100%; text-align: center; }
  .badge { padding: 2px 11px; border-radius: 999px; font-size: 12px; font-weight: 700; display: inline-block; white-space: nowrap; }
  .badge.on, .badge.answered, .badge.approved { background: var(--ok-dim); color: var(--ok); }
  .badge.off, .badge.rejected { background: var(--danger-dim); color: var(--danger); }
  .badge.open, .badge.pending { background: var(--warn-dim); color: var(--warn); }
  .badge.closed, .badge.expired { background: var(--surface-2); color: var(--muted); }
  button.tgl { min-width: 112px; padding: 6px 14px; font-size: 13px; border-radius: 999px; box-shadow: none; white-space: nowrap; }
  button.tgl.on { background: var(--ok-dim); color: var(--ok); border-color: var(--ok); }
  button.tgl.off { background: var(--danger-dim); color: var(--danger); border-color: transparent; }
  button.tgl:hover { filter: brightness(1.1); }
  .flash { background: var(--ok-dim); color: var(--ok); padding: 11px 16px; border-radius: 14px; margin-bottom: 12px; font-size: 14px; font-weight: 600; border: 1px solid rgba(61,220,151,.25); animation: fadeUp .35s both; }
  .flash.error { background: var(--danger-dim); color: var(--danger); border-color: rgba(255,123,147,.3); }
  .flex { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .pager { display: flex; gap: 8px; margin: 14px 0; flex-wrap: wrap; }
  .chips-row { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
  .pill { padding: 6px 14px; border-radius: 999px; border: 1px solid var(--border); background: var(--surface); color: var(--ink); text-decoration: none; font-size: 13px; font-weight: 600; transition: .15s; }
  .pill:hover { border-color: var(--brand); }
  .pill.active { background: var(--grad); color: #fff; border-color: transparent; box-shadow: var(--glow); }
  .kv { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 14px; }
  .kv div span { display: block; font-size: 12px; color: var(--muted); }
  .kv div b { font-size: 15px; }
  .act { display: inline-flex; align-items: center; gap: 7px; }
  .act i { width: 9px; height: 9px; border-radius: 50%; background: var(--border); display: inline-block; flex-shrink: 0; }
  .act i.online { background: #2fd48a; box-shadow: 0 0 0 4px var(--ok-dim); }
  .act i.today { background: var(--sun); }
  .act i.old { background: var(--muted); opacity: .5; }
  .switch-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--border); }
  .switch-row:last-child { border-bottom: none; }
  .savebar { position: sticky; bottom: calc(var(--nav-h) + env(safe-area-inset-bottom, 0px) + 10px); z-index: 5; padding: 10px 0; }

  /* ---------- نمایش اطلاعات ورود فروشنده ---------- */
  .secret { display: inline-flex; align-items: center; gap: 6px; max-width: 100%; }
  .secret code { min-width: 74px; text-align: center; letter-spacing: .4px; user-select: all; }
  .secret code.masked { letter-spacing: 2px; color: var(--muted); user-select: none; }
  .mini { width: 30px; height: 30px; padding: 0; border-radius: 9px; font-size: 14px; line-height: 1; background: var(--surface-2); color: var(--ink); border: 1px solid var(--border); box-shadow: none; display: inline-flex; align-items: center; justify-content: center; }
  .mini:hover { border-color: var(--brand); background: var(--brand-dim); filter: none; }
  .cred-box { background: var(--surface-2); border: 1px dashed var(--border); border-radius: 16px; padding: 14px 16px; margin-bottom: 14px; display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); }
  .cred-box > div > span { display: block; font-size: 12px; color: var(--muted); margin-bottom: 3px; }
  .search-box { position: relative; flex: 1; min-width: 220px; }
  .search-box input { padding-right: 40px; }
  .search-box::before { content: '🔎'; position: absolute; right: 13px; top: 50%; transform: translateY(-50%); font-size: 14px; pointer-events: none; opacity: .75; }
  .toast { position: fixed; bottom: 96px; left: 50%; transform: translate(-50%, 20px); background: var(--grad); color: #fff; padding: 10px 22px; border-radius: 999px; font-weight: 700; font-size: 13.5px; box-shadow: var(--glow); opacity: 0; pointer-events: none; transition: .3s; z-index: 99; }
  .toast.show { opacity: 1; transform: translate(-50%, 0); }

  /* ---------- ورود ---------- */
  .login-wrap { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px 16px; position: relative; overflow: hidden; }
  .orb { position: absolute; border-radius: 50%; filter: blur(60px); opacity: .55; animation: floaty 12s ease-in-out infinite; pointer-events: none; }
  .orb.o1 { width: 340px; height: 340px; background: var(--g1); top: -80px; right: -60px; }
  .orb.o2 { width: 300px; height: 300px; background: var(--g2); bottom: -60px; left: -40px; animation-delay: -4s; }
  .orb.o3 { width: 220px; height: 220px; background: var(--g3); top: 55%; right: 30%; opacity: .3; animation-delay: -8s; }
  .login-box { position: relative; z-index: 1; background: var(--surface); -webkit-backdrop-filter: blur(22px) saturate(150%); backdrop-filter: blur(22px) saturate(150%); border: 1px solid var(--border); border-radius: 28px; padding: 32px 28px 28px; width: 100%; max-width: 410px; box-shadow: 0 24px 70px rgba(30,20,120,.35); animation: fadeUp .7s both; }
  .login-logo { display: flex; flex-direction: column; align-items: center; gap: 10px; margin-bottom: 8px; }
  .login-logo .mark { width: 64px; height: 64px; border-radius: 20px; }
  .login-logo .mark::after { inset: 15px; border-width: 3.5px; }
  .login-box h2 { margin: 0; font-size: 24px; text-align: center; }
  .login-box .sub { text-align: center; color: var(--muted); font-size: 13px; margin-bottom: 8px; }

  /* ======================================================================
     بازطراحی: خوانایی بیشتر + استیکرها و شکل‌های تزئینی
     ====================================================================== */
  :root {
    --muted: #46547f; --ink: #0d1433; --border: rgba(80,90,200,.22);
    --surface: #ffffff; --surface-2: #eef1ff;
    --shadow: 0 1px 2px rgba(20,24,70,.06), 0 8px 24px rgba(60,60,160,.10);
  }
  [data-theme="dark"] {
    --bg: #070b1c; --surface: #111a3a; --surface-2: #1a2652; --border: rgba(150,170,255,.24);
    --ink: #f5f7ff; --muted: #b9c4e8;
    --ok: #45e6a1; --warn: #ffd072; --danger: #ff8fa5;
    --shadow: 0 2px 4px rgba(0,0,0,.35), 0 10px 28px rgba(0,0,0,.30);
  }
  body { font-size: 15.5px; line-height: 1.95; }
  body::after { display: none; }                         /* شبکه‌ی پس‌زمینه حواس‌پرتی می‌آورد */
  .panel, .card, .stat, table, .login-box { -webkit-backdrop-filter: none; backdrop-filter: none; }
  .card, .panel { padding: 20px 22px; border-radius: 22px; }
  .card h3, .panel h3 { font-size: 18px; }
  .card > h3:first-child::before, .panel > h3:first-child::before {
    content: ''; display: inline-block; width: 6px; height: 1.15em; border-radius: 6px; margin-left: 10px; vertical-align: -3px;
    background: var(--grad); }
  .muted, small.muted { font-size: 13.5px; }
  small { font-size: 13px; }
  label { font-size: 14px; color: var(--ink); opacity: .85; margin: 16px 0 7px; }
  input[type=text], input[type=number], input[type=password], input[type=search], textarea, select {
    font-size: 15.5px; padding: 12px 16px; border-radius: 15px; border-width: 2px; }
  button, .btn { font-size: 15px; padding: 10px 22px; border-radius: 15px; }
  button.sm, .btn.sm { font-size: 13.5px; padding: 6px 15px; border-radius: 12px; }
  button.secondary, .btn.secondary { border-width: 2px; }
  th { font-size: 13.5px; padding: 13px 16px; color: var(--ink); opacity: .8; }
  td { font-size: 14.5px; padding: 13px 16px; }
  tbody tr:nth-child(even) td { background: rgba(120,135,255,.06); }
  tbody tr:hover td { background: var(--brand-dim); }
  table { border-radius: 20px; border-width: 1.5px; }
  .badge { font-size: 12.5px; padding: 3px 13px; }
  .badge::before { content: ''; display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: currentColor; margin-left: 7px; }
  .flash { font-size: 15px; padding: 13px 18px; border-radius: 16px; }

  /* ---- استیکرهای منو ---- */
  .stk { display: inline-grid; place-items: center; width: 36px; height: 36px; border-radius: 12px; font-size: 19px; line-height: 1;
         background: var(--c, rgba(139,123,255,.25)); flex-shrink: 0; transition: transform .2s; font-style: normal; }
  .side-link { padding: 8px 12px; font-size: 15px; gap: 12px; }
  .side-link:hover .stk { transform: rotate(-8deg) scale(1.12); }
  .side-link.active .stk { background: rgba(255,255,255,.26); }
  .nav-group { font-size: 12px; opacity: .65; }
  .bottom-nav a .stk { width: 40px; height: 30px; border-radius: 11px; font-size: 18px; }
  .bottom-nav a.active .stk { background: var(--grad); box-shadow: var(--glow); }
  .drawer a.dl { padding: 10px 2px; font-size: 15.5px; }

  /* ---- عنوان صفحه با استیکر ---- */
  .title-row { display: flex; align-items: center; gap: 14px; }
  .title-stk { display: grid; place-items: center; width: 54px; height: 54px; border-radius: 18px; font-size: 28px;
               background: var(--grad); box-shadow: var(--glow); transform: rotate(-6deg); flex-shrink: 0; }
  .page-title { background: none; -webkit-text-fill-color: var(--ink); color: var(--ink); font-size: 26px; }

  /* ---- کارت‌های آمار: دایره‌ی تزئینی و عدد درشت‌تر ---- */
  .stat { padding: 16px 18px; border-radius: 22px; }
  .stat::after { content: ''; position: absolute; left: -22px; bottom: -30px; width: 96px; height: 96px; border-radius: 50%;
                 background: var(--grad); opacity: .14; pointer-events: none; }
  .stat:nth-child(3n+2)::after { background: linear-gradient(135deg, var(--g3), var(--g1)); border-radius: 30% 70% 60% 40%; }
  .stat:nth-child(3n)::after { background: linear-gradient(135deg, var(--g2), var(--ok)); border-radius: 22px; transform: rotate(18deg); }
  .stat span { font-size: 13.5px; color: var(--ink); opacity: .8; }
  .stat b { font-size: 27px; }
  .hero { border-radius: 28px; }
  .hero-number { font-size: 50px; }

  /* ---- اشکال شناور تو پس‌زمینه‌ی ورود ---- */
  .fl { position: absolute; font-size: 38px; z-index: 1; opacity: .9; animation: floaty 9s ease-in-out infinite; pointer-events: none;
        filter: drop-shadow(0 6px 14px rgba(0,0,0,.35)); }
  .fl.f1 { top: 12%; right: 12%; } .fl.f2 { top: 20%; left: 10%; animation-delay: -3s; font-size: 46px; }
  .fl.f3 { bottom: 14%; right: 16%; animation-delay: -5s; } .fl.f4 { bottom: 20%; left: 14%; animation-delay: -7s; font-size: 34px; }
  .login-box { border-radius: 30px; }
  @media (max-width: 700px) {
    .title-stk { width: 46px; height: 46px; font-size: 24px; border-radius: 15px; }
    .page-title { font-size: 22px; }
    .fl { font-size: 28px; }
  }
  @media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; transition: none !important; } html { scroll-behavior: auto; } }
</style>
</head>
<body>
__BODY__
<script>
  function toggleTheme() {
    var t = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', t);
    try { localStorage.setItem('sky-theme', t); } catch (e) {}
  }
  function toast(msg) {
    var t = document.getElementById('toast');
    if (!t) { t = document.createElement('div'); t.id = 'toast'; t.className = 'toast'; document.body.appendChild(t); }
    t.textContent = msg; t.classList.add('show');
    clearTimeout(window.__tt); window.__tt = setTimeout(function () { t.classList.remove('show'); }, 1800);
  }
  function copyText(text) {
    function fallback() {
      var ta = document.createElement('textarea'); ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); toast('✅ کپی شد'); } catch (e) { toast('⚠️ کپی نشد'); }
      document.body.removeChild(ta);
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function () { toast('✅ کپی شد'); }, fallback);
    } else { fallback(); }
  }
  function copyFrom(btn) { copyText(btn.getAttribute('data-copy') || ''); }
  function revealSecret(btn) {
    var box = btn.closest('.secret'), code = box.querySelector('code');
    var hidden = code.classList.contains('masked');
    if (hidden) { code.textContent = code.getAttribute('data-v'); code.classList.remove('masked'); btn.textContent = '🙈'; }
    else { code.textContent = '••••••••'; code.classList.add('masked'); btn.textContent = '👁'; }
  }
  function filterRows(inp, tableId) {
    var q = inp.value.trim().toLowerCase();
    document.querySelectorAll('#' + tableId + ' tbody tr').forEach(function (tr) {
      tr.style.display = (!q || tr.textContent.toLowerCase().indexOf(q) > -1) ? '' : 'none';
    });
  }
  function genPw(id) {
    var c = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789', a = new Uint32Array(12), s = '', i;
    crypto.getRandomValues(a);
    for (i = 0; i < 12; i++) s += c[a[i] % c.length];
    var el = document.getElementById(id); el.value = s; el.type = 'text';
  }
</script>
</body>
</html>
"""

ICONS = {
    "dashboard": '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-3.5 3.2-5.5 6.5-5.5s5.9 2 6.5 5.5"/><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14.7c2 .6 3.3 2.3 3.6 5.3"/>',
    "tickets": '<path d="M4 5h16v11H9l-5 4z"/>',
    "resellers": '<path d="M3 9l2-5h14l2 5"/><path d="M4 9v11h16V9"/><path d="M9 20v-6h6v6"/>',
    "discounts": '<path d="M20 12l-8 8-9-9V3h8z"/><circle cx="7.5" cy="7.5" r="1.3"/>',
    "topups": '<rect x="2.5" y="5" width="19" height="14" rx="2.5"/><path d="M2.5 10h19M6.5 15h4"/>',
    "broadcast": '<path d="M3 11v2a1 1 0 0 0 1 1h3l6 4V6L7 10H4a1 1 0 0 0-1 1z"/><path d="M17 8.5a5 5 0 0 1 0 7"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    "texts": '<path d="M4 6h16M4 12h16M4 18h10"/>',
    "appearance": '<circle cx="13.5" cy="6.5" r="1.5"/><circle cx="17.5" cy="10.5" r="1.5"/><circle cx="8.5" cy="7.5" r="1.5"/><circle cx="6.5" cy="12.5" r="1.5"/><path d="M12 2a10 10 0 1 0 0 20c1.1 0 2-.9 2-2 0-.5-.2-1-.5-1.3-.3-.4-.5-.8-.5-1.3 0-1.1.9-2 2-2h2.4a4.6 4.6 0 0 0 4.6-4.6C22 6 17.5 2 12 2z"/>',
    "crypto": '<circle cx="12" cy="12" r="9"/><path d="M9.5 8.5h4a1.8 1.8 0 0 1 0 3.6H9.5m0 0h4.4a1.8 1.8 0 0 1 0 3.6H9.5M9.5 7v10M12 6v2m0 8v2"/>',
    "salenotify": '<path d="M4 4h16v12H8l-4 4z"/><path d="M8 9h8M8 12h5"/>',
    "more": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5M21 12H9"/>',
}


STICKERS = {
    "dashboard": ("🏠", "rgba(109,74,255,.35)"), "users": ("👥", "rgba(34,211,255,.30)"),
    "tickets": ("🎫", "rgba(255,179,36,.32)"), "resellers": ("🏪", "rgba(255,95,174,.30)"),
    "discounts": ("🏷️", "rgba(61,220,151,.30)"), "topups": ("💰", "rgba(255,196,87,.34)"),
    "crypto": ("🪙", "rgba(255,150,60,.32)"), "broadcast": ("📣", "rgba(255,95,174,.30)"),
    "salenotify": ("📢", "rgba(34,211,255,.30)"), "settings": ("⚙️", "rgba(139,123,255,.35)"),
    "texts": ("✍️", "rgba(61,220,151,.30)"), "appearance": ("🎨", "rgba(255,95,174,.32)"), "custombtn": ("🔘", "rgba(34,211,255,.30)"),
    "orders": ("🧾", "rgba(34,211,255,.30)"), "channels": ("📡", "rgba(139,123,255,.35)"),
    "backup": ("💾", "rgba(61,220,151,.30)"), "finance": ("📊", "rgba(255,196,87,.34)"),
    "donito": ("⚡", "rgba(255,196,87,.36)"), "plans": ("📦", "rgba(255,150,60,.32)"),
    "alerts": ("⏰", "rgba(255,95,174,.30)"), "envvars": ("🔑", "rgba(139,123,255,.35)"),
    "more": ("☰", "rgba(255,255,255,.14)"), "logout": ("🚪", "rgba(255,123,147,.30)"),
}


def icon(name):
    if name in STICKERS:
        emo, col = STICKERS[name]
        return f'<span class="stk" style="--c:{col}" aria-hidden="true">{emo}</span>'
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>')


NAV = [
    ("نمای کلی", [("dashboard", "داشبورد", "dashboard")]),
    ("مشتریان", [("users", "کاربران", "users"), ("tickets", "تیکت‌ها", "tickets"), ("resellers", "فروشنده‌ها", "resellers_page")]),
    ("فروش", [("discounts", "کدهای تخفیف", "discount_codes"), ("topups", "شارژهای کیف پول", "topups_page"),
              ("crypto", "رمزارزها", "crypto_page"), ("broadcast", "پیام همگانی", "broadcast"),
              ("salenotify", "اعلان فروش", "sale_notify_page")]),
    ("ربات", [("settings", "تنظیمات ربات", "settings_page"), ("texts", "متن‌های ربات", "texts_page"),
              ("appearance", "دکمه‌ها و ظاهر", "appearance_page"),
              ("custombtn", "دکمه‌های سفارشی", "custom_buttons_page")]),
]
BOTTOM = [("dashboard", "داشبورد", "dashboard"), ("users", "کاربران", "users"), ("tickets", "تیکت‌ها", "tickets")]


def render_sidebar(active):
    bot = get_bot_info()
    if bot and bot.get("username"):
        status = f'<span class="dot"></span>@{esc(bot.get("username"))}'
    elif not BOT_TOKEN:
        status = '<span class="dot off"></span>توکن ربات تنظیم نشده'
    else:
        status = '<span class="dot off"></span>وضعیت ربات نامشخص'
    out = (f'<aside class="sidebar"><div class="brand"><div class="mark"></div><div><b>SkyTunnel</b>'
           f'<span>{status}</span></div></div>')
    for group, items in NAV:
        out += f'<div class="nav-group">{group}</div>'
        for key, label, endpoint in items:
            cls = "side-link active" if active == key else "side-link"
            out += f'<a class="{cls}" href="{url_for(endpoint)}">{icon(key)}{label}</a>'
    out += (f'<div class="side-foot"><button type="button" onclick="toggleTheme()">🌗 تم</button>'
            f'<a href="{url_for("logout")}">خروج</a></div></aside>')
    return out


def render_bottom(active):
    links = ""
    for key, label, endpoint in BOTTOM:
        cls = "active" if active == key else ""
        links += f'<a class="{cls}" href="{url_for(endpoint)}">{icon(key)}{label}</a>'
    more_active = "active" if active not in [b[0] for b in BOTTOM] else ""
    links += f'<a class="{more_active}" href="#more">{icon("more")}بیشتر</a>'
    drawer = '<div id="more" class="drawer-overlay"><div class="drawer"><div class="handle"></div>'
    for group, items in NAV:
        drawer += f"<h4>{group}</h4>"
        for key, label, endpoint in items:
            drawer += f'<a class="dl" href="{url_for(endpoint)}">{icon(key)}{label}</a>'
    drawer += (f'<h4>حساب</h4><a class="dl" href="#" onclick="toggleTheme();return false;">🌗 تغییر تم (روشن/تیره)</a>'
               f'<a class="dl" href="{url_for("logout")}">{icon("logout")}خروج از پنل</a></div></div>')
    return f'<nav class="bottom-nav"><div class="nav-inner">{links}</div></nav>{drawer}'


def render_topbar():
    return (f'<header class="topbar"><div class="brand"><div class="mark"></div><div><b>SkyTunnel</b></div></div>'
            f'<div class="flex" style="gap:8px;"><button type="button" class="icon-btn" onclick="toggleTheme()" aria-label="تغییر تم">🌗</button>'
            f'<a class="icon-btn" href="{url_for("logout")}" aria-label="خروج">⎋</a></div></header>')


def inject_csrf(html):
    token = csrf_token()
    return re.sub(r'(<form\b[^>]*\bmethod="post"[^>]*>)',
                  lambda m: m.group(1) + f'<input type="hidden" name="csrf" value="{token}">', html)


def render_page(title, active, content_html, actions=""):
    flashes = "".join(
        f'<div class="flash{" error" if m.startswith("⚠️") else ""}">{esc(m)}</div>' for m in get_flashed_messages())
    body = f"""
    {render_sidebar(active)}
    <div class="shell">
      {render_topbar()}
      <main class="app">
        <div class="page-head"><div class="title-row">{('<span class="title-stk">' + STICKERS[active][0] + '</span>') if active in STICKERS and active not in ('more', 'logout') else ''}<h2 class="page-title">{title}</h2></div><div class="flex">{actions}</div></div>
        {flashes}
        {content_html}
      </main>
      {render_bottom(active)}
    </div>
    """
    return BASE_HTML.replace("__BODY__", inject_csrf(body))


def bar_chart(points, fmt, color_class="bar"):
    """points: [(label, value)] — نمودار میله‌ای SVG ساده (بدون کتابخانه‌ی بیرونی)."""
    W, H, PAD_B, PAD_T = 640, 170, 22, 8
    n = len(points)
    mx = max([v for _l, v in points] + [1])
    slot = W / n
    bw = slot * 0.62
    parts = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" dir="ltr">']
    for g in (0.25, 0.5, 0.75, 1.0):
        y = PAD_T + (H - PAD_B - PAD_T) * (1 - g)
        parts.append(f'<line class="gridline" x1="0" x2="{W}" y1="{y:.1f}" y2="{y:.1f}"/>')
    for i, (label, v) in enumerate(points):
        h = (H - PAD_B - PAD_T) * (v / mx)
        x = i * slot + (slot - bw) / 2
        y = H - PAD_B - h
        parts.append(f'<rect class="{color_class}" x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{max(h, 1.5):.1f}" rx="4">'
                     f'<title>{esc(label)}: {esc(fmt(v))}</title></rect>')
        if i % 2 == 0 or n <= 8:
            parts.append(f'<text x="{x + bw / 2:.1f}" y="{H - 6}" text-anchor="middle">{esc(label)}</text>')
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# صفحات
# ---------------------------------------------------------------------------

LOGIN_HTML = """
<div class="login-wrap">
  <div class="orb o1"></div><div class="orb o2"></div><div class="orb o3"></div>
  <span class="fl f1">🚀</span><span class="fl f2">🛡️</span><span class="fl f3">⚡</span><span class="fl f4">🔐</span>
  <form method="post" class="login-box">
    <div class="login-logo"><div class="mark"></div><h2>SkyTunnel</h2></div>
    <div class="sub">ورود به پنل مدیریت</div>
    __ERROR__
    <label for="username">نام کاربری</label>
    <input id="username" type="text" name="username" autocapitalize="off" autocorrect="off" spellcheck="false" autocomplete="username" required>
    <label for="password">رمز عبور</label>
    <div class="flex" style="flex-wrap:nowrap;gap:8px;">
      <input id="password" type="password" name="password" autocapitalize="off" autocorrect="off" spellcheck="false" autocomplete="current-password" required>
      <button type="button" class="mini" style="width:44px;height:44px;flex-shrink:0;" aria-label="نمایش رمز"
              onclick="var p=document.getElementById('password');p.type=p.type==='password'?'text':'password';">👁</button>
    </div>
    <div style="margin-top:22px;"><button type="submit" class="block">ورود به پنل ✦</button></div>
  </form>
</div>
"""


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        if login_locked():
            error = "تعداد تلاش‌های ناموفق زیاد بود؛ چند دقیقه‌ی دیگه دوباره امتحان کنید."
        else:
            u = request.form.get("username", "").strip()
            p = request.form.get("password", "").strip()
            if safe_equal(u, PANEL_USERNAME.strip()) and safe_equal(p, PANEL_PASSWORD.strip()):
                LOGIN_FAILS.pop(_client_ip(), None)
                session.clear()
                session["logged_in"] = True
                session.permanent = True
                return redirect(url_for("dashboard"))
            login_failed()
            error = "نام کاربری یا رمز عبور اشتباه است."
    err_html = f'<div class="flash error">{esc(error)}</div>' if error else ""
    return BASE_HTML.replace("__BODY__", LOGIN_HTML.replace("__ERROR__", err_html))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- داشبورد ----------

@app.route("/")
@login_required
def dashboard():
    s = get_dashboard_stats()
    x = get_extra_stats()
    recent = get_users_page(offset=0, limit=7, sort="active")

    open_tickets, pending_topups = s["open_tickets"], s["pending_topups"]
    today_topup = 0
    try:
        _today = datetime.now(TEHRAN).date()
        for _r in fin_rows(2):
            _d = parse_ts(_r[5])
            if _r[3] == "approved" and _d and _d.astimezone(TEHRAN).date() == _today:
                today_topup += int(_r[2] or 0)
    except Exception as e:
        print("⚠️ today_topup:", e)
    revenue = int(s["total_revenue"] or 0)
    configs_sold = int(s["total_configs"] or 0)
    avg_price = revenue // configs_sold if configs_sold else 0

    attention = ""
    if open_tickets > 0:
        attention += f"""
        <a href="{url_for('tickets')}" class="row-link">
          <span class="icon-badge">🎧</span>
          <span class="row-main"><b>تیکت‌های پاسخ‌نداده</b><small>{open_tickets} تیکت در انتظار پاسخ</small></span>
          <span class="chev">‹</span></a>"""
    if pending_topups > 0:
        attention += f"""
        <a href="{url_for('topups_page')}" class="row-link">
          <span class="icon-badge">💳</span>
          <span class="row-main"><b>شارژهای در انتظار تایید</b><small>{pending_topups} درخواست شارژ کیف پول</small></span>
          <span class="chev">‹</span></a>"""
    if not attention:
        attention = '<p class="empty-note">چیزی برای رسیدگی فوری نیست. 🎉</p>'

    def day_label(d):
        jy, jm, jd = g2j(d.year, d.month, d.day)
        return fa(f"{jm:02d}/{jd:02d}")

    rev_chart = bar_chart([(day_label(d), v) for d, v, _c in x["rev"]], lambda v: f"{int(v):,} تومان")
    join_chart = bar_chart([(day_label(d), v) for d, v in x["joins"]], lambda v: f"{v} نفر")
    rev14 = sum(v for _d, v, _c in x["rev"])
    orders14 = sum(c for _d, _v, c in x["rev"])

    recent_html = ""
    for user_id, username, first_name, wallet, joined_at, last_active, last_action in recent:
        state = activity_state(last_active)
        recent_html += f"""
        <a href="{url_for('user_detail', user_id=user_id)}" class="row-link">
          <span class="act"><i class="{state}"></i></span>
          <span class="row-main"><span>{user_display(first_name, username, user_id)}</span>
            <small>{esc(action_label(last_action))}</small></span>
          <small class="muted">{rel_time(last_active)}</small>
        </a>"""
    if not recent_html:
        recent_html = '<p class="empty-note">هنوز کاربری ثبت نشده.</p>'

    warn = ""
    if not BOT_TOKEN:
        warn += '<div class="alert">⚠️ متغیر <code>BOT_TOKEN</code> تنظیم نشده؛ ارسال پیام (پاسخ تیکت، پیام همگانی) کار نمی‌کنه.</div>'

    content = f"""
    {warn}
    <section class="hero">
      <div class="hero-label">درآمد کل فروش</div>
      <div class="hero-number num">{revenue:,}<span class="hero-unit">تومان</span></div>
      <div class="hero-meta">
        <div><b class="num">{s['total_users']:,}</b><span>کاربر</span></div>
        <div><b class="num">{configs_sold:,}</b><span>کانفیگ فروخته‌شده</span></div>
        <div><b class="num">{float(s['total_gb'] or 0):,.1f}</b><span>گیگ فروخته‌شده</span></div>
      </div>
    </section>

    <div class="stats">
      <div class="stat"><span>🟢 آنلاین (۵ دقیقه اخیر)</span><b class="num">{x['online_now']:,}</b></div>
      <div class="stat"><span>فعال در ۲۴ ساعت اخیر</span><b class="num">{x['active_24h']:,}</b></div>
      <div class="stat"><span>عضو جدید ۷ روز اخیر</span><b class="num">{x['new_7d']:,}</b></div>
      <div class="stat"><span>مجموع کیف‌پول کاربران</span><b class="num">{int(s['total_wallet'] or 0):,}</b><small>تومان</small></div>
      <div class="stat"><span>میانگین قیمت هر کانفیگ</span><b class="num">{avg_price:,}</b><small>تومان</small></div>
      <a class="stat" href="{url_for('finance_page')}" style="text-decoration:none;color:inherit;"><span>💎 شارژ امروز (مرکز مالی)</span><b class="num">{today_topup:,}</b><small>تومان ›</small></a>
    </div>

    <div class="grid cols-2">
      <div class="card"><h3>فروش ۱۴ روز اخیر</h3>
        <small class="muted num">{rev14:,} تومان در {orders14:,} سفارش</small>{rev_chart}</div>
      <div class="card"><h3>کاربران جدید ۱۴ روز اخیر</h3>
        <small class="muted num">{x['new_7d']:,} نفر در ۷ روز اخیر</small>{join_chart}</div>
    </div>

    <div class="grid cols-2">
      <div class="card"><h3>نیاز به توجه</h3>{attention}</div>
      <div class="card"><h3>آخرین فعالیت کاربران</h3>{recent_html}
        <div style="margin-top:10px;"><a class="btn secondary sm" href="{url_for('users')}">همه‌ی کاربران ›</a></div></div>
    </div>
    """
    return render_page("پیشخوان", "dashboard", content)


# ---------- کاربران ----------

@app.route("/users")
@login_required
def users():
    search = request.args.get("q", "").strip()
    sort = request.args.get("sort", "active")
    if sort not in USER_SORTS:
        sort = "active"
    only_recent = request.args.get("recent") == "1"
    only_banned = request.args.get("banned") == "1"
    offset = max(0, to_int(request.args.get("offset"), 0))
    total = get_users_count(search or None, only_recent, only_banned)
    rows = get_users_page(offset=offset, search=search or None, sort=sort, only_recent=only_recent, only_banned=only_banned)
    banned_ids = get_banned_ids([r[0] for r in rows])

    rows_html = ""
    for user_id, username, first_name, wallet, joined_at, last_active, last_action in rows:
        state = activity_state(last_active)
        is_b = user_id in banned_ids
        b_badge = ' <span class="badge off">مسدود</span>' if is_b else ""
        rows_html += f"""
        <tr>
          <td data-label="کاربر" class="wrap">{user_display(first_name, username, user_id)}{b_badge}<br><small class="muted num">{user_id}</small></td>
          <td data-label="موجودی" class="num">{int(wallet or 0):,} تومان</td>
          <td data-label="آخرین فعالیت"><span class="act" title="{fmt_dt(last_active)}"><i class="{state}"></i>{rel_time(last_active)}</span></td>
          <td data-label="آخرین دستور" class="wrap">{esc(action_label(last_action))}</td>
          <td data-label="عضویت"><small class="muted">{fmt_dt(joined_at, with_time=False)}</small></td>
          <td data-label="تغییر موجودی">
            <form method="post" action="{url_for('adjust_wallet')}" class="flex">
              <input type="hidden" name="user_id" value="{user_id}"><input type="hidden" name="next" value="list">
              <input type="number" name="amount" placeholder="مبلغ" style="width:110px;" min="1" required>
              <button type="submit" name="sign" value="1">➕</button>
              <button type="submit" name="sign" value="-1" class="secondary">➖</button>
            </form></td>
          <td data-label=""><div class="flex"><a class="btn secondary sm" href="{url_for('user_detail', user_id=user_id)}">مشاهده</a>
            <form method="post" action="{url_for('user_ban', user_id=user_id)}" style="margin:0;"
                  {'' if is_b else 'onsubmit="return confirm(' + chr(39) + 'این کاربر مسدود بشه؟' + chr(39) + ');"'}>
              <input type="hidden" name="action" value="{'unban' if is_b else 'ban'}"><input type="hidden" name="next" value="list">
              <button type="submit" class="{'' if is_b else 'danger '}sm">{'✅ آزاد' if is_b else '⛔ مسدود'}</button></form></div></td>
        </tr>"""

    def link(**kw):
        params = {"q": search, "sort": sort, "recent": "1" if only_recent else "", "banned": "1" if only_banned else ""}
        params.update(kw)
        return url_for("users", **{k: v for k, v in params.items() if v not in ("", None)})

    pager = ""
    if offset > 0:
        pager += f'<a class="btn secondary" href="{link(offset=max(0, offset - USERS_PAGE_SIZE))}">‹ صفحه قبل</a>'
    if offset + USERS_PAGE_SIZE < total:
        pager += f'<a class="btn secondary" href="{link(offset=offset + USERS_PAGE_SIZE)}">صفحه بعد ›</a>'

    sorts = [("active", "آخرین فعالیت"), ("joined", "جدیدترین عضو"), ("wallet", "بیشترین موجودی")]
    pills = "".join(f'<a class="pill {"active" if sort == k else ""}" href="{link(sort=k, offset="")}">{label}</a>' for k, label in sorts)
    pills += f'<a class="pill {"active" if only_recent else ""}" href="{link(recent="" if only_recent else "1", offset="")}">🟢 فعال در ۲۴ ساعت اخیر</a>'
    pills += f'<a class="pill {"active" if only_banned else ""}" href="{link(banned="" if only_banned else "1", offset="")}">⛔ مسدودها</a>'

    content = f"""
    <div class="card">
      <form method="get" class="flex">
        <input type="hidden" name="sort" value="{esc(sort)}">
        {'<input type="hidden" name="recent" value="1">' if only_recent else ''}
        {'<input type="hidden" name="banned" value="1">' if only_banned else ''}
        <input type="text" name="q" placeholder="جستجو با آیدی، یوزرنیم یا نام..." value="{esc(search)}" style="flex:1;min-width:200px;">
        <button type="submit">جستجو</button>
      </form>
    </div>
    <div class="chips-row">{pills}</div>
    <table class="rt">
      <thead><tr><th>کاربر</th><th>موجودی</th><th>آخرین فعالیت</th><th>آخرین دستور</th><th>عضویت</th><th>تغییر موجودی</th><th></th></tr></thead>
      <tbody>{rows_html if rows_html else '<tr><td colspan="7">کاربری یافت نشد.</td></tr>'}</tbody>
    </table>
    <div class="pager">{pager}</div>
    <p><small class="muted num">{total:,} کاربر{' (با فیلتر فعلی)' if (search or only_recent or only_banned) else ' ثبت‌شده'}</small></p>
    <p><small class="muted">«آخرین دستور» همون آخرین دستور، دکمه یا مرحله‌ایه که کاربر تو ربات زده. زمان‌ها به وقت تهران و تاریخ شمسی است.
    برای کاربرانی که از آخرین بروزرسانی ربات به بعد هنوز پیامی نداده‌اند، فعالیت ثبت نشده.</small></p>
    """
    return render_page("کاربران", "users", content)


@app.route("/users/<int:user_id>")
@login_required
def user_detail(user_id):
    u = get_user(user_id)
    if not u:
        flash("⚠️ کاربر پیدا نشد.")
        return redirect(url_for("users"))
    _id, username, first_name, wallet, joined_at, last_active, last_action, lang = u
    configs = get_user_configs(user_id)
    state = activity_state(last_active)

    cfg_rows = ""
    for label, ctype, gb, days, price, status, created_at, expires_at in configs:
        active = (status or "active") == "active"
        cfg_rows += f"""
        <tr>
          <td data-label="اسم">{esc(label)}</td><td data-label="نوع">{esc(ctype or '-')}</td>
          <td data-label="حجم" class="num">{float(gb or 0):g} گیگ</td><td data-label="مدت" class="num">{days or 0} روز</td>
          <td data-label="مبلغ" class="num">{int(price or 0):,}</td>
          <td data-label="تاریخ ساخت"><small class="muted">{fmt_dt(created_at, with_time=False)}</small></td>
          <td data-label="وضعیت"><span class="badge {'on' if active else 'off'}">{'فعال' if active else esc(status)}</span></td>
        </tr>"""

    is_b = user_id in get_banned_ids([user_id])
    ban_card = f"""
    <div class="card"><h3>⛔ مسدودسازی</h3>
      <p>وضعیت: {'<span class="badge off">مسدود</span>' if is_b else '<span class="badge on">آزاد</span>'}</p>
      <small class="muted">کاربر مسدود دیگه به هیچ بخشی از ربات دسترسی نداره و فقط پیام «دسترسی شما مسدود شده» می‌بینه. اعمال تغییر تا حدود ۱۵ ثانیه طول می‌کشه.</small>
      <form method="post" action="{url_for('user_ban', user_id=user_id)}" style="margin-top:10px;">
        <input type="hidden" name="action" value="{'unban' if is_b else 'ban'}">
        <button type="submit" class="{'' if is_b else 'danger'}">{'✅ آزاد کردن کاربر' if is_b else '⛔ مسدود کردن کاربر'}</button>
      </form></div>"""

    trial_count, trial_last = get_trial_info(user_id)
    trial_card = f"""
    <div class="card"><h3>🧪 تست رایگان</h3>
      <div class="kv">
        <div><span>تعداد تست گرفته‌شده</span><b class="num">{trial_count}</b></div>
        <div><span>آخرین تست</span><b>{fmt_dt(trial_last) if trial_last else '—'}</b></div>
      </div>
      <form method="post" action="{url_for('user_trial_reset', user_id=user_id)}" style="margin-top:10px;">
        <button type="submit" class="secondary">♻️ ریست تست رایگان این کاربر</button>
      </form>
    </div>"""

    content = f"""
    <p><a class="btn secondary sm" href="{url_for('users')}">‹ بازگشت به کاربران</a></p>
    <div class="card">
      <div class="kv">
        <div><span>کاربر</span><b>{user_display(first_name, username, user_id)}</b></div>
        <div><span>آیدی عددی</span><b class="num">{user_id}</b></div>
        <div><span>موجودی کیف پول</span><b class="num">{int(wallet or 0):,} تومان</b></div>
        <div><span>زبان</span><b>{'English' if lang == 'en' else 'فارسی'}</b></div>
        <div><span>تاریخ عضویت</span><b>{fmt_dt(joined_at)}</b></div>
        <div><span>آخرین فعالیت</span><b class="act"><i class="{state}"></i>{rel_time(last_active)}</b><small class="muted">{fmt_dt(last_active)}</small></div>
        <div><span>آخرین دستور</span><b>{esc(action_label(last_action))}</b></div>
      </div>
    </div>

    <div class="grid cols-2">
      <div class="card"><h3>تغییر موجودی</h3>
        <form method="post" action="{url_for('adjust_wallet')}" class="flex">
          <input type="hidden" name="user_id" value="{user_id}">
          <input type="number" name="amount" placeholder="مبلغ (تومان)" min="1" style="flex:1;min-width:140px;" required>
          <button type="submit" name="sign" value="1">➕ افزایش</button>
          <button type="submit" name="sign" value="-1" class="secondary">➖ کاهش</button>
        </form></div>
      <div class="card"><h3>ارسال پیام به این کاربر</h3>
        <form method="post" action="{url_for('user_message', user_id=user_id)}">
          <textarea name="text" style="min-height:70px;" placeholder="متن پیام (HTML تلگرام مجاز است)" required></textarea>
          <div style="margin-top:10px;"><button type="submit">ارسال در ربات</button></div>
        </form></div>
    </div>

    {ban_card}
    {trial_card}
    <p><a class="btn" href="{url_for('user_configs_admin', user_id=user_id)}">⚙️ مدیریت کانفیگ‌های این کاربر (تمدید، توقف، حذف، ساخت هدیه)</a></p>

    <h3>کانفیگ‌های کاربر</h3>
    <table class="rt">
      <thead><tr><th>اسم</th><th>نوع</th><th>حجم</th><th>مدت</th><th>مبلغ</th><th>تاریخ ساخت</th><th>وضعیت</th></tr></thead>
      <tbody>{cfg_rows if cfg_rows else '<tr><td colspan="7">این کاربر هنوز کانفیگی نخریده.</td></tr>'}</tbody>
    </table>
    """
    return render_page(f"کاربر {user_id}", "users", content)


@app.route("/users/wallet", methods=["POST"])
@login_required
def adjust_wallet():
    user_id = to_int(request.form.get("user_id"))
    amount = to_int(request.form.get("amount"))
    sign = 1 if request.form.get("sign") == "1" else -1
    back = url_for("user_detail", user_id=user_id) if (user_id and request.form.get("next") != "list") else url_for("users")
    if user_id is None or amount is None or amount <= 0:
        flash("⚠️ مبلغ باید یک عدد مثبت باشد.")
        return redirect(back)
    current = get_wallet(user_id)
    if current is None:
        flash("⚠️ کاربر پیدا نشد.")
    else:
        update_wallet(user_id, amount * sign)
        flash(f"موجودی کاربر {user_id} به مقدار {amount:,} تومان {'افزایش' if sign > 0 else 'کاهش'} یافت.")
    return redirect(back)


@app.route("/users/<int:user_id>/ban", methods=["POST"])
@login_required
def user_ban(user_id):
    if get_user(user_id) is None:
        flash("⚠️ کاربر پیدا نشد.")
        return redirect(url_for("users"))
    ban = request.form.get("action") == "ban"
    set_user_banned(user_id, ban)
    flash(f"کاربر {user_id} " + ("مسدود شد." if ban else "آزاد شد."))
    if request.form.get("next") == "list":
        return redirect(url_for("users"))
    return redirect(url_for("user_detail", user_id=user_id))


@app.route("/users/<int:user_id>/trial-reset", methods=["POST"])
@login_required
def user_trial_reset(user_id):
    reset_trial(user_id)
    flash(f"تست رایگان کاربر {user_id} ریست شد؛ دوباره می‌تونه تست بگیره.")
    return redirect(url_for("user_detail", user_id=user_id))


@app.route("/users/<int:user_id>/message", methods=["POST"])
@login_required
def user_message(user_id):
    text = request.form.get("text", "").strip()
    if not text:
        flash("⚠️ متن پیام خالیه.")
    elif send_telegram_message(user_id, text):
        flash("پیام برای کاربر ارسال شد.")
    else:
        flash("⚠️ ارسال پیام ناموفق بود (کاربر ربات را بلاک کرده یا توکن/متن مشکل دارد).")
    return redirect(url_for("user_detail", user_id=user_id))


# ---------- تیکت‌ها ----------

@app.route("/tickets")
@login_required
def tickets():
    status_filter = request.args.get("status", "open")
    rows = get_tickets(status_filter if status_filter != "all" else None)

    rows_html = ""
    for tid, user_id, message, status, admin_reply, created_at in rows:
        msg = message or ""
        rows_html += f"""
        <tr>
          <td data-label="شماره">#{tid}</td>
          <td data-label="کاربر"><a href="{url_for('user_detail', user_id=user_id)}" class="num">{user_id}</a></td>
          <td data-label="پیام" class="wrap">{esc(msg[:80])}{'…' if len(msg) > 80 else ''}</td>
          <td data-label="وضعیت"><span class="badge {esc(status)}">{esc(status)}</span></td>
          <td data-label=""><a class="btn secondary sm" href="{url_for('ticket_detail', ticket_id=tid)}">مشاهده</a></td>
        </tr>"""

    tabs = ""
    for key, label in [("open", "باز"), ("answered", "پاسخ‌داده‌شده"), ("closed", "بسته"), ("all", "همه")]:
        tabs += f'<a class="pill {"active" if status_filter == key else ""}" href="{url_for("tickets", status=key)}">{label}</a>'

    content = f"""
    <div class="chips-row">{tabs}</div>
    <table class="rt">
      <thead><tr><th>شماره</th><th>کاربر</th><th>پیام</th><th>وضعیت</th><th></th></tr></thead>
      <tbody>{rows_html if rows_html else '<tr><td colspan="5">تیکتی یافت نشد.</td></tr>'}</tbody>
    </table>"""
    return render_page("تیکت‌های پشتیبانی", "tickets", content)


@app.route("/tickets/<int:ticket_id>")
@login_required
def ticket_detail(ticket_id):
    t = get_ticket(ticket_id)
    if not t:
        flash("⚠️ تیکت پیدا نشد.")
        return redirect(url_for("tickets"))
    tid, user_id, message, status, admin_reply, created_at = t
    reply_block = f'<div class="card" style="background:var(--surface-2);"><b>پاسخ قبلی</b><p style="margin:6px 0 0;">{esc(admin_reply)}</p></div>' if admin_reply else ""
    content = f"""
    <p><a class="btn secondary sm" href="{url_for('tickets')}">‹ بازگشت به تیکت‌ها</a></p>
    <div class="card">
      <div class="flex" style="margin-bottom:10px;"><b>تیکت #{tid}</b><span class="badge {esc(status)}">{esc(status)}</span>
        <a href="{url_for('user_detail', user_id=user_id)}">کاربر {user_id}</a><small class="muted">{fmt_dt(created_at)}</small></div>
      <p style="white-space:pre-wrap;margin:0;">{esc(message)}</p>
    </div>
    {reply_block}
    <div class="card">
      <form method="post" action="{url_for('ticket_reply', ticket_id=tid)}">
        <label>پاسخ به کاربر</label>
        <textarea name="reply" required></textarea>
        <div class="flex" style="margin-top:12px;"><button type="submit">ارسال پاسخ</button></div>
      </form>
      <form method="post" action="{url_for('ticket_close', ticket_id=tid)}" style="margin-top:10px;">
        <button type="submit" class="danger">بستن تیکت بدون پاسخ</button>
      </form>
    </div>"""
    return render_page(f"تیکت #{tid}", "tickets", content)


@app.route("/tickets/<int:ticket_id>/reply", methods=["POST"])
@login_required
def ticket_reply(ticket_id):
    reply_text = request.form.get("reply", "").strip()
    t = get_ticket(ticket_id)
    if not t:
        flash("⚠️ تیکت پیدا نشد.")
        return redirect(url_for("tickets"))
    if reply_text:
        update_ticket_status(ticket_id, "answered", reply_text)
        if send_telegram_message(t[1], f"📩 پاسخ پشتیبانی برای تیکت #{ticket_id}:\n\n{reply_text}"):
            flash("پاسخ برای کاربر ارسال شد.")
        else:
            flash("⚠️ پاسخ ذخیره شد ولی ارسالش به کاربر ناموفق بود.")
    return redirect(url_for("tickets"))


@app.route("/tickets/<int:ticket_id>/close", methods=["POST"])
@login_required
def ticket_close(ticket_id):
    update_ticket_status(ticket_id, "closed")
    flash(f"تیکت #{ticket_id} بسته شد.")
    return redirect(url_for("tickets"))


# ---------- شارژهای کیف پول (تایید/رد از پنل) ----------

@app.route("/topups")
@login_required
def topups_page():
    f_status = request.args.get("status", "all")
    f_method = request.args.get("method", "all")
    f_q = (request.args.get("q") or "").strip()
    rows = get_topups(300)
    if f_status != "all":
        rows = [r for r in rows if r[3] == f_status]
    if f_method != "all":
        rows = [r for r in rows if (r[5] or "card") == f_method]
    if f_q.isdigit():
        rows = [r for r in rows if str(r[1]) == f_q]
    rows = rows[:120]

    def _pill(label, key, val, cur):
        args = {"status": f_status, "method": f_method, "q": f_q}
        args[key] = val
        args = {k: v for k, v in args.items() if v and v != "all"}
        cls = "pill active" if cur == val else "pill"
        return f'<a class="{cls}" href="{url_for("topups_page", **args)}">{label}</a>'

    filter_bar = (
        '<div class="chips-row">'
        + _pill("همه", "status", "all", f_status) + _pill("⏳ در انتظار", "status", "pending", f_status)
        + _pill("✅ تایید شده", "status", "approved", f_status) + _pill("❌ رد شده", "status", "rejected", f_status)
        + _pill("⌛️ منقضی", "status", "expired", f_status) + '</div>'
        + '<div class="chips-row">'
        + _pill("همه روش‌ها", "method", "all", f_method) + _pill("⚡️ دونیتو", "method", "donito", f_method)
        + _pill("🧾 دونیتو دستی", "method", "donito_manual", f_method)
        + _pill("💳 کارت‌به‌کارت", "method", "card", f_method) + _pill("🪙 رمزارز", "method", "crypto", f_method)
        + '</div>'
        + '<form method="get" class="flex" style="margin-bottom:14px;">'
        + f'<input type="hidden" name="status" value="{esc(f_status)}"><input type="hidden" name="method" value="{esc(f_method)}">'
        + f'<input type="search" name="q" value="{esc(f_q)}" placeholder="آیدی عددی کاربر…" inputmode="numeric" style="max-width:240px;">'
        + '<button type="submit" class="sm">🔍 جستجو</button></form>')
    rows_html = ""
    for rid, user_id, amount, status, created_at, method, coin_symbol, coin_qty, tx_hash, matched_tx, user_note in rows:
        is_crypto = (method == "crypto")
        is_donito = (method == "donito")
        is_manual = (method == "donito_manual")
        kind = ("🪙 رمزارز" if is_crypto else ("⚡️ دونیتو (خودکار)" if is_donito else
                ("🧾 دونیتو (تایید دستی)" if is_manual else "💳 کارت‌به‌کارت")))
        detail = ""
        if is_manual:
            detail = f"<br><small class=\"muted\" style=\"word-break:break-all;\">📝 {esc(user_note or '—')}</small>"
            if matched_tx:
                detail += "<br><small class=\"muted\">✔️ دونیت هم‌مبلغ تو دونیتو پیدا شده</small>"
        if is_donito:
            detail = ("<br><small class=\"muted\">✔️ پرداخت در دونیتو پیدا شد</small>" if matched_tx
                      else "<br><small class=\"muted\">منتظر پرداخت کاربر (مبلغ یکتا)</small>")
        if is_crypto:
            try:
                qty_txt = f"{float(coin_qty):g}" if coin_qty else ""
            except (TypeError, ValueError):
                qty_txt = str(coin_qty or "")
            detail = f"<br><small class=\"muted\">{esc(qty_txt)} {esc((coin_symbol or '').upper())}</small>"
            if tx_hash:
                detail += f"<br><small class=\"muted num\" dir=\"ltr\" style=\"word-break:break-all;\">{esc(tx_hash)}</small>"
            if matched_tx:
                detail += "<br><small class=\"muted\">✔️ واریز در نوبیتکس پیدا شده</small>"
        if status == "pending":
            actions = f"""
            <form method="post" action="{url_for('topup_approve', req_id=rid)}" style="display:inline;"
                  onsubmit="return confirm('شارژ #{rid} تایید بشه و مبلغ به کیف پول کاربر اضافه بشه؟');">
              <button type="submit" class="sm">✅ تایید</button>
            </form>
            <form method="post" action="{url_for('topup_reject', req_id=rid)}" style="display:inline;"
                  onsubmit="return confirm('شارژ #{rid} رد بشه؟');">
              <button type="submit" class="danger sm">❌ رد</button>
            </form>"""
        else:
            actions = "—"
        rows_html += f"""
        <tr>
          <td data-label="شماره">#{rid}</td>
          <td data-label="کاربر"><a class="num" href="{url_for('user_detail', user_id=user_id)}">{user_id}</a></td>
          <td data-label="نوع">{kind}{detail}</td>
          <td data-label="مبلغ" class="num">{int(amount or 0):,} تومان</td>
          <td data-label="وضعیت"><span class="badge {esc(status)}">{esc({'pending': 'در انتظار', 'approved': 'تایید شده', 'rejected': 'رد شده', 'expired': 'منقضی شده'}.get(status, status))}</span></td>
          <td data-label="تاریخ"><small class="muted">{fmt_dt(created_at)}</small></td>
          <td data-label="عملیات">{actions}</td>
        </tr>"""
    content = f"""
    {filter_bar}
    <table class="rt">
      <thead><tr><th>شماره</th><th>کاربر</th><th>نوع</th><th>مبلغ واریزی</th><th>وضعیت</th><th>تاریخ</th><th>عملیات</th></tr></thead>
      <tbody>{rows_html if rows_html else '<tr><td colspan="7">درخواستی ثبت نشده.</td></tr>'}</tbody>
    </table>
    <p><small class="muted">تایید/رد از همین‌جا با دکمه‌ی داخل ربات یکی‌ه و پیام نتیجه برای کاربر هم فرستاده می‌شه. هر درخواست فقط یک‌بار قابل بررسیه (اگه تو ربات تایید شده باشه، اینجا دوباره شارژ نمی‌شه).
    عکس رسید کارت‌به‌کارت فقط داخل پیام ادمین تو ربات هست؛ قبل از تایید، رسید رو اون‌جا چک کن.
    شارژهای «دونیتو» خودکار تایید می‌شن (بدون رسید)؛ فقط اگه کاربر مبلغ رو اشتباه پرداخت کرد یا مهلت تموم شد، بعد از چک‌کردن داشبورد دونیتو دستی تایید کن
    (درخواست منقضی‌شده دیگه قابل تایید نیست).</small></p>"""
    return render_page("شارژهای کیف پول", "topups", content)


@app.route("/topups/<int:req_id>/approve", methods=["POST"])
@login_required
def topup_approve(req_id):
    ok, msg = panel_approve_topup(req_id)
    flash(msg if ok else "⚠️ " + msg)
    return redirect(url_for("topups_page"))


@app.route("/topups/<int:req_id>/reject", methods=["POST"])
@login_required
def topup_reject(req_id):
    ok, msg = panel_reject_topup(req_id)
    flash(msg if ok else "⚠️ " + msg)
    return redirect(url_for("topups_page"))


# ---------- رمزارزها (شارژ کیف پول با رمزارز) ----------
# لیست رمزارزها تو جدول settings (کلید crypto_coins) به‌صورت JSON ذخیره می‌شه و ربات همون رو می‌خونه:
#   [{"id": "ab12cd", "label": "Gram", "symbol": "gram", "wallet": "UQ...", "memo": "12345", "enabled": true}, ...]
#   label  = اسمی که کاربر تو ربات می‌بینه
#   symbol = «نام درست» کوین تو نوبیتکس (برای گرفتن قیمت لحظه‌ای؛ جفت‌ارز symbol-rls)
#   wallet = آدرسی که کاربر بهش واریز می‌کنه (کوینی که آدرس نداشته باشه تو ربات نشون داده نمی‌شه)
#   network = شبکه‌ی بلاکچین واریز (مثل TON یا TRC20؛ اختیاری، خالی باشه تو ربات نشون داده نمی‌شه)
#   memo   = Memo/Comment/Tag واریز (اختیاری؛ خالی باشه تو ربات هیچی نشون داده نمی‌شه)
# اگه این کلید هیچ‌وقت ثبت نشده باشه، گزینه‌ی رمزارز تو ربات نشون داده نمی‌شه.
CRYPTO_DEFAULT_COINS = [{"id": "gram", "label": "Gram", "symbol": "gram", "wallet": "", "memo": "", "network": "", "enabled": True}]
CRYPTO_SYMBOL_RE = re.compile(r"^[a-z0-9]{2,15}$")


def load_crypto_coins(all_settings=None):
    """(coins, configured) — configured=False یعنی هنوز از پنل ذخیره نشده و پیش‌فرض (Gram) نشون داده می‌شه."""
    if all_settings is None:
        all_settings = get_all_settings()
    raw = all_settings.get("crypto_coins")
    if raw is None:
        return [dict(c) for c in CRYPTO_DEFAULT_COINS], False
    try:
        data = json.loads(raw)
    except Exception:
        data = []
    coins = []
    for c in data if isinstance(data, list) else []:
        if isinstance(c, dict) and c.get("symbol"):
            coins.append({"id": str(c.get("id") or secrets.token_hex(3)), "label": str(c.get("label") or c["symbol"]),
                          "symbol": str(c["symbol"]).lower(), "wallet": str(c.get("wallet") or ""),
                          "memo": str(c.get("memo") or ""), "network": str(c.get("network") or ""),
                          "enabled": bool(c.get("enabled", True))})
    return coins, True


def save_crypto_coins(coins):
    set_setting("crypto_coins", json.dumps(coins, ensure_ascii=False))


def check_coin_fields(label, symbol, wallet, memo="", network=""):
    """(label, symbol, wallet, memo, network, error) — memo و network اختیارین؛ خالی بمونن تو ربات نشون داده نمی‌شن."""
    label, symbol, wallet, memo = label.strip(), symbol.strip().lower(), wallet.strip(), (memo or "").strip()
    network = (network or "").strip()
    if not label or len(label) > 30:
        return None, None, None, None, None, "اسم نمایشی باید بین ۱ تا ۳۰ کاراکتر باشه."
    if not CRYPTO_SYMBOL_RE.match(symbol):
        return None, None, None, None, None, "نام کوین تو نوبیتکس فقط حروف انگلیسی/عدد (۲ تا ۱۵ کاراکتر) باشه؛ مثل gram یا usdt."
    if len(wallet) > 200 or re.search(r"\s", wallet):
        return None, None, None, None, None, "آدرس ولت نباید فاصله داشته باشه و بیشتر از ۲۰۰ کاراکتر باشه."
    if len(memo) > 100 or re.search(r"[\r\n]", memo):
        return None, None, None, None, None, "Memo/Comment حداکثر ۱۰۰ کاراکتر و تک‌خطی باشه."
    if len(network) > 50 or re.search(r"[\r\n]", network):
        return None, None, None, None, None, "اسم شبکه حداکثر ۵۰ کاراکتر و تک‌خطی باشه."
    return label, symbol, wallet, memo, network, None


# آدرس رسمی تو مستندات جدید نوبیتکس apiv2.nobitex.ir هست؛ api.nobitex.ir آدرس قدیمیه و از سرور خارج از ایران
# (مثل Railway) ممکنه DNS اش جواب نده (ارور Failed to resolve). به ترتیب هر دو امتحان می‌شن.
# همون Environment اختیاری ربات (NOBITEX_API_BASE، چند آدرس با کاما) اینجا هم خونده می‌شه.
NOBITEX_API_BASES = [x.strip().rstrip("/") for x in os.getenv(
    "NOBITEX_API_BASE", "https://apiv2.nobitex.ir,https://api.nobitex.ir").split(",") if x.strip()]


def nobitex_price_toman(symbol):
    """قیمت لحظه‌ای (تومان) از API عمومی نوبیتکس؛ (price, error)."""
    r, last_err = None, None
    for base in NOBITEX_API_BASES:
        try:
            r = SESSION.post(base + "/market/stats",
                             json={"srcCurrency": symbol, "dstCurrency": "rls"}, timeout=12)
            break
        except requests.exceptions.RequestException as e:   # DNS/اتصال: آدرس بعدی
            last_err = e
    if r is None:
        return None, f"ارتباط با نوبیتکس ممکن نشد: {last_err}"
    try:
        if r.status_code != 200:
            return None, f"نوبیتکس جواب نامعتبر داد (HTTP {r.status_code})"
        data = r.json()
        if data.get("status") != "ok":
            return None, f"نوبیتکس خطا داد: {str(data)[:150]}"
        st = (data.get("stats") or {}).get(f"{symbol}-rls") or {}
        latest = float(st.get("latest") or 0)
        if latest <= 0:
            bb, bs = float(st.get("bestBuy") or 0), float(st.get("bestSell") or 0)
            latest = (bb + bs) / 2.0 if bb > 0 and bs > 0 else 0
        if latest > 0:
            return latest / 10.0, None
        return None, "نوبیتکس برای این نام قیمتی برنگردوند (نام کوین درسته؟)"
    except Exception as e:
        return None, f"پاسخ نوبیتکس قابل خوندن نبود: {e}"


@app.route("/crypto")
@login_required
def crypto_page():
    ensure_settings_table()
    all_settings = get_all_settings()
    coins, configured = load_crypto_coins(all_settings)
    master_on = all_settings.get("crypto_enabled", "1") == "1"
    card_on = all_settings.get("card_topup_enabled", "1") == "1"

    card_master = f"""
    <div class="card">
      <div class="switch-row" style="padding-top:0;">
        <div><b>💳 شارژ کارت‌به‌کارت (ریالی)</b><br>
          <small class="muted">خاموش باشه، گزینه‌ی کارت‌به‌کارت تو شارژ کیف پول به کاربر نشون داده نمی‌شه. اگه رمزارز روشن باشه کاربر مستقیم میره سراغ پرداخت با رمزارز؛
          اگه هر دو خاموش باشن، شارژ کیف پول برای کاربر غیرفعال می‌شه. (تنظیمات شماره کارت و صاحب کارت همچنان از صفحه‌ی تنظیمات عوض می‌شه.)</small></div>
        <form method="post" action="{url_for('card_topup_master')}">
          {tgl_btn(card_on)}
        </form>
      </div>
    </div>"""

    donito_on = all_settings.get("donito_enabled", "1") == "1"
    donito_master = f"""
    <div class="card">
      <div class="switch-row" style="padding-top:0;">
        <div><b>⚡️ شارژ ریالی خودکار (دونیتو)</b><br>
          <small class="muted">کاربر مبلغ رو می‌نویسه، ربات یه مبلغ یکتا (مثلاً ۱۰۰,۰۳۷) بهش می‌ده و کاربر همون مبلغ دقیق رو تو صفحه‌ی دونیتوی تو می‌پردازه؛
          ربات با تطبیق مبلغ، شارژ رو خودکار تأیید می‌کنه (بدون رسید و بدون تأیید ادمین). آدرس صفحه، حداقل مبلغ و مدت اعتبار از صفحه‌ی «تنظیمات ربات» عوض می‌شه.
          توکن دونیتو داخل خود ربات (متغیر DONITO_TOKEN یا کد) تنظیم می‌شه؛ با دستور /donitocheck تو ربات اتصال رو تست کن.
          صفحه‌ی فعلی: <span dir="ltr">{esc(all_settings.get('donito_page_url') or DEFAULT_DONITO_PAGE_URL)}</span></small></div>
        <form method="post" action="{url_for('donito_master')}">
          {tgl_btn(donito_on)}
        </form>
      </div>
    </div>"""

    master = f"""
    <div class="card">
      <div class="switch-row" style="padding-top:0;">
        <div><b>🪙 شارژ با رمزارز</b><br>
          <small class="muted">کاربر ارز رو انتخاب می‌کنه، آدرس ولت رو می‌بینه و بعد از واریز مقدار دقیق رو می‌نویسه (مثلاً 0.2 TON). ربات معادل تومانی رو نشون می‌ده و همون لحظه واریز رو تو نوبیتکس چک می‌کنه؛ اگه پیدا نشد هش می‌خواد و در نهایت منتظر تأیید دستی تو می‌مونه.
          تأیید خودکار از صفحه‌ی «تنظیمات ربات» (کلید «تأیید خودکار واریز رمزارز») روشن/خاموش می‌شه.</small></div>
        <form method="post" action="{url_for('crypto_master')}">
          {tgl_btn(master_on)}
        </form>
      </div>
    </div>"""

    rows = ""
    for c in coins:
        cid = esc(c["id"])
        rows += f"""
        <div class="card">
          <input type="hidden" name="ids" value="{cid}">
          <h3>{esc(c['label'])} <span class="badge {'on' if c['enabled'] else 'off'}">{'فعال' if c['enabled'] else 'غیرفعال'}</span></h3>
          <label for="l_{cid}">اسم نمایشی (چیزی که کاربر تو ربات می‌بینه)</label>
          <input id="l_{cid}" name="label_{cid}" value="{esc(c['label'])}" maxlength="30">
          <label for="s_{cid}">نام درست کوین تو نوبیتکس (برای گرفتن قیمت)</label>
          <input id="s_{cid}" name="symbol_{cid}" value="{esc(c['symbol'])}" dir="ltr" autocapitalize="off" spellcheck="false" placeholder="gram">
          <label for="w_{cid}">آدرس ولت (کاربر بهش واریز می‌کنه)</label>
          <input id="w_{cid}" name="wallet_{cid}" value="{esc(c['wallet'])}" dir="ltr" autocapitalize="off" spellcheck="false" placeholder="آدرس ولت رو اینجا بنویس">
          <label for="nw_{cid}">شبکه‌ی بلاکچین (اختیاری؛ مثل TON یا TRC20)</label>
          <input id="nw_{cid}" name="network_{cid}" value="{esc(c.get('network', ''))}" dir="ltr" autocapitalize="off" spellcheck="false" maxlength="50" placeholder="خالی بذار تا تو ربات نشون داده نشه">
          <label for="m_{cid}">Memo / Comment (اختیاری)</label>
          <input id="m_{cid}" name="memo_{cid}" value="{esc(c.get('memo', ''))}" dir="ltr" autocapitalize="off" spellcheck="false" maxlength="100" placeholder="خالی بذار تا تو ربات نشون داده نشه">
          <div class="switch-row"><div><b>نمایش تو ربات</b></div>
            <input type="hidden" name="enabled_{cid}" value="{'1' if c['enabled'] else '0'}">
            {tgl_btn(c['enabled'], url_for('crypto_coin_toggle', coin_id=c['id']))}</div>
          <div class="flex" style="margin-top:8px;">
            <button type="submit" class="secondary sm" formaction="{url_for('crypto_test', coin_id=c['id'])}" formnovalidate>🔎 تست قیمت (ذخیره نمی‌کنه)</button>
            <button type="submit" class="danger sm" formaction="{url_for('crypto_delete', coin_id=c['id'])}" formnovalidate
              onclick="return confirm('حذف شود؟');">🗑 حذف</button>
          </div>
        </div>"""

    if not coins:
        rows = '<div class="card"><p class="empty-note">هیچ رمزارزی ثبت نشده؛ تا وقتی یکی اضافه نکنید، گزینه‌ی رمزارز تو ربات نشون داده نمی‌شه.</p></div>'

    note = ("" if configured else
            '<div class="card"><small class="muted">هنوز رمزارزی ذخیره نشده و گزینه‌ی رمزارز تو ربات نشون داده نمی‌شه. '
            'آدرس ولت «Gram» رو پایین بنویس و ذخیره کن (یا رمزارز دیگه‌ای اضافه کن). از اون به بعد آدرس رو هر وقت خواستی از همین صفحه عوض کن.</small></div>')

    add_form = f"""
    <div class="card">
      <h3>➕ افزودن رمزارز جدید</h3>
      <form method="post" action="{url_for('crypto_add')}">
        <label for="n_label">اسم نمایشی</label>
        <input id="n_label" name="label" maxlength="30" placeholder="مثلاً Tether" required>
        <label for="n_symbol">نام درست کوین تو نوبیتکس (انگلیسی، مثل usdt)</label>
        <input id="n_symbol" name="symbol" dir="ltr" autocapitalize="off" spellcheck="false" placeholder="usdt" required>
        <label for="n_wallet">آدرس ولت</label>
        <input id="n_wallet" name="wallet" dir="ltr" autocapitalize="off" spellcheck="false" placeholder="آدرس واریز" required>
        <label for="n_network">شبکه‌ی بلاکچین (اختیاری؛ مثل TON یا TRC20)</label>
        <input id="n_network" name="network" dir="ltr" autocapitalize="off" spellcheck="false" maxlength="50" placeholder="خالی بذار تا تو ربات نشون داده نشه">
        <label for="n_memo">Memo / Comment (اختیاری)</label>
        <input id="n_memo" name="memo" dir="ltr" autocapitalize="off" spellcheck="false" maxlength="100" placeholder="خالی بذار تا تو ربات نشون داده نشه">
        <div style="margin-top:10px;"><button type="submit" class="block">➕ اضافه کن</button></div>
      </form>
    </div>"""

    content = f"""
    {donito_master}
    {card_master}
    {master}
    {note}
    <form method="post" action="{url_for('crypto_save')}">
      {rows}
      {'<div class="savebar"><button type="submit" class="block">💾 ذخیره‌ی تغییرات</button></div>' if coins else ''}
    </form>
    {add_form}
    <p><small class="muted">قیمت از نوبیتکس به‌صورت لحظه‌ای گرفته می‌شه (جفت‌ارز «نام کوین / ریال»)؛ دکمه‌ی «تست قیمت» کمک می‌کنه مطمئن بشی نام کوین درسته. تغییرات حداکثر ~۲۰ ثانیه بعد روی ربات اعمال می‌شه.</small></p>"""
    return render_page("رمزارزها", "crypto", content)


@app.route("/card/master", methods=["POST"])
@login_required
def card_topup_master():
    on = get_setting("card_topup_enabled", "1") == "1"
    set_setting("card_topup_enabled", "0" if on else "1")
    flash("شارژ کارت‌به‌کارت خاموش شد." if on else "شارژ کارت‌به‌کارت روشن شد.")
    return redirect(url_for("crypto_page"))


@app.route("/donito/master", methods=["POST"])
@login_required
def donito_master():
    on = get_setting("donito_enabled", "1") == "1"
    set_setting("donito_enabled", "0" if on else "1")
    flash("شارژ ریالی خودکار (دونیتو) خاموش شد." if on else "شارژ ریالی خودکار (دونیتو) روشن شد.")
    return redirect(url_for("crypto_page"))


@app.route("/crypto/master", methods=["POST"])
@login_required
def crypto_master():
    on = get_setting("crypto_enabled", "1") == "1"
    set_setting("crypto_enabled", "0" if on else "1")
    flash("شارژ با رمزارز خاموش شد." if on else "شارژ با رمزارز روشن شد.")
    return redirect(url_for("crypto_page"))


@app.route("/crypto/<coin_id>/toggle", methods=["POST"])
@login_required
def crypto_coin_toggle(coin_id):
    coins, _configured = load_crypto_coins()
    for c in coins:
        if c["id"] == coin_id:
            c["enabled"] = not c["enabled"]
            flash(f"«{c['label']}» " + ("روشن شد." if c["enabled"] else "خاموش شد."))
    save_crypto_coins(coins)
    return redirect(url_for("crypto_page"))


@app.route("/crypto/save", methods=["POST"])
@login_required
def crypto_save():
    coins, _configured = load_crypto_coins()
    by_id = {c["id"]: c for c in coins}
    out, errors = [], 0
    for cid in request.form.getlist("ids"):
        old = by_id.get(cid)
        if old is None:
            continue
        label, symbol, wallet, memo, network, err = check_coin_fields(request.form.get(f"label_{cid}", ""),
                                                                      request.form.get(f"symbol_{cid}", ""),
                                                                      request.form.get(f"wallet_{cid}", ""),
                                                                      request.form.get(f"memo_{cid}", ""),
                                                                      request.form.get(f"network_{cid}", ""))
        if err:
            flash(f"⚠️ «{old['label']}»: {err} — تغییراتش ذخیره نشد.")
            out.append(old)
            errors += 1
            continue
        out.append({"id": cid, "label": label, "symbol": symbol, "wallet": wallet, "memo": memo, "network": network,
                    "enabled": request.form.get(f"enabled_{cid}") == "1"})
    save_crypto_coins(out)
    if not errors:
        flash("رمزارزها ذخیره شد.")
    return redirect(url_for("crypto_page"))


@app.route("/crypto/add", methods=["POST"])
@login_required
def crypto_add():
    label, symbol, wallet, memo, network, err = check_coin_fields(request.form.get("label", ""), request.form.get("symbol", ""),
                                                                  request.form.get("wallet", ""), request.form.get("memo", ""),
                                                                  request.form.get("network", ""))
    if err:
        flash(f"⚠️ {err}")
        return redirect(url_for("crypto_page"))
    if not wallet:
        flash("⚠️ آدرس ولت رو وارد کنید.")
        return redirect(url_for("crypto_page"))
    coins, _configured = load_crypto_coins()
    coins.append({"id": secrets.token_hex(3), "label": label, "symbol": symbol, "wallet": wallet, "memo": memo, "network": network, "enabled": True})
    save_crypto_coins(coins)
    price, perr = nobitex_price_toman(symbol)
    if price:
        flash(f"«{label}» اضافه شد. قیمت لحظه‌ای تست‌شده: {price:,.0f} تومان ✅")
    else:
        flash(f"«{label}» اضافه شد ولی ⚠️ قیمتش از نوبیتکس گرفته نشد: {perr}")
    return redirect(url_for("crypto_page"))


@app.route("/crypto/<coin_id>/delete", methods=["POST"])
@login_required
def crypto_delete(coin_id):
    coins, _configured = load_crypto_coins()
    save_crypto_coins([c for c in coins if c["id"] != coin_id])
    flash("رمزارز حذف شد.")
    return redirect(url_for("crypto_page"))


@app.route("/crypto/<coin_id>/test", methods=["POST"])
@login_required
def crypto_test(coin_id):
    """قیمت رو با نامی که الان تو فرم نوشته شده تست می‌کنه (بدون ذخیره)."""
    coins, _configured = load_crypto_coins()
    coin = next((c for c in coins if c["id"] == coin_id), None)
    symbol = (request.form.get(f"symbol_{coin_id}") or (coin or {}).get("symbol") or "").strip().lower()
    label = (request.form.get(f"label_{coin_id}") or (coin or {}).get("label") or symbol)
    if not CRYPTO_SYMBOL_RE.match(symbol):
        flash("⚠️ نام کوین معتبر نیست (فقط حروف انگلیسی/عدد).")
    else:
        price, err = nobitex_price_toman(symbol)
        flash(f"✅ قیمت لحظه‌ای {label} ({symbol}): {price:,.0f} تومان" if price else f"⚠️ {label} ({symbol}): {err}")
    return redirect(url_for("crypto_page"))


# ---------- تنظیمات ربات ----------

@app.route("/settings")
@login_required
def settings_page():
    ensure_settings_table()
    all_settings = get_all_settings()
    bot = get_bot_info()

    if bot:
        bot_card = f"""
        <div class="card"><h3>اطلاعات ربات</h3><div class="kv">
          <div><span>نام ربات</span><b>{esc(bot.get('first_name', '-'))}</b></div>
          <div><span>یوزرنیم</span><b dir="ltr">@{esc(bot.get('username', '-'))}</b></div>
          <div><span>آیدی ربات</span><b class="num">{esc(bot.get('id', '-'))}</b></div>
          <div><span>آیدی عددی ادمین فعلی</span><b class="num">{esc(all_settings.get('admin_id', os.getenv('ADMIN_ID', '48985781')))}</b></div>
        </div></div>"""
    else:
        bot_card = ('<div class="card"><h3>اطلاعات ربات</h3><p class="empty-note">اتصال به API ربات برقرار نشد '
                    '(توکن تنظیم نشده یا سرویس در دسترس نیست). تنظیمات پایین‌تر به هر حال کار می‌کنند.</p></div>')

    maint_on = all_settings.get("maintenance", "0") == "1"
    maint_card = f"""
    <div class="card">
      <div class="switch-row" style="padding-top:0;">
        <div><b>🛠 حالت تعمیر ربات</b><br><small class="muted">وقتی روشن باشه ربات به همه‌ی کاربران (جز ادمین) فقط پیام تعمیر نشون می‌ده. متن پیام رو پایین‌تر، بخش «مدیریت و نگهداری» عوض کنید.</small></div>
        <form method="post" action="{url_for('toggle_maintenance')}">
          {tgl_btn(maint_on)}
        </form>
      </div>
      <div><span class="badge {'off' if maint_on else 'on'}">{'ربات در حالت تعمیر است' if maint_on else 'ربات عادی کار می‌کند'}</span></div>
    </div>"""

    chips, groups_html = "", ""
    for idx, (title, items) in enumerate(CONFIG_GROUPS):
        rows = ""
        for key, label, default, kind in items:
            value = all_settings.get(key, default)
            if kind == "toggle":
                t_title, _sep, t_desc = label.partition("||")
                t_desc_html = f'<br><small class="muted">{esc(t_desc)}</small>' if t_desc else ""
                rows += (f'<div class="switch-row"><div><b>{esc(t_title)}</b>{t_desc_html}</div>'
                         f'{tgl_btn(str(value) == "1", url_for("toggle_config", key=key))}</div>')
                continue
            attrs = ' type="text"'
            if kind == "number":
                attrs = ' type="number" min="0" step="1" inputmode="numeric"'
            elif kind == "float":
                attrs = ' type="text" inputmode="decimal"'
            elif kind in ("url", "tiers"):
                attrs = ' type="text" dir="ltr" autocapitalize="off" spellcheck="false"'
            changed = ' <span class="badge on">سفارشی</span>' if key in all_settings else ""
            rows += f"""
            <label for="s_{key}">{esc(label)}{changed}</label>
            <input id="s_{key}" name="{key}" value="{esc(value)}" placeholder="{esc(default)}"{attrs}>"""
        chips += f'<a class="pill" href="#g{idx}">{title.split(" ", 1)[0]} {esc(title.split(" ", 1)[1][:22]) if " " in title else ""}</a>'
        groups_html += f'<div class="card" id="g{idx}"><h3>{title}</h3>{rows}</div>'

    rows_html = ""
    for key, label in FEATURES.items():
        enabled = all_settings.get(key, "1") == "1"
        rows_html += f"""
        <div class="switch-row"><div><b>{label}</b></div>
          <form method="post" action="{url_for('toggle_setting', key=key)}">{tgl_btn(enabled)}</form></div>"""

    content = f"""
    {bot_card}
    {maint_card}
    <div class="card"><h3>🔌 روشن/خاموش کردن قابلیت‌ها</h3>{rows_html}</div>
    <div class="chips-row">{chips}</div>
    <form method="post" action="{url_for('save_config')}">
      {groups_html}
      <p class="muted" style="font-size:12.5px;">هر فیلد را خالی بگذارید یا برابر مقدار پیش‌فرض (داخل کادر کم‌رنگ) بنویسید تا به پیش‌فرض برگردد. تغییرات حداکثر ~۲۰ ثانیه بعد روی ربات اعمال می‌شود.</p>
      <div class="savebar"><button type="submit" class="block">💾 ذخیره‌ی همه‌ی تغییرات</button></div>
    </form>
    <p><small class="muted">توکن ربات، کلید پنل اصلی (CONFIG_KEY) و اطلاعات دیتابیس عمداً از پنل قابل تغییر نیستند؛ اون‌ها فقط باید تو Environment سرور باشن.</small></p>
    """
    return render_page("تنظیمات ربات", "settings", content)


@app.route("/settings/maintenance", methods=["POST"])
@login_required
def toggle_maintenance():
    if get_setting("maintenance", "0") == "1":
        delete_setting("maintenance")
        flash("حالت تعمیر خاموش شد؛ ربات به حالت عادی برگشت.")
    else:
        set_setting("maintenance", "1")
        flash("حالت تعمیر روشن شد؛ کاربران فقط پیام تعمیر می‌بینند (ادمین مجاز است).")
    return redirect(url_for("settings_page"))


# ---------- فروشنده‌ها (ورود با نام کاربری و رمز) ----------

def _vendor_back(vkey):
    return redirect(url_for("reseller_detail", vkey=vkey))


def _status_badge(status):
    return '<span class="badge on">فعال</span>' if status == "active" else '<span class="badge off">مسدود</span>'


@app.route("/resellers")
@login_required
def resellers_page():
    vendors, svc_ok = build_vendors()
    total_paid = sum(v["paid"] or 0 for v in vendors)
    active_cnt = sum(1 for v in vendors if v["status"] == "active")
    warn = "" if svc_ok else ('<div class="alert">⚠️ ارتباط با سرویس برقرار نشد؛ حجم و قیمت‌ها نمایش داده نمی‌شن و '
                              'تغییر حجم/وضعیت/قیمت فعلاً کار نمی‌کنه. چند لحظه بعد صفحه رو دوباره باز کنید.</div>')
    rows_html = ""
    for v in vendors:
        vk = v["key"]
        tg_cell = (f'{user_display(v["tg_name"], v["tg_user"], v["tg_id"])}<br><small class="muted num">{v["tg_id"]}</small>'
                   if v["tg_id"] else '<span class="badge open">هنوز به تلگرام وصل نشده</span>')
        login_cell = copy_widget(v["name"]) if v["name"] and v["name"] != "—" else '<span class="badge open">تعیین نشده</span>'
        if v["password"]:
            pw_cell = secret_widget(v["password"])
        else:
            pw_cell = '<span class="badge open" title="رمز تو دیتابیس ربات ثبت نشده؛ با تغییر رمز از جزئیات ثبت می‌شه.">ثبت نشده</span>'
        both = ""
        if v["name"] and v["password"]:
            both = (f'<button type="button" class="secondary sm" data-copy="{esc(vendor_login_text(v))}" '
                    f'onclick="copyFrom(this)">📋 کپی ورود</button>')
        if v["on_service"]:
            actions = f"""
              <form method="post" action="{url_for('reseller_toggle', vkey=vk)}">
                <input type="hidden" name="next" value="list">
                <button type="submit" class="{'danger' if v['status'] == 'active' else ''} sm">{'مسدود کن' if v['status'] == 'active' else 'فعال کن'}</button>
              </form>"""
        else:
            actions = '<small class="muted">تو سرویس نیست</small>'
        price_txt = f"{int(v['price']):,}" if v["price"] else "پیش‌فرض"
        rows_html += f"""
        <tr>
          <td data-label="فروشنده" class="wrap">{tg_cell}</td>
          <td data-label="نام کاربری">{login_cell}</td>
          <td data-label="رمز عبور">{pw_cell}</td>
          <td data-label="قیمت هر گیگ" class="num">{price_txt}</td>
          <td data-label="خرید" class="num">{v['purchases']}</td>
          <td data-label="پرداختی (تومان)" class="num">{int(v['paid'] or 0):,}</td>
          <td data-label="وضعیت">{_status_badge(v['status'])}</td>
          <td data-label="عملیات"><div class="flex">{both}{actions}
              <a class="btn secondary sm" href="{url_for('reseller_detail', vkey=vk)}">جزئیات</a></div></td>
        </tr>"""
    content = f"""
    {warn}
    <div class="stats">
      <div class="stat"><span>👥 کل فروشنده‌ها</span><b class="num">{len(vendors):,}</b></div>
      <div class="stat"><span>✅ فعال</span><b class="num">{active_cnt:,}</b></div>
      <div class="stat"><span>💰 مجموع پرداختی‌ها</span><b class="num">{total_paid:,}</b><small>تومان</small></div>
    </div>
    <div class="card"><small class="muted">قیمت و وضعیت هر فروشنده <b>مستقیم روی سرویس اصلی</b> خونده و تغییر داده می‌شه.</small></div>
    <div class="flex" style="margin-bottom:14px;">
      <div class="search-box"><input type="search" placeholder="جستجو: نام، آیدی، نام کاربری…" oninput="filterRows(this,'resellers-table')" autocomplete="off"></div>
    </div>
    <table class="rt" id="resellers-table">
      <thead><tr><th>فروشنده</th><th>نام کاربری ورود</th><th>رمز عبور</th><th>قیمت هر گیگ</th><th>خرید</th><th>پرداختی</th><th>وضعیت</th><th>عملیات</th></tr></thead>
      <tbody>{rows_html if rows_html else '<tr><td colspan="9">هنوز فروشنده‌ای ثبت نشده.</td></tr>'}</tbody>
    </table>"""
    return render_page("فروشنده‌ها", "resellers", content)


@app.route("/resellers/<vkey>")
@login_required
def reseller_detail(vkey):
    v = find_vendor(vkey)
    if not v:
        flash("⚠️ فروشنده پیدا نشد.")
        return redirect(url_for("resellers_page"))
    tg_id = v["tg_id"]

    tg_line = (user_display(v["tg_name"], v["tg_user"], tg_id) if tg_id else '<span class="badge open">هنوز به تلگرام وصل نشده</span>')
    pw_html = secret_widget(v["password"]) if v["password"] else '<span class="badge open">تو دیتابیس ربات ثبت نشده؛ با تغییر رمز ثبت می‌شه</span>'
    copy_all = (f'<div><span>همه‌ی اطلاعات</span><button type="button" class="secondary sm" data-copy="{esc(vendor_login_text(v))}" '
                f'onclick="copyFrom(this)">📋 کپی آدرس پنل + نام کاربری + رمز</button></div>') if (v["name"] and v["password"]) else ""
    if v["on_service"]:
        manage = f"""
    <div class="card">
      <h3>🔐 رمز ورود به پنل فروشنده</h3>
      <small class="muted">نام کاربری روی سرویس قابل تغییر نیست؛ فقط رمز عوض می‌شه (مستقیم روی سرویس).</small>
      <form method="post" action="{url_for('reseller_credentials', vkey=vkey)}" autocomplete="off">
        <label for="new_password">رمز عبور جدید ({RESELLER_PASSWORD_MIN} تا {RESELLER_PASSWORD_MAX} کاراکتر)</label>
        <div class="flex"><input id="new_password" type="password" name="password" dir="ltr" autocomplete="new-password" style="flex:1;min-width:180px;" required>
          <button type="button" class="secondary" onclick="genPw('new_password')">🎲 ساخت رمز تصادفی</button></div>
        {'<label style="display:flex;align-items:center;gap:8px;cursor:pointer;margin-top:14px;"><input type="checkbox" name="notify" value="1"> <span>رمز جدید رو تو ربات برای خود فروشنده هم بفرست (به‌صورت متن ساده تو چت می‌ره)</span></label>' if tg_id else ''}
        <div style="margin-top:14px;"><button type="submit">💾 ذخیره‌ی رمز</button></div>
      </form>
    </div>
    <div class="grid cols-1">
      <div class="card"><h3>قیمت هر گیگ فروشنده (تومان)</h3>
        <form method="post" action="{url_for('reseller_price', vkey=vkey)}" class="flex">
          <input type="number" name="price_per_gb" value="{int(v['price']) if v['price'] else ''}" min="0" placeholder="۰ = قیمت پیش‌فرض خودت" style="flex:1;min-width:120px;" required>
          <button type="submit">ذخیره</button></form></div>
    </div>
    <div class="card"><h3>وضعیت حساب</h3>
      <form method="post" action="{url_for('reseller_toggle', vkey=vkey)}" class="flex">
        <button type="submit" class="{'danger' if v['status'] == 'active' else ''}">{'⛔ مسدود کردن فروشنده' if v['status'] == 'active' else '✅ فعال کردن فروشنده'}</button>
        <small class="muted">فروشنده‌ی مسدود نمی‌تونه از پنل سرویس استفاده کنه.</small></form></div>"""
    else:
        manage = """
    <div class="card"><small class="muted">این فروشنده هنوز تو لیست زیرمجموعه‌های سرویس نیست، برای همین حجم و تنظیماتش از اینجا قابل تغییر نیست.
    وقتی نام کاربری‌ش رو تو سرویس اضافه کنید یا خودش از ربات حساب بسازه، اینجا مدیریت می‌شه.</small></div>"""

    content = f"""
    <p><a class="btn secondary sm" href="{url_for('resellers_page')}">‹ بازگشت به فروشنده‌ها</a></p>
    <div class="card"><div class="kv">
      <div><span>فروشنده</span><b>{tg_line}</b></div>
      <div><span>آیدی عددی</span><b class="num">{tg_id or '—'}</b></div>
      <div><span>وضعیت</span><b>{_status_badge(v['status'])}</b></div>
      <div><span>پرداختی‌ها</span><b class="num">{int(v['paid'] or 0):,} تومان</b></div>
      <div><span>تعداد خرید</span><b class="num">{v['purchases']}</b></div>
      <div><span>نام کاربری</span><b>{copy_widget(v['name']) if v['name'] and v['name'] != '—' else '— تعیین نشده —'}</b></div>
      <div><span>رمز عبور</span><b>{pw_html}</b></div>
      {copy_all}
    </div></div>
    {manage}
    """
    return render_page(f"فروشنده {v['name'] or vkey}", "resellers", content)


def _need_service_vendor(vkey):
    """فروشنده‌ای که روی سرویس هست یا (None و flash)."""
    v = find_vendor(vkey)
    if not v:
        flash("⚠️ فروشنده پیدا نشد.")
        return None
    if not v["sub_id"]:
        flash("⚠️ این فروشنده تو لیست زیرمجموعه‌های سرویس نیست؛ تغییر ممکن نیست.")
        return None
    return v


def _after_vendor_action(vkey):
    if request.form.get("next") == "list":
        return redirect(url_for("resellers_page"))
    return _vendor_back(vkey)


@app.route("/resellers/<vkey>/credentials", methods=["POST"])
@login_required
def reseller_credentials(vkey):
    v = _need_service_vendor(vkey)
    if not v:
        return redirect(url_for("resellers_page"))
    pw = request.form.get("password", "")
    if not (RESELLER_PASSWORD_MIN <= len(pw) <= RESELLER_PASSWORD_MAX) or pw != pw.strip():
        flash(f"⚠️ رمز باید بین {RESELLER_PASSWORD_MIN} تا {RESELLER_PASSWORD_MAX} کاراکتر و بدون فاصله‌ی اول/آخر باشه.")
        return _vendor_back(vkey)
    res = seller_api("POST", f"/resale/subs/{v['sub_id']}/password", {"password": pw})
    if not res["success"]:
        flash("⚠️ رمز تغییر نکرد: " + seller_reason(res))
        return _vendor_back(vkey)
    if v["tg_id"]:
        try:
            save_seller_password_local(v["tg_id"], v["sub_id"], v["name"], v["panel_url"], pw)
        except Exception as e:
            print("⚠️ ذخیره‌ی رمز تو دیتابیس ناموفق بود:", e)
    flash(f"رمز فروشنده {v['name']} روی سرویس تغییر کرد.")
    if request.form.get("notify") == "1" and v["tg_id"]:
        text = (f"🔐 <b>رمز ورود شما به پنل فروشندگی تغییر کرد:</b>\n\n👤 نام کاربری: <code>{esc(v['name'])}</code>\n"
                f"🔑 رمز عبور: <code>{esc(pw)}</code>\n\nبعد از ورود، رمز رو تو جای امن نگه دارید.")
        flash("پیام رمز جدید برای فروشنده ارسال شد." if send_telegram_message(v["tg_id"], text)
              else "⚠️ رمز تغییر کرد ولی ارسال پیام به فروشنده ناموفق بود.")
    return _vendor_back(vkey)


@app.route("/resellers/<vkey>/toggle", methods=["POST"])
@login_required
def reseller_toggle(vkey):
    v = _need_service_vendor(vkey)
    if not v:
        return redirect(url_for("resellers_page"))
    new_status = "suspended" if v["status"] == "active" else "active"
    res = seller_api("PATCH", f"/resale/subs/{v['sub_id']}", {"status": new_status})
    invalidate_subs_cache()
    if res["success"]:
        flash(f"فروشنده {v['name']} {'فعال' if new_status == 'active' else 'مسدود'} شد.")
    else:
        flash("⚠️ وضعیت تغییر نکرد: " + seller_reason(res))
    return _after_vendor_action(vkey)


@app.route("/resellers/<vkey>/price", methods=["POST"])
@login_required
def reseller_price(vkey):
    v = _need_service_vendor(vkey)
    if not v:
        return redirect(url_for("resellers_page"))
    price = to_int(request.form.get("price_per_gb"))
    if price is None or price < 0:
        flash("⚠️ قیمت هر گیگ باید عدد صحیح (۰ یا بیشتر) باشه.")
        return _after_vendor_action(vkey)
    res = seller_api("PATCH", f"/resale/subs/{v['sub_id']}", {"modeOverride": "price", "gbTomanOverride": price})
    invalidate_subs_cache()
    if res["success"]:
        flash(f"قیمت هر گیگ فروشنده {v['name']} " + (f"به {price:,} تومان تغییر کرد." if price else "به قیمت پیش‌فرض برگشت."))
    else:
        flash("⚠️ قیمت تغییر نکرد: " + seller_reason(res))
    return _after_vendor_action(vkey)



# ---------- دکمه‌های سفارشی منوی ربات ----------
# ذخیره تو settings با کلید custom_buttons (JSON). بات هر ~۲۰ ثانیه می‌خونه و تو منوی اصلی نشون می‌ده.
# هر دکمه: id, label, label_en, type (message|link|goto), text, url, url_label, target, enabled

CUSTOM_BTN_KEY = "custom_buttons"
CUSTOM_BTN_MAX = 12
CUSTOM_BTN_TYPES = (("message", "📝 ارسال یک پیام"), ("link", "🔗 باز کردن یک لینک"), ("goto", "↪️ رفتن به یکی از بخش‌های ربات"))
CUSTOM_BTN_GOTO = [(k, d) for k, _l, d in BOT_BUTTONS]


def load_custom_buttons():
    try:
        items = json.loads(get_setting(CUSTOM_BTN_KEY, "") or "[]")
    except Exception:
        return []
    return [i for i in items if isinstance(i, dict) and i.get("id")] if isinstance(items, list) else []


def save_custom_buttons(items):
    set_setting(CUSTOM_BTN_KEY, json.dumps(items, ensure_ascii=False))


def parse_custom_button(form):
    """(dict, None) یا (None, پیام خطا)."""
    label = form.get("label", "").strip()
    kind = form.get("type", "message")
    text = form.get("text", "").strip()
    url = form.get("url", "").strip()
    target = form.get("target", "").strip()
    if not label or len(label) > 40:
        return None, "اسم دکمه باید بین ۱ تا ۴۰ حرف باشه."
    if kind not in dict(CUSTOM_BTN_TYPES):
        return None, "نوع دکمه نامعتبره."
    if len(text) > 3500:
        return None, "متن پیام خیلی طولانیه (حداکثر ۳۵۰۰ حرف)."
    if url and not url.lower().startswith(("http://", "https://")):
        return None, "لینک باید با http:// یا https:// شروع بشه."
    if kind == "message" and not text:
        return None, "برای نوع «ارسال پیام»، متن پیام رو بنویسید."
    if kind == "link" and not url:
        return None, "برای نوع «باز کردن لینک»، لینک رو بنویسید."
    if kind == "goto" and target not in dict(CUSTOM_BTN_GOTO):
        return None, "بخش مقصد رو انتخاب کنید."
    return {
        "label": label, "label_en": form.get("label_en", "").strip()[:40], "type": kind,
        "text": text, "url": url, "url_label": form.get("url_label", "").strip()[:40],
        "target": target if kind == "goto" else "", "enabled": form.get("enabled") == "1",
    }, None


def custom_button_fields(it):
    it = it or {}
    kind = it.get("type", "message")
    type_opts = "".join(f'<option value="{k}"{" selected" if k == kind else ""}>{esc(v)}</option>' for k, v in CUSTOM_BTN_TYPES)
    goto_opts = "".join(f'<option value="{k}"{" selected" if k == it.get("target") else ""}>{esc(v)}</option>' for k, v in CUSTOM_BTN_GOTO)
    return f"""
      <label>اسم دکمه (فارسی)</label>
      <input type="text" name="label" value="{esc(it.get('label', ''))}" maxlength="40" placeholder="مثلاً 📣 کانال ما" required>
      <label>اسم دکمه برای کاربران انگلیسی‌زبان (اختیاری)</label>
      <input type="text" name="label_en" value="{esc(it.get('label_en', ''))}" maxlength="40" dir="ltr">
      <label>وقتی کاربر روش می‌زنه چی بشه؟</label>
      <select name="type" onchange="cbtnType(this)">{type_opts}</select>
      <div data-for="message link">
        <label>متن پیامی که ربات می‌فرسته (HTML تلگرام مجاز است؛ برای نوع «لینک» اختیاری)</label>
        <textarea name="text" style="min-height:90px;">{esc(it.get('text', ''))}</textarea>
        <label>لینک (اختیاری برای پیام؛ الزامی برای نوع «لینک»)</label>
        <input type="url" name="url" value="{esc(it.get('url', ''))}" dir="ltr" placeholder="https://...">
        <label>نوشته‌ی دکمه‌ی لینک (اختیاری)</label>
        <input type="text" name="url_label" value="{esc(it.get('url_label', ''))}" maxlength="40" placeholder="🔗 باز کردن لینک">
      </div>
      <div data-for="goto">
        <label>کاربر به کدوم بخش ربات بره؟</label>
        <select name="target">{goto_opts}</select>
      </div>
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;margin-top:14px;">
        <input type="checkbox" name="enabled" value="1"{" checked" if it.get("enabled", True) else ""}> <span>نمایش تو منوی ربات</span></label>"""


@app.route("/custom-buttons")
@login_required
def custom_buttons_page():
    items = load_custom_buttons()
    cards = ""
    for n, it in enumerate(items):
        bid = it["id"]
        kind_txt = dict(CUSTOM_BTN_TYPES).get(it.get("type"), "—")
        on = it.get("enabled", True)
        cards += f"""
    <div class="card">
      <h3>{esc(it.get('label', ''))} <span class="badge {'on' if on else 'off'}">{'نمایش' if on else 'مخفی'}</span></h3>
      <small class="muted">{esc(kind_txt)}</small>
      <form method="post" action="{url_for('custom_button_save', bid=bid)}">{custom_button_fields(it)}
        <div class="flex" style="margin-top:14px;"><button type="submit">💾 ذخیره</button></div>
      </form>
      <div class="flex" style="margin-top:10px;">
        <form method="post" action="{url_for('custom_button_move', bid=bid, direction='up')}"><button type="submit" class="secondary sm"{' disabled' if n == 0 else ''}>⬆️ بالاتر</button></form>
        <form method="post" action="{url_for('custom_button_move', bid=bid, direction='down')}"><button type="submit" class="secondary sm"{' disabled' if n == len(items) - 1 else ''}>⬇️ پایین‌تر</button></form>
        <form method="post" action="{url_for('custom_button_delete', bid=bid)}" onsubmit="return confirm('این دکمه حذف بشه؟');"><button type="submit" class="danger sm">🗑 حذف</button></form>
      </div>
    </div>"""
    add_card = (f"""
    <div class="card"><h3>➕ دکمه‌ی جدید</h3>
      <form method="post" action="{url_for('custom_button_add')}">{custom_button_fields(None)}
        <div style="margin-top:14px;"><button type="submit">➕ اضافه کن</button></div>
      </form></div>""" if len(items) < CUSTOM_BTN_MAX else
        f'<div class="alert">⚠️ حداکثر {CUSTOM_BTN_MAX} دکمه‌ی سفارشی مجازه؛ برای اضافه کردن، یکی رو حذف کنید.</div>')
    content = f"""
    <div class="card"><small class="muted">دکمه‌هایی که اینجا بسازید، زیر دکمه‌های اصلی منوی ربات نمایش داده می‌شن (تا ۲۰ ثانیه بعد از ذخیره).
    می‌تونید تعیین کنید با زدن هر دکمه ربات یک پیام بفرسته، لینکی رو باز کنه، یا کاربر رو به یکی از بخش‌های خود ربات (خرید، پشتیبانی، ...) ببره.</small></div>
    {add_card}
    {cards}
    <script>
    function cbtnType(sel){{var f=sel.closest('form');f.querySelectorAll('[data-for]').forEach(function(e){{e.style.display=e.getAttribute('data-for').split(' ').indexOf(sel.value)>-1?'':'none';}});}}
    document.querySelectorAll('select[name=type]').forEach(cbtnType);
    </script>"""
    return render_page("دکمه‌های سفارشی", "custombtn", content)


@app.route("/custom-buttons/add", methods=["POST"])
@login_required
def custom_button_add():
    items = load_custom_buttons()
    if len(items) >= CUSTOM_BTN_MAX:
        flash(f"⚠️ حداکثر {CUSTOM_BTN_MAX} دکمه‌ی سفارشی مجازه.")
        return redirect(url_for("custom_buttons_page"))
    it, err = parse_custom_button(request.form)
    if err:
        flash("⚠️ " + err)
        return redirect(url_for("custom_buttons_page"))
    it["id"] = secrets.token_hex(3)
    items.append(it)
    save_custom_buttons(items)
    flash(f"دکمه‌ی «{it['label']}» اضافه شد.")
    return redirect(url_for("custom_buttons_page"))


@app.route("/custom-buttons/<bid>/save", methods=["POST"])
@login_required
def custom_button_save(bid):
    items = load_custom_buttons()
    idx = next((i for i, x in enumerate(items) if x["id"] == bid), None)
    if idx is None:
        flash("⚠️ دکمه پیدا نشد.")
        return redirect(url_for("custom_buttons_page"))
    it, err = parse_custom_button(request.form)
    if err:
        flash("⚠️ " + err)
        return redirect(url_for("custom_buttons_page"))
    it["id"] = bid
    items[idx] = it
    save_custom_buttons(items)
    flash(f"دکمه‌ی «{it['label']}» ذخیره شد.")
    return redirect(url_for("custom_buttons_page"))


@app.route("/custom-buttons/<bid>/move/<direction>", methods=["POST"])
@login_required
def custom_button_move(bid, direction):
    items = load_custom_buttons()
    idx = next((i for i, x in enumerate(items) if x["id"] == bid), None)
    if idx is not None:
        j = idx - 1 if direction == "up" else idx + 1
        if 0 <= j < len(items):
            items[idx], items[j] = items[j], items[idx]
            save_custom_buttons(items)
    return redirect(url_for("custom_buttons_page"))


@app.route("/custom-buttons/<bid>/delete", methods=["POST"])
@login_required
def custom_button_delete(bid):
    items = load_custom_buttons()
    new = [x for x in items if x["id"] != bid]
    if len(new) != len(items):
        save_custom_buttons(new)
        flash("دکمه حذف شد.")
    return redirect(url_for("custom_buttons_page"))


# ---------- پیام همگانی ----------

@app.route("/broadcast", methods=["GET", "POST"])
@login_required
def broadcast():
    if request.method == "POST":
        text = request.form.get("text", "").strip()
        if not text:
            flash("⚠️ متن پیام نمی‌تواند خالی باشد.")
        elif BROADCAST["running"]:
            flash("⚠️ یک ارسال همگانی هنوز در حال انجامه؛ صبر کنید تموم بشه.")
        else:
            user_ids = get_all_user_ids()
            threading.Thread(target=broadcast_worker, args=(text, user_ids), daemon=True).start()
            flash(f"ارسال پیام همگانی برای {len(user_ids):,} کاربر شروع شد (در پس‌زمینه ادامه می‌یابد).")
        return redirect(url_for("broadcast"))

    state = ""
    if BROADCAST["total"]:
        done = BROADCAST["sent"] + BROADCAST["failed"]
        state = (f'<div class="card"><b>{"⏳ در حال ارسال…" if BROADCAST["running"] else "✅ آخرین ارسال تمام شد"}</b>'
                 f'<p class="muted num" style="margin:6px 0 0;">{done:,} از {BROADCAST["total"]:,} — موفق: {BROADCAST["sent"]:,} · ناموفق: {BROADCAST["failed"]:,}</p></div>')
    content = f"""
    {state}
    <div class="card">
      <form method="post" onsubmit="return confirm('این پیام برای همه‌ی کاربران ارسال بشه؟');">
        <label>متن پیام همگانی (فرمت HTML تلگرام پشتیبانی می‌شود، مثل &lt;b&gt;بولد&lt;/b&gt;)</label>
        <textarea name="text" required></textarea>
        <div style="margin-top:12px;"><button type="submit">ارسال به همه‌ی کاربران</button></div>
      </form>
    </div>
    <p><small class="muted">این پیام برای همه‌ی کاربرانی که تا الان با ربات فروش /start زده‌اند ارسال می‌شود.</small></p>"""
    return render_page("پیام همگانی", "broadcast", content)


# ---------- اعلان فروش (بات sales_notifier.py این تنظیمات رو از جدول settings می‌خونه) ----------

SALE_NOTIFY_FIELDS = ("gb", "type", "days", "price", "time", "date", "user", "bot")
SALE_NOTIFY_DEFAULT_TEMPLATE = (
    "📦 {gb} گیگ {type}\n"
    "🕒 در ساعت {time}\n"
    "💰 با قیمت {price} تومان\n"
    "👤 توسط آیدی عددی {user}\n"
    "\n"
    "🛒 جهت خرید: {bot}"
)
SALE_NOTIFY_TYPES = (("config", "کانفیگ"), ("wireguard", "وایرگارد"), ("both", "کانفیگ + وایرگارد"),
                     ("openvpn", "OpenVPN"), ("dns", "DNS بازی"))
SALE_NOTIFY_SAMPLE = {"gb": "10", "type": "کانفیگ", "days": "30", "price": "35,000",
                      "time": "14:32", "date": "2026-10-12", "user": "45****90", "bot": "@SKYTUNNELbot"}


def sale_notify_render(tpl, values):
    return re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), m.group(0))), tpl)


@app.route("/sale-notify")
@login_required
def sale_notify_page():
    ensure_settings_table()
    st = get_all_settings()
    on = st.get("sale_notify_enabled", "1") == "1"
    channel = st.get("sale_notify_channel", "")
    bot_name = st.get("sale_notify_bot", "@SKYTUNNELbot")
    tpl = st.get("sale_notify_template") or SALE_NOTIFY_DEFAULT_TEMPLATE

    status_html = '<p class="muted">هنوز گزارشی از بات اعلان نرسیده؛ مطمئن شو sales_notifier.py در حال اجراست.</p>'
    raw = st.get("sale_notify_status")
    if raw:
        try:
            info = json.loads(raw)
            age = rel_time(info.get("ts"))
            stale = False
            dt = parse_ts(info.get("ts"))
            if dt and (datetime.now(timezone.utc) - dt).total_seconds() > 300:
                stale = True
            badge = "⛔ احتمالاً بات اعلان خاموشه" if stale else ("✅ سالم" if info.get("ok") else "⚠️ خطا")
            status_html = (f'<div class="kv"><div><span>وضعیت</span><b>{badge}</b></div>'
                           f'<div><span>اکانت</span><b dir="ltr">{esc(info.get("account") or "—")}</b></div>'
                           f'<div><span>آخرین گزارش</span><b>{esc(age)}</b></div></div>'
                           f'<p class="muted" style="margin:8px 0 0;">{esc(info.get("msg", ""))}</p>')
        except Exception:
            pass

    type_inputs = "".join(
        f'<div><label>نام نوع «{k}» در اعلان</label>'
        f'<input type="text" name="type_{k}" value="{esc(st.get("sale_notify_type_" + k, ""))}" placeholder="{esc(d)}"></div>'
        for k, d in SALE_NOTIFY_TYPES)

    preview = esc(re.sub(r"<[^>]+>", "", sale_notify_render(tpl, {**SALE_NOTIFY_SAMPLE, "bot": bot_name or "@SKYTUNNELbot"})))
    fields_hint = " ".join(f"<code>{{{f}}}</code>" for f in SALE_NOTIFY_FIELDS)

    content = f"""
    <div class="card"><h3>وضعیت بات اعلان</h3>{status_html}</div>

    <div class="card">
      <div class="switch-row" style="padding-top:0;">
        <div><b>📢 اعلان خودکار فروش</b><br><small class="muted">با هر خرید موفق، یه پیام توی کانال ارسال می‌شه.</small></div>
        <form method="post" action="{url_for('sale_notify_toggle')}">{tgl_btn(on)}</form>
      </div>
    </div>

    <form method="post" action="{url_for('sale_notify_save')}">
      <div class="card">
        <label>کانال‌های اعلان فروش (هر خط یه کانال، حداکثر ۱۰ تا؛ یوزرنیم یا لینک عمومی مثل https://splus.ir/mychannel — اکانتِ بات اعلان باید تو همه‌شون ادمین باشه)</label>
        <textarea name="channel" dir="ltr" style="min-height:90px;" placeholder="https://splus.ir/mychannel&#10;https://splus.ir/otherchannel">{esc(channel)}</textarea>
        <label style="margin-top:12px;">یوزرنیم بات فروش (برای «جهت خرید»)</label>
        <input type="text" name="bot" value="{esc(bot_name)}" dir="ltr" placeholder="@SKYTUNNELbot">
        <label style="margin-top:12px;">متن اعلان (متن ساده؛ ایموجی و خط جدید مجازه)</label>
        <textarea name="template" dir="rtl" style="min-height:170px;" required>{esc(tpl)}</textarea>
        <p class="muted" style="margin:6px 0 0;"><small>متغیرها: {fields_hint}<br>
          <code>{{user}}</code> آیدی خریدار به‌صورت نیمه‌مخفی (مثل 45****90) نمایش داده می‌شه.</small></p>
      </div>
      <div class="card"><h3>نام نوع سرویس‌ها (اختیاری)</h3>
        <div class="kv" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr));">{type_inputs}</div>
        <p class="muted" style="margin:6px 0 0;"><small>خالی بذاری، اسم پیش‌فرض (داخل کادر) استفاده می‌شه.</small></p>
      </div>
      <div class="card"><h3>پیش‌نمایش</h3>
        <pre style="white-space:pre-wrap;margin:0;font-family:inherit;line-height:1.9;">{preview}</pre></div>
      <div style="margin:12px 0;"><button type="submit">ذخیره</button>
        <button type="submit" formaction="{url_for('sale_notify_test')}" formnovalidate style="margin-inline-start:8px;">💾 ذخیره و ارسال پیام تست</button></div>
    </form>
    <p><small class="muted">فقط خریدهای واقعیِ بعد از روشن‌شدن اعلان می‌شن؛ خرید قبلی و تست رایگان اعلان نمی‌شن.</small></p>"""
    return render_page("اعلان فروش", "salenotify", content)


def _sale_notify_save_form():
    """فرم رو اعتبارسنجی و ذخیره می‌کنه؛ True اگه همه‌چی ذخیره شد."""
    channels = []
    for part in re.split(r"[\s,;،]+", request.form.get("channel", "")):
        part = part.strip()
        if part and part not in channels:
            channels.append(part)
    if len(channels) > 10:
        flash("⚠️ حداکثر ۱۰ کانال مجازه — ذخیره نشد.")
        return False
    for ch in channels:
        m = re.fullmatch(r"(?:https?://)?(?:splus\.ir/|sapp\.ir/)?@?([A-Za-z0-9_.\-]{3,64})/?(?:\?.*)?", ch) \
            or re.fullmatch(r"-?\d+", ch)
        if not m or "+" in ch or "joinchat" in ch.lower():
            flash(f"⚠️ کانال نامعتبره: {ch} (لینک دعوت خصوصی پشتیبانی نمی‌شه؛ یوزرنیم عمومی یا آیدی عددی بده) — ذخیره نشد.")
            return False
    channel = "\n".join(channels)
    bot_name = request.form.get("bot", "").strip()
    tpl = request.form.get("template", "").replace("\r\n", "\n").strip()
    if bot_name and not re.fullmatch(r"@?[A-Za-z0-9_]{3,64}", bot_name):
        flash("⚠️ یوزرنیم بات نامعتبره — ذخیره نشد.")
        return False
    if bot_name and not bot_name.startswith("@"):
        bot_name = "@" + bot_name
    if not tpl:
        flash("⚠️ متن اعلان نمی‌تواند خالی باشد — ذخیره نشد.")
        return False
    if len(tpl) > 1500:
        flash("⚠️ متن اعلان خیلی بلنده (حداکثر ۱۵۰۰ کاراکتر) — ذخیره نشد.")
        return False
    err = validate_template(tpl, SALE_NOTIFY_FIELDS)
    if err:
        flash(f"⚠️ متن اعلان: {err} — ذخیره نشد.")
        return False

    def put(key, value, default=""):
        if value and value != default:
            set_setting(key, value)
        else:
            delete_setting(key)

    put("sale_notify_channel", channel)
    put("sale_notify_bot", bot_name, "@SKYTUNNELbot")
    put("sale_notify_template", tpl, SALE_NOTIFY_DEFAULT_TEMPLATE)
    for k, _d in SALE_NOTIFY_TYPES:
        put("sale_notify_type_" + k, request.form.get("type_" + k, "").strip()[:40])
    return True


@app.route("/sale-notify/save", methods=["POST"])
@login_required
def sale_notify_save():
    if _sale_notify_save_form():
        flash("تنظیمات اعلان فروش ذخیره شد (حداکثر چند ثانیه بعد روی بات اعلان اعمال می‌شه).")
    return redirect(url_for("sale_notify_page"))


@app.route("/sale-notify/test", methods=["POST"])
@login_required
def sale_notify_test():
    if _sale_notify_save_form():
        set_setting("sale_notify_test_req", secrets.token_hex(6))
        flash("ذخیره شد و درخواست پیام تست ثبت شد؛ چند ثانیه بعد صفحه رو رفرش کن و وضعیت رو ببین.")
    return redirect(url_for("sale_notify_page"))


@app.route("/sale-notify/toggle", methods=["POST"])
@login_required
def sale_notify_toggle():
    cur = get_setting("sale_notify_enabled", "1")
    set_setting("sale_notify_enabled", "0" if cur == "1" else "1")
    flash("اعلان فروش " + ("خاموش شد." if cur == "1" else "روشن شد."))
    return redirect(url_for("sale_notify_page"))


# ---------- ذخیره‌ی تنظیمات / ظاهر / متن‌ها / کد تخفیف ----------

@app.route("/settings/save-config", methods=["POST"])
@login_required
def save_config():
    current = get_all_settings()
    saved = reset = 0
    for key, label, default, kind in CONFIG_SETTINGS:
        if key not in request.form:
            continue
        raw = request.form.get(key, "").strip()
        if raw == "":
            if key in current:
                delete_setting(key)
                reset += 1
            continue
        value, err = normalize_setting(kind, raw)
        if err:
            flash(f"⚠️ «{label}»: {err} — ذخیره نشد.")
            continue
        if key == "refund_ratio" and float(value) > 1:
            flash(f"⚠️ «{label}»: باید بین 0 و 1 باشه — ذخیره نشد.")
            continue
        if key == "admin_id" and int(value) <= 0:
            flash(f"⚠️ «{label}»: باید یک آیدی عددی معتبر باشه — ذخیره نشد.")
            continue
        if key == "trial_proto" and value.lower() not in ("both", "xray", "wireguard", "openvpn", "dns"):
            flash(f"⚠️ «{label}»: فقط یکی از both / xray / wireguard / openvpn / dns مجازه — ذخیره نشد.")
            continue
        if key == "trial_proto":
            value = value.lower()
        if key == "bot_username":
            value = value.lstrip("@")
        if key == "trial_gb" and float(value) <= 0:
            flash(f"⚠️ «{label}»: باید بزرگ‌تر از صفر باشه — ذخیره نشد.")
            continue
        default_norm, _e = normalize_setting(kind, str(default))
        if value == (default_norm or str(default)):
            if key in current:
                delete_setting(key)
                reset += 1
            continue
        if current.get(key) != value:
            set_setting(key, value)
            saved += 1

    flash(f"تنظیمات ذخیره شد ({saved} تغییر، {reset} برگشت به پیش‌فرض).")
    return redirect(url_for("settings_page"))


@app.route("/settings/toggle-config/<key>", methods=["POST"])
@login_required
def toggle_config(key):
    if key in TOGGLE_DEFAULTS:
        current = get_setting(key, TOGGLE_DEFAULTS[key])
        set_setting(key, "0" if current == "1" else "1")
        flash("وضعیت تغییر کرد: " + ("روشن شد." if current != "1" else "خاموش شد."))
    return redirect(url_for("settings_page"))


@app.route("/settings/toggle/<key>", methods=["POST"])
@login_required
def toggle_setting(key):
    if key in FEATURES:
        current = get_setting(key, "1")
        set_setting(key, "0" if current == "1" else "1")
        flash(f"وضعیت «{FEATURES[key]}» تغییر کرد.")
    return redirect(url_for("settings_page"))




@app.route("/appearance")
@login_required
def appearance_page():
    ensure_settings_table()
    all_settings = get_all_settings()
    keyboard_style = all_settings.get("keyboard_style", "reply")

    main_order = get_ordered_keys("menu_order_main", MAIN_MENU_KEYS, all_settings)
    main_labels = {key: label for key, label, _default in BOT_BUTTONS}
    main_defaults = {key: default for key, _label, default in BOT_BUTTONS}
    buttons_html = ""
    for key in main_order:
        value = all_settings.get("btn_" + key, main_defaults[key])
        buttons_html += f"""
        <div class="reorder-row" data-key="{key}">
          <div>
            <label>{main_labels[key]}</label>
            <input type="text" name="btn_{key}" value="{esc(value)}" required>
          </div>
          <div class="reorder-arrows">
            <button type="button" class="secondary" onclick="moveRow(this,-1)" title="بالا">▲</button>
            <button type="button" class="secondary" onclick="moveRow(this,1)" title="پایین">▼</button>
          </div>
        </div>
        """

    buytype_order = get_ordered_keys("menu_order_buytypes", CONFIG_TYPE_KEYS, all_settings)
    buytype_labels = {key: label for key, label, _default in CONFIG_TYPE_BUTTONS}
    buytype_defaults = {key: default for key, _label, default in CONFIG_TYPE_BUTTONS}
    buytype_buttons_html = ""
    for key in buytype_order:
        value = all_settings.get("ctype_label_" + key, buytype_defaults[key])
        buytype_buttons_html += f"""
        <div class="reorder-row" data-key="{key}">
          <div>
            <label>{buytype_labels[key]}</label>
            <input type="text" name="ctype_label_{key}" value="{esc(value)}" required>
          </div>
          <div class="reorder-arrows">
            <button type="button" class="secondary" onclick="moveRow(this,-1)" title="بالا">▲</button>
            <button type="button" class="secondary" onclick="moveRow(this,1)" title="پایین">▼</button>
          </div>
        </div>
        """

    content = f"""
    <div class="panel">
      <form method="post" action="{url_for('save_appearance')}" id="appearanceForm">
        <h3 style="margin-top:0;">⌨️ نوع کیبورد منوی اصلی</h3>
        <div class="flex" style="margin-bottom:14px;">
          <label class="flex" style="cursor:pointer;">
            <input type="radio" name="keyboard_style" value="reply" {"checked" if keyboard_style == "reply" else ""}>
            <span>کیبورد ثابت پایین صفحه (روش فعلی)</span>
          </label>
          <label class="flex" style="cursor:pointer;">
            <input type="radio" name="keyboard_style" value="inline" {"checked" if keyboard_style == "inline" else ""}>
            <span>دکمه‌های شیشه‌ای زیر پیام (اینلاین)</span>
          </label>
        </div>

        <h3>💬 متن‌های ربات</h3>
        <p class="muted" style="font-size:12.5px;margin:0 0 10px;">همه‌ی متن‌های ربات (فارسی و انگلیسی؛ پیام‌ها، فاکتور، دکمه‌های داخل پیام، پیام‌های ادمین و ...) در صفحه‌ی <a href="{url_for('texts_page')}">📝 همه‌ی متن‌های ربات</a> قابل ویرایش‌اند.</p>
        <div class="flex" style="margin:0 0 14px;">
          <a class="btn secondary" href="{url_for('texts_page', lang='fa', view='buttons')}">🔘 ویرایش همه‌ی دکمه‌ها (فارسی)</a>
          <a class="btn secondary" href="{url_for('texts_page', lang='en', view='buttons')}">🔘 All buttons (English)</a>
          <a class="btn secondary" href="{url_for('texts_page', lang='fa', view='messages')}">💬 ویرایش همه‌ی پیام‌ها</a>
        </div>

        <h3>🔘 دکمه‌های منوی اصلی</h3>
        <p class="muted" style="font-size:12.5px;margin:0 0 10px;">با فلش‌ها ترتیبشون رو عوض کن، تو کادر هم اسم دلخواه رو بنویس؛ با «ذخیره‌ی تغییرات» پایین صفحه هر دو با هم ذخیره می‌شن.</p>
        <div class="reorder-list" id="mainBtnList">
          {buttons_html}
        </div>
        <input type="hidden" name="order_main" id="order_main">

        <h3>🛍 دکمه‌های انتخاب نوع سرویس (صفحه‌ی خرید)</h3>
        <p class="muted" style="font-size:12.5px;margin:0 0 10px;">همین ترتیب و اسم‌ها، هم تو پیام «نوع سرویس مورد نظر را انتخاب کنید» و هم هرجای دیگه‌ای که این نوع سرویس‌ها نشون داده می‌شن اعمال می‌شه.</p>
        <div class="reorder-list" id="buytypeBtnList">
          {buytype_buttons_html}
        </div>
        <input type="hidden" name="order_buytypes" id="order_buytypes">

        <div style="margin-top:14px;"><button type="submit">💾 ذخیره‌ی تغییرات</button></div>
      </form>
    </div>
    <p><small class="muted">این تغییرات مستقیم روی خود ربات تلگرام اعمال می‌شوند (بدون نیاز به ری‌استارت).</small></p>
    <script>
      function moveRow(btn, dir) {{
        var row = btn.closest('.reorder-row');
        var list = row.parentElement;
        if (dir === -1) {{
          var prev = row.previousElementSibling;
          if (prev) list.insertBefore(row, prev);
        }} else {{
          var next = row.nextElementSibling;
          if (next) list.insertBefore(next, row);
        }}
      }}
      document.getElementById('appearanceForm').addEventListener('submit', function() {{
        function serialize(containerId, hiddenId) {{
          var container = document.getElementById(containerId);
          var rows = container.querySelectorAll('.reorder-row');
          var keys = Array.prototype.map.call(rows, function(r) {{ return r.getAttribute('data-key'); }});
          document.getElementById(hiddenId).value = keys.join(',');
        }}
        serialize('mainBtnList', 'order_main');
        serialize('buytypeBtnList', 'order_buytypes');
      }});
    </script>
    """
    return render_page("دکمه‌ها و ظاهر ربات", "appearance", content)


@app.route("/appearance/save", methods=["POST"])
@login_required
def save_appearance():
    style = request.form.get("keyboard_style", "reply")
    set_setting("keyboard_style", "inline" if style == "inline" else "reply")

    for key, _label, _default in BOT_BUTTONS:
        value = request.form.get("btn_" + key, "").strip()
        if value:
            set_setting("btn_" + key, value)

    for key, _label, _default in CONFIG_TYPE_BUTTONS:
        value = request.form.get("ctype_label_" + key, "").strip()
        if value:
            set_setting("ctype_label_" + key, value)

    order_main = request.form.get("order_main", "").strip()
    if order_main:
        keys = [k for k in order_main.split(",") if k in MAIN_MENU_KEYS]
        for k in MAIN_MENU_KEYS:
            if k not in keys:
                keys.append(k)
        if keys:
            set_setting("menu_order_main", ",".join(keys))

    order_buytypes = request.form.get("order_buytypes", "").strip()
    if order_buytypes:
        keys = [k for k in order_buytypes.split(",") if k in CONFIG_TYPE_KEYS]
        for k in CONFIG_TYPE_KEYS:
            if k not in keys:
                keys.append(k)
        if keys:
            set_setting("menu_order_buytypes", ",".join(keys))

    flash("دکمه‌ها و ظاهر ربات ذخیره شد.")
    return redirect(url_for("appearance_page"))



TEXTS_CSS_JS = """
<style>
  details.grp { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; margin-bottom: 12px; }
  details.grp > summary { cursor: pointer; padding: 14px 16px; font-weight: 700; list-style: none; display: flex; justify-content: space-between; gap: 8px; }
  details.grp > summary::-webkit-details-marker { display: none; }
  details.grp > summary small { color: var(--muted); font-weight: 500; }
  details.grp[open] > summary { border-bottom: 1px solid var(--border); }
  .txt { padding: 4px 16px 14px; border-bottom: 1px dashed var(--border); }
  .txt:last-child { border-bottom: none; }
  .txt label { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
  .txt code.key { direction: ltr; font-size: 11.5px; color: var(--muted); font-weight: 400; }
  .txt textarea { font-size: 14px; line-height: 1.7; }
  .txt .ref { font-size: 12.5px; color: var(--muted); background: var(--surface-2); border-radius: 8px; padding: 6px 10px; margin-top: 6px; white-space: pre-wrap; }
  .chips { display: flex; gap: 6px; flex-wrap: wrap; margin: 4px 0 6px; }
  .chip { font-family: monospace; font-size: 12px; padding: 2px 9px; border-radius: 6px; background: var(--accent-dim); color: var(--accent); border: none; cursor: pointer; direction: ltr; }
  .txt-actions { margin-top: 6px; }
  .txt-actions button { padding: 4px 12px; font-size: 12px; }
  .savebar { position: sticky; bottom: var(--nav-h); z-index: 5; padding: 10px 0; background: linear-gradient(transparent, var(--bg) 35%); }
</style>
<script>
  function insertAt(btn) {
    var ta = btn.closest('.txt').querySelector('textarea, input[type=text]');
    var ph = btn.getAttribute('data-ph');
    var s = ta.selectionStart || 0, e = ta.selectionEnd || 0;
    ta.value = ta.value.slice(0, s) + ph + ta.value.slice(e);
    ta.focus(); ta.selectionStart = ta.selectionEnd = s + ph.length;
  }
  function resetTxt(btn) {
    var box = btn.closest('.txt');
    box.querySelector('textarea, input[type=text]').value = box.getAttribute('data-default');
  }
  function filterTexts() {
    var q = document.getElementById('q').value.trim().toLowerCase();
    var shown = 0;
    document.querySelectorAll('.txt').forEach(function (el) {
      var hit = !q || el.getAttribute('data-search').indexOf(q) > -1;
      el.style.display = hit ? '' : 'none';
      if (hit) shown++;
    });
    document.querySelectorAll('details.grp').forEach(function (d) {
      var any = false;
      d.querySelectorAll('.txt').forEach(function (t) { if (t.style.display !== 'none') any = true; });
      d.style.display = any ? '' : 'none';
      if (q && any) d.open = true;
    });
    document.getElementById('count').textContent = q ? (shown + ' مورد پیدا شد') : '';
  }
</script>
"""


_BUTTON_KEY_PREFIXES = ("btn_", "menu_btn_", "ctype_btn_", "lang_btn_", "plat_", "svc_", "admin_btn_")
_BUTTON_KEYS_EXACT = {"qty_continue", "ask_label_skip"}


def is_button_key(key):
    """کلیدهایی که متن یه «دکمه» هستن (نه پیام)؛ برای فیلتر «فقط دکمه‌ها» تو صفحه‌ی متن‌ها."""
    return key in _BUTTON_KEYS_EXACT or key.startswith(_BUTTON_KEY_PREFIXES)


@app.route("/texts")
@login_required
def texts_page():
    lang = "en" if request.args.get("lang") == "en" else "fa"
    view = request.args.get("view", "all")
    if view not in ("all", "buttons", "messages"):
        view = "all"
    registry = load_text_registry()
    if not registry:
        content = """
        <div class="panel">
          <h3 style="margin-top:0;">⏳ هنوز لیست متن‌ها از ربات نرسیده</h3>
          <p>ربات موقع هر بار روشن‌شدن، لیست کامل متن‌هاش رو برای این پنل ثبت می‌کنه.
          نسخه‌ی جدید <b>bot.py</b> رو روی سرور جایگزین کنید و ربات رو یک‌بار <b>ری‌استارت</b> کنید، بعد این صفحه رو دوباره باز کنید.</p>
        </div>"""
        return render_page("همه‌ی متن‌های ربات", "texts", content)

    all_settings = get_all_settings()
    items = registry.get(lang, [])
    if view == "buttons":
        items = [it for it in items if is_button_key(it["k"])]
    elif view == "messages":
        items = [it for it in items if not is_button_key(it["k"])]
    by_group = {}
    for it in items:
        by_group.setdefault(it["g"], []).append(it)
    order = [g for g in registry.get("groups", []) if g in by_group] + [g for g in by_group if g not in registry.get("groups", [])]

    groups_html = ""
    for g in order:
        boxes = ""
        for it in by_group[g]:
            key, setting, default = it["k"], it["s"], it["d"]
            overridden = setting in all_settings
            value = all_settings.get(setting, default)
            rows = max(2, min(14, value.count("\n") + 2, 14))
            as_button = is_button_key(key)
            chips = "".join(
                f'<button type="button" class="chip" data-ph="{{{esc(p)}}}" onclick="insertAt(this)">{{{esc(p)}}}</button>'
                for p in it.get("p", [])
            )
            chips_html = f'<div class="chips">{chips}</div>' if chips else ""
            ref = it.get("ref", "")
            ref_html = f'<div class="ref">متن فارسی (مرجع):\n{esc(ref)}</div>' if (ref and not default) else ""
            ph_attr = f' placeholder="{esc(ref)}"' if (ref and not default) else ""
            badge = '<span class="badge on">سفارشی</span>' if overridden else ""
            if as_button:
                field_html = f'<input type="text" name="t__{esc(setting)}" value="{esc(value)}" maxlength="64"{ph_attr}>'
            else:
                field_html = f'<textarea name="t__{esc(setting)}" rows="{rows}"{ph_attr}>{esc(value)}</textarea>'
            search = esc((key + " " + default + " " + value + " " + ref).lower())
            boxes += f"""
            <div class="txt" data-default="{esc(default)}" data-search="{search}">
              <label>{badge}<code class="key">{esc(key)}</code></label>
              {chips_html}
              {field_html}
              {ref_html}
              <div class="txt-actions"><button type="button" class="secondary" onclick="resetTxt(this)">↩ پیش‌فرض</button></div>
            </div>"""
        groups_html += f'<details class="grp"><summary><span>{g}</span><small>{len(by_group[g])} متن</small></summary>{boxes}</details>'

    tab_fa = "btn" if lang == "fa" else "btn secondary"
    tab_en = "btn" if lang == "en" else "btn secondary"
    vt = {v: ("btn" if view == v else "btn secondary") for v in ("all", "buttons", "messages")}
    note_en = ("<p class='muted' style='font-size:12.5px;'>متن‌هایی که ترجمه‌ی انگلیسی ندارن (کادرشون خالیه) فعلاً برای کاربران انگلیسی‌زبان "
               "به‌صورت فارسی نمایش داده می‌شن؛ اگه ترجمه‌شون رو بنویسید جایگزین می‌شه.</p>") if lang == "en" else ""

    content = f"""
    {TEXTS_CSS_JS}
    <div class="panel">
      <div class="flex" style="margin-bottom:12px;">
        <a class="{tab_fa}" href="{url_for('texts_page', lang='fa', view=view)}">🇮🇷 فارسی</a>
        <a class="{tab_en}" href="{url_for('texts_page', lang='en', view=view)}">🇬🇧 English</a>
      </div>
      <div class="flex" style="margin-bottom:12px;">
        <a class="{vt['all']}" href="{url_for('texts_page', lang=lang, view='all')}">همه</a>
        <a class="{vt['buttons']}" href="{url_for('texts_page', lang=lang, view='buttons')}">🔘 فقط دکمه‌ها</a>
        <a class="{vt['messages']}" href="{url_for('texts_page', lang=lang, view='messages')}">💬 فقط پیام‌ها</a>
      </div>
      <input type="text" id="q" placeholder="🔎 جستجو در متن‌ها (کلید یا بخشی از متن)..." oninput="filterTexts()">
      <small class="muted" id="count"></small>
      <p class="muted" style="font-size:12.5px;margin:10px 0 0;">
        هر متن را ویرایش و ذخیره کنید؛ همان لحظه (حداکثر ~۲۰ ثانیه) روی ربات اعمال می‌شود.
        عبارت‌های داخل آکولاد مثل <code>{{wallet}}</code> جاهایی‌اند که ربات مقدار واقعی را می‌گذارد؛ اسمشان را عوض نکنید
        (با زدن روی هر دکمه‌ی آبی داخل متن درج می‌شود). کادر را خالی بگذارید یا «↩ پیش‌فرض» بزنید تا به متن اصلی برگردد.
        تگ‌های <code>&lt;b&gt;</code> و <code>&lt;code&gt;</code> برای پررنگ‌کردن و کپی‌شدن متن‌اند.
      </p>
      {note_en}
    </div>
    <form method="post" action="{url_for('texts_save')}">
      <input type="hidden" name="lang" value="{lang}">
      <input type="hidden" name="view" value="{view}">
      {groups_html}
      <div class="savebar"><button type="submit" class="block">💾 ذخیره‌ی تغییرات ({'فارسی' if lang == 'fa' else 'English'})</button></div>
    </form>
    <p><small class="muted">دکمه‌های منوی اصلی و نام نوع سرویس‌ها (فارسی) هم همین‌جا در گروه «🔘 دکمه‌های منوی اصلی و نوع سرویس» قابل ویرایش‌اند؛ فقط «ترتیب» دکمه‌ها در صفحه‌ی «دکمه‌ها و ظاهر» تنظیم می‌شود.</small></p>
    """
    return render_page("همه‌ی متن‌های ربات", "texts", content)


@app.route("/texts/save", methods=["POST"])
@login_required
def texts_save():
    lang = "en" if request.form.get("lang") == "en" else "fa"
    view = request.form.get("view", "all")
    if view not in ("all", "buttons", "messages"):
        view = "all"
    registry = load_text_registry()
    if not registry:
        flash("⚠️ لیست متن‌ها از ربات دریافت نشده؛ ربات را ری‌استارت کنید.")
        return redirect(url_for("texts_page", lang=lang, view=view))

    current = get_all_settings()
    saved = reset = 0
    errors = []
    for it in registry.get(lang, []):
        field = "t__" + it["s"]
        if field not in request.form:
            continue
        value = request.form[field].replace("\r\n", "\n").strip()
        default = it["d"].strip()
        stored = current.get(it["s"])
        if value == "" or value == default:
            if stored is not None:
                delete_setting(it["s"])
                reset += 1
            continue
        if stored is not None and value == stored.strip():
            continue
        if stored is None and value == default:
            continue
        err = validate_template(value, it.get("p", []))
        if err:
            errors.append(f"«{it['k']}»: {err}")
            continue
        set_setting(it["s"], value)
        saved += 1

    flash(f"{saved} متن ذخیره شد، {reset} متن به پیش‌فرض برگشت.")
    for e in errors[:8]:
        flash("⚠️ ذخیره نشد — " + e)
    if len(errors) > 8:
        flash(f"⚠️ و {len(errors) - 8} خطای دیگر.")
    return redirect(url_for("texts_page", lang=lang, view=view))


DISCOUNT_LIST_HTML_HEADER = ""



@app.route("/discounts")
@login_required
def discount_codes():
    ensure_discount_table()
    codes = get_all_discount_codes()
    rows_html = ""
    for code, percent, max_uses, used_count, active in codes:
        badge = '<span class="badge on">فعال</span>' if active == 1 else '<span class="badge off">غیرفعال</span>'
        toggle_label = "غیرفعال کن" if active == 1 else "فعال کن"
        rows_html += f"""
        <tr>
          <td>{esc(code)}</td>
          <td>{percent}٪</td>
          <td>{used_count} از {max_uses}</td>
          <td>{badge}</td>
          <td class="flex">
            <form method="post" action="{url_for('toggle_discount', code=code)}">
              <button type="submit" class="secondary">{toggle_label}</button>
            </form>
            <form method="post" action="{url_for('delete_discount', code=code)}" onsubmit="return confirm('حذف این کد تخفیف؟');">
              <button type="submit" class="danger">حذف</button>
            </form>
          </td>
        </tr>
        """

    content = f"""
    <div class="panel">
      <form method="post" action="{url_for('create_discount')}" class="flex">
        <input type="text" name="code" placeholder="کد (مثل SUMMER20)" style="width:160px;" required>
        <input type="number" name="percent" placeholder="درصد تخفیف" style="width:130px;" min="1" max="100" required>
        <input type="number" name="max_uses" placeholder="سقف تعداد استفاده" style="width:150px;" min="1" required>
        <button type="submit">ساخت کد تخفیف</button>
      </form>
    </div>
    <table>
      <tr><th>کد</th><th>درصد</th><th>مصرف</th><th>وضعیت</th><th></th></tr>
      {rows_html if rows_html else '<tr><td colspan="5">هنوز کد تخفیفی ثبت نشده.</td></tr>'}
    </table>
    """
    return render_page("کدهای تخفیف", "discounts", content)


@app.route("/discounts/create", methods=["POST"])
@login_required
def create_discount():
    code = request.form.get("code", "").strip()
    try:
        percent = int(request.form.get("percent", ""))
        max_uses = int(request.form.get("max_uses", ""))
    except ValueError:
        flash("درصد و سقف استفاده باید عدد باشند.")
        return redirect(url_for("discount_codes"))

    if not code:
        flash("کد نمی‌تواند خالی باشد.")
    elif code_exists(code):
        flash("این کد از قبل وجود دارد.")
    elif not (1 <= percent <= 100):
        flash("درصد تخفیف باید بین ۱ تا ۱۰۰ باشد.")
    else:
        create_discount_code(code, percent, max_uses)
        flash(f"کد «{code.upper()}» ساخته شد.")
    return redirect(url_for("discount_codes"))


@app.route("/discounts/<code>/toggle", methods=["POST"])
@login_required
def toggle_discount(code):
    toggle_discount_code(code)
    flash(f"وضعیت کد «{code}» تغییر کرد.")
    return redirect(url_for("discount_codes"))


@app.route("/discounts/<code>/delete", methods=["POST"])
@login_required
def delete_discount(code):
    delete_discount_code(code)
    flash(f"کد «{code}» حذف شد.")
    return redirect(url_for("discount_codes"))




# ===========================================================================
# افزونه‌ها: پست‌گذاری در کانال‌ها، مدیریت کانفیگ کاربران، سفارش‌ها، بکاپ و خروجی
# هدف: هر کاری که ادمین تو سروش می‌کرد، از همین پنل هم قابل انجام باشه.
# ===========================================================================
import csv
import io
from concurrent.futures import ThreadPoolExecutor
from flask import Response

CONFIG_API = os.getenv("CONFIG_API", "https://su.randomatic.ir/api/v1/configs")
CONFIG_KEY = os.getenv("CONFIG_KEY", "").strip()

ICONS.update({
    "channels": '<path d="M3 11v2a1 1 0 0 0 1 1h3l6 4V6L7 10H4a1 1 0 0 0-1 1z"/><path d="M17 8.5a5 5 0 0 1 0 7M19.5 6a8.5 8.5 0 0 1 0 12"/>',
    "orders": '<path d="M6 3h12l2 4v13H4V7z"/><path d="M4 7h16M9 11h6"/>',
    "backup": '<path d="M12 3v12m0 0l-4-4m4 4l4-4"/><path d="M4 17v3h16v-3"/>',
})
NAV[1][1].append(("orders", "سفارش‌ها", "orders_page"))
NAV[2][1].append(("channels", "کانال‌ها و پست", "channels_page"))
NAV[3][1].append(("backup", "بکاپ و خروجی", "backup_page"))

PANEL_CH_KEY = "panel_channels"
PANEL_POST_LOG_KEY = "panel_post_log"
DEFAULT_GATE_LINK = os.getenv("CHANNEL_LINK", "https://splus.ir/skytunnel").strip()


def _load_json_setting(key, default):
    try:
        v = json.loads(get_setting(key, "") or "")
    except Exception:
        return default
    return v if isinstance(v, type(default)) else default


def norm_target(raw):
    """لینک عمومی / @یوزرنیم / آیدی عددی → هدف Bot API (یا None اگه نامعتبر)."""
    s = str(raw or "").strip()
    if not s:
        return None
    if re.fullmatch(r"-?\d{5,20}", s):
        return int(s)
    s = s.split("?")[0].rstrip("/")
    name = s.split("/")[-1].lstrip("@")
    if "+" in s or "joinchat" in s.lower() or not re.fullmatch(r"[A-Za-z0-9_.\-]{3,64}", name):
        return None
    return "@" + name


def gate_links():
    raw = get_setting("gate_channels", None)
    if raw is None:
        return [DEFAULT_GATE_LINK] if DEFAULT_GATE_LINK else []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    return [str(x).strip() for x in data if str(x).strip()] if isinstance(data, list) else []


def channel_list():
    out, seen = [], set()
    for c in _load_json_setting(PANEL_CH_KEY, []):
        if isinstance(c, dict) and c.get("target"):
            out.append({"id": str(c.get("id")), "title": str(c.get("title") or c["target"]),
                        "target": c["target"], "src": "panel"})
            seen.add(str(c["target"]).lower())
    for lk in gate_links():
        t = norm_target(lk)
        if t and str(t).lower() not in seen:
            out.append({"id": "g" + hashlib.md5(str(lk).encode()).hexdigest()[:6], "title": str(t),
                        "target": t, "src": "gate"})
            seen.add(str(t).lower())
    return out


def bot_call(method, payload=None, files=None):
    if not BOT_TOKEN:
        return {"ok": False, "description": "BOT_TOKEN تنظیم نشده"}
    try:
        if files:
            r = SESSION.post(BASE_URL + "/" + method, data=payload, files=files, timeout=45)
        else:
            r = SESSION.post(BASE_URL + "/" + method, json=payload, timeout=20)
        return r.json()
    except Exception as e:
        return {"ok": False, "description": str(e)[:200]}


def _send_to(target, text, photo, btn_text, btn_url):
    markup = {"inline_keyboard": [[{"text": btn_text, "url": btn_url}]]} if (btn_text and btn_url) else None
    if photo:
        payload = {"chat_id": str(target), "parse_mode": "HTML"}
        if text:
            payload["caption"] = text
        if markup:
            payload["reply_markup"] = json.dumps(markup)
        return bot_call("sendPhoto", payload, files={"photo": photo})
    payload = {"chat_id": target, "text": text, "parse_mode": "HTML"}
    if markup:
        payload["reply_markup"] = markup
    return bot_call("sendMessage", payload)


@app.route("/channels")
@login_required
def channels_page():
    chans = channel_list()
    log = _load_json_setting(PANEL_POST_LOG_KEY, [])

    boxes = "".join(
        f'<label class="flex" style="cursor:pointer;margin:6px 0;"><input type="checkbox" name="t" value="{esc(c["id"])}">'
        f'<span>{esc(c["title"])} <small class="muted" dir="ltr">{esc(c["target"])}</small></span></label>'
        for c in chans) or '<p class="empty-note">کانالی ثبت نشده؛ پایین یکی اضافه کنید یا آدرس دلخواه بنویسید.</p>'

    manage = ""
    for c in chans:
        if c["src"] == "panel":
            manage += (f'<div class="switch-row"><div><b>{esc(c["title"])}</b> <small class="muted" dir="ltr">{esc(c["target"])}</small></div>'
                       f'<form method="post" action="{url_for("channel_delete", cid=c["id"])}" onsubmit="return confirm(\'حذف از لیست؟\');">'
                       f'<button type="submit" class="danger sm">حذف</button></form></div>')
        else:
            manage += (f'<div class="switch-row"><div><b>{esc(c["title"])}</b> <small class="muted">(از لیست عضویت اجباری)</small></div></div>')

    log_html = ""
    for i in range(len(log) - 1, -1, -1):
        e = log[i]
        log_html += (f'<tr><td data-label="کانال" dir="ltr">{esc(e.get("title"))}</td>'
                     f'<td data-label="نوع">{"🖼 عکس" if e.get("kind") == "photo" else "💬 متن"}</td>'
                     f'<td data-label="متن" class="wrap">{esc(e.get("preview"))}</td>'
                     f'<td data-label="زمان"><small class="muted">{fmt_dt(e.get("ts"))}</small></td>'
                     f'<td data-label=""><form method="post" action="{url_for("channel_log_delete", idx=i)}" '
                     f'onsubmit="return confirm(\'پیام از کانال هم پاک بشه؟\');"><button type="submit" class="danger sm">حذف از کانال</button></form></td></tr>')

    gate_rows = ""
    for lk in gate_links():
        h = hashlib.md5(lk.encode()).hexdigest()[:8]
        gate_rows += (f'<div class="switch-row"><div dir="ltr">{esc(lk)}</div>'
                      f'<form method="post" action="{url_for("gate_delete", h=h)}" onsubmit="return confirm(\'از عضویت اجباری حذف بشه؟\');">'
                      f'<button type="submit" class="danger sm">حذف</button></form></div>')
    if not gate_rows:
        gate_rows = '<p class="empty-note">عضویت اجباری کانالی ندارد.</p>'

    content = f"""
    {'' if BOT_TOKEN else '<div class="alert">⚠️ BOT_TOKEN تنظیم نشده؛ ارسال پیام کار نمی‌کنه.</div>'}
    <div class="card">
      <h3>✍️ ارسال پست در کانال‌ها</h3>
      <small class="muted">ربات باید تو کانال ادمین (با اجازه‌ی ارسال پیام) باشه. HTML تلگرام مجازه: &lt;b&gt; &lt;i&gt; &lt;code&gt; &lt;a href&gt;</small>
      <form method="post" action="{url_for('channels_post')}" enctype="multipart/form-data">
        <label>کانال‌ها</label>{boxes}
        <label for="extra">یا آدرس دلخواه (@یوزرنیم، لینک عمومی یا آیدی عددی)</label>
        <input id="extra" name="extra" dir="ltr" placeholder="@mychannel">
        <label for="ptext">متن پست</label>
        <textarea id="ptext" name="text" placeholder="متن (برای عکس تا ۱۰۲۴ کاراکتر)"></textarea>
        <label for="pphoto">عکس (اختیاری، حداکثر ۱۰ مگابایت)</label>
        <input id="pphoto" type="file" name="photo" accept="image/*">
        <div class="grid cols-2">
          <div><label for="btext">متن دکمه‌ی لینک‌دار (اختیاری)</label><input id="btext" name="btn_text" maxlength="40"></div>
          <div><label for="burl">لینک دکمه</label><input id="burl" name="btn_url" dir="ltr" placeholder="https://..."></div>
        </div>
        <div style="margin-top:14px;"><button type="submit" onclick="return confirm('پست ارسال بشه؟');">📤 ارسال</button></div>
      </form>
    </div>

    <div class="card"><h3>📺 کانال‌های ذخیره‌شده</h3>{manage if manage else '<p class="empty-note">—</p>'}
      <form method="post" action="{url_for('channel_add')}" class="flex" style="margin-top:12px;">
        <input name="title" placeholder="اسم نمایشی (اختیاری)" style="width:180px;">
        <input name="target" dir="ltr" placeholder="@mychannel یا لینک" style="flex:1;min-width:180px;" required>
        <button type="submit">➕ افزودن</button>
      </form></div>

    <h3>📜 آخرین پست‌های ارسال‌شده از پنل</h3>
    <table class="rt"><thead><tr><th>کانال</th><th>نوع</th><th>متن</th><th>زمان</th><th></th></tr></thead>
      <tbody>{log_html if log_html else '<tr><td colspan="5">هنوز پستی از پنل ارسال نشده.</td></tr>'}</tbody></table>

    <div class="card"><h3>🔒 کانال‌های عضویت اجباری</h3>
      {gate_rows}
      <form method="post" action="{url_for('gate_add')}" class="flex" style="margin-top:12px;">
        <input name="link" dir="ltr" placeholder="https://splus.ir/mychannel" style="flex:1;min-width:200px;" required>
        <button type="submit">➕ افزودن</button></form>
      <p class="muted" style="margin:8px 0 0;"><small>ربات این لیست رو فقط موقع روشن‌شدن می‌خونه؛ بعد از هر تغییر ربات رو ری‌استارت کنید. اکانت گیت باید تو کانال جدید ادمین باشه، وگرنه عضویت‌ها درست چک نمی‌شن. لاگین اکانت گیت (کد تأیید) فقط داخل خود ربات ممکنه.</small></p>
    </div>"""
    return render_page("کانال‌ها و پست‌گذاری", "channels", content)


@app.route("/channels/add", methods=["POST"])
@login_required
def channel_add():
    t = norm_target(request.form.get("target"))
    if t is None:
        flash("⚠️ آدرس کانال نامعتبره (لینک دعوت خصوصی پشتیبانی نمی‌شه).")
        return redirect(url_for("channels_page"))
    lst = _load_json_setting(PANEL_CH_KEY, [])
    if any(str(c.get("target")).lower() == str(t).lower() for c in lst if isinstance(c, dict)):
        flash("⚠️ این کانال از قبل تو لیسته.")
    else:
        lst.append({"id": secrets.token_hex(3), "title": (request.form.get("title") or "").strip()[:40] or str(t), "target": t})
        set_setting(PANEL_CH_KEY, json.dumps(lst, ensure_ascii=False))
        flash("کانال اضافه شد.")
    return redirect(url_for("channels_page"))


@app.route("/channels/<cid>/delete", methods=["POST"])
@login_required
def channel_delete(cid):
    lst = [c for c in _load_json_setting(PANEL_CH_KEY, []) if not (isinstance(c, dict) and str(c.get("id")) == cid)]
    set_setting(PANEL_CH_KEY, json.dumps(lst, ensure_ascii=False))
    flash("کانال از لیست حذف شد.")
    return redirect(url_for("channels_page"))


@app.route("/channels/post", methods=["POST"])
@login_required
def channels_post():
    text = request.form.get("text", "").strip()
    btn_text, btn_url = request.form.get("btn_text", "").strip(), request.form.get("btn_url", "").strip()
    back = redirect(url_for("channels_page"))
    f = request.files.get("photo")
    photo = None
    if f and f.filename:
        data = f.read()
        if not (f.mimetype or "").startswith("image/") or len(data) > 10 * 1024 * 1024 or not data:
            flash("⚠️ فایل باید عکس و حداکثر ۱۰ مگابایت باشه.")
            return back
        photo = (f.filename, data, f.mimetype)
    if not text and not photo:
        flash("⚠️ متن یا عکس لازمه.")
        return back
    if len(text) > (1024 if photo else 4096):
        flash("⚠️ متن بلنده (برای عکس حداکثر ۱۰۲۴، برای متن ۴۰۹۶ کاراکتر).")
        return back
    if bool(btn_text) != bool(btn_url) or (btn_url and not re.match(r"^https?://\S+$", btn_url)):
        flash("⚠️ برای دکمه، هم متن و هم لینک (با http/https) لازمه.")
        return back
    chans = {c["id"]: c for c in channel_list()}
    targets = [(chans[i]["title"], chans[i]["target"]) for i in request.form.getlist("t") if i in chans]
    extra_raw = request.form.get("extra", "").strip()
    if extra_raw:
        et = norm_target(extra_raw)
        if et is None:
            flash("⚠️ آدرس دلخواه نامعتبره.")
            return back
        if all(str(et).lower() != str(t[1]).lower() for t in targets):
            targets.append((str(et), et))
    if not targets:
        flash("⚠️ حداقل یک کانال انتخاب کنید.")
        return back
    log = _load_json_setting(PANEL_POST_LOG_KEY, [])
    ok_n, errs = 0, []
    for title, target in targets:
        res = _send_to(target, text, photo, btn_text, btn_url)
        if res.get("ok"):
            ok_n += 1
            log.append({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "title": title, "target": target,
                        "message_id": (res.get("result") or {}).get("message_id"),
                        "kind": "photo" if photo else "text", "preview": (text or "[عکس]")[:80]})
        else:
            errs.append(f"{title}: {str(res.get('description') or 'خطا')[:120]}")
    set_setting(PANEL_POST_LOG_KEY, json.dumps(log[-40:], ensure_ascii=False))
    if ok_n:
        flash(f"پست در {ok_n} کانال ارسال شد.")
    for e in errs[:6]:
        flash("⚠️ ارسال نشد — " + e)
    return back


@app.route("/channels/log/<int:idx>/delete", methods=["POST"])
@login_required
def channel_log_delete(idx):
    log = _load_json_setting(PANEL_POST_LOG_KEY, [])
    if not (0 <= idx < len(log)):
        flash("⚠️ مورد پیدا نشد.")
        return redirect(url_for("channels_page"))
    e = log[idx]
    res = bot_call("deleteMessage", {"chat_id": e.get("target"), "message_id": e.get("message_id")})
    if res.get("ok"):
        log.pop(idx)
        set_setting(PANEL_POST_LOG_KEY, json.dumps(log, ensure_ascii=False))
        flash("پیام از کانال حذف شد.")
    else:
        flash("⚠️ حذف نشد: " + str(res.get("description") or "خطا")[:150])
    return redirect(url_for("channels_page"))


@app.route("/channels/gate/add", methods=["POST"])
@login_required
def gate_add():
    t = norm_target(request.form.get("link"))
    if not t or isinstance(t, int):
        flash("⚠️ فقط لینک/یوزرنیم عمومی کانال مجازه.")
        return redirect(url_for("channels_page"))
    link = "https://splus.ir/" + t[1:]
    links = gate_links()
    if any(norm_target(x) == t for x in links):
        flash("⚠️ این کانال از قبل تو لیسته.")
    else:
        set_setting("gate_channels", json.dumps(links + [link], ensure_ascii=False))
        flash("به لیست عضویت اجباری اضافه شد؛ ربات رو ری‌استارت کنید.")
    return redirect(url_for("channels_page"))


@app.route("/channels/gate/<h>/delete", methods=["POST"])
@login_required
def gate_delete(h):
    links = gate_links()
    new = [x for x in links if hashlib.md5(x.encode()).hexdigest()[:8] != h]
    set_setting("gate_channels", json.dumps(new, ensure_ascii=False))
    flash("از عضویت اجباری حذف شد؛ ربات رو ری‌استارت کنید.")
    return redirect(url_for("channels_page"))


# ---------- مدیریت کانفیگ‌های یک کاربر ----------

PROTO_TO_TYPE = {"xray": "config", "wireguard": "wireguard", "both": "both", "openvpn": "openvpn", "dns": "dns"}


def cfg_call(method, suffix, config_id, body=None):
    if not CONFIG_KEY:
        return {"success": False, "error": "CONFIG_KEY تو Environment پنل تنظیم نشده"}
    try:
        res = SESSION.request(method, CONFIG_API + "/" + str(config_id) + suffix,
                              headers={"Authorization": "Bearer " + CONFIG_KEY}, json=body, timeout=20)
        try:
            data = res.json()
        except Exception:
            data = {}
        if res.status_code in (200, 201, 204):
            return {"success": True, "data": data if isinstance(data, dict) else {}}
        return {"success": False, "error": (res.text or str(res.status_code))[:200]}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


def cfg_usage_gb(config_id):
    if not config_id:
        return None
    r = cfg_call("GET", "", config_id)
    if not r["success"]:
        return None
    d = r["data"]
    if isinstance(d.get("configs"), list) and d["configs"]:
        d = d["configs"][0]
    try:
        return float(d["usedGb"]) if d.get("usedGb") is not None else None
    except (TypeError, ValueError):
        return None


@with_db_retry
def db_run(sql, params=()):
    conn = get_conn()
    c = conn.cursor()
    c.execute(sql, params)
    conn.commit()
    rid = c.lastrowid
    conn.close()
    return rid


@with_db_retry
def db_rows(sql, params=()):
    conn = get_conn()
    c = conn.cursor()
    c.execute(sql, params)
    rows = c.fetchall()
    conn.close()
    return rows


_CFG_COLS = "id, sub_url, config_id, gb, label, days, price, type, status, created_at, expires_at"


def get_cfg_row(user_id, rid):
    rows = db_rows(f"SELECT {_CFG_COLS} FROM user_configs WHERE user_id=? AND id=?", (user_id, rid))
    return rows[0] if rows else None


def _notify(user_id, text):
    return send_telegram_message(user_id, text)


@app.route("/users/<int:user_id>/configs")
@login_required
def user_configs_admin(user_id):
    u = get_user(user_id)
    if not u:
        flash("⚠️ کاربر پیدا نشد.")
        return redirect(url_for("users"))
    rows = db_rows(f"SELECT {_CFG_COLS} FROM user_configs WHERE user_id=? ORDER BY id DESC LIMIT 60", (user_id,))
    with ThreadPoolExecutor(max_workers=8) as ex:
        usage = list(ex.map(lambda r: cfg_usage_gb(r[2]), rows)) if (rows and CONFIG_KEY) else [None] * len(rows)
    cards = ""
    for r, used in zip(rows, usage):
        rid, sub_url, config_id, gb, label, days, price, ctype, status, created_at, expires_at = r
        exp = parse_ts(expires_at)
        left = max(0, (exp - datetime.now(timezone.utc)).days) if exp else 0
        paused = (status or "active") == "paused"
        state = "متوقف" if paused else ("منقضی" if left <= 0 else "فعال")
        used_txt = f"{used:.2f} گیگ" if used is not None else "نامشخص"
        base = url_for("user_config_action", user_id=user_id, rid=rid, action="x")[:-1]
        cards += f"""
        <div class="card">
          <h3>{esc(label)} <span class="badge {'off' if paused or left <= 0 else 'on'}">{state}</span></h3>
          <div class="kv">
            <div><span>نوع</span><b>{esc(ctype or '-')}</b></div>
            <div><span>حجم کل</span><b class="num">{float(gb or 0):g} گیگ</b></div>
            <div><span>مصرف</span><b class="num">{used_txt}</b></div>
            <div><span>روز باقی‌مانده</span><b class="num">{left}</b></div>
            <div><span>پرداختی</span><b class="num">{int(price or 0):,}</b></div>
            <div><span>ساخت</span><b>{fmt_dt(created_at, with_time=False)}</b></div>
            <div style="grid-column:1/-1;"><span>لینک</span>{copy_widget(sub_url or '')}</div>
          </div>
          <div class="grid cols-2" style="margin-top:12px;">
            <form method="post" action="{base}extend" class="flex">
              <input type="text" name="gb" inputmode="decimal" placeholder="گیگ +" style="width:90px;">
              <input type="number" name="days" min="0" placeholder="روز +" style="width:90px;">
              <label class="flex" style="margin:0;"><input type="checkbox" name="notify" value="1"> اطلاع به کاربر</label>
              <button type="submit" class="sm">➕ تمدید</button></form>
            <form method="post" action="{base}rename" class="flex">
              <input type="text" name="label" placeholder="نام جدید" style="flex:1;min-width:120px;" required>
              <button type="submit" class="secondary sm">✏️ تغییر نام</button></form>
          </div>
          <div class="flex" style="margin-top:10px;">
            <form method="post" action="{base}{'resume' if paused else 'pause'}"><button type="submit" class="secondary sm">{'▶️ ازسرگیری' if paused else '⏸ توقف'}</button></form>
            <form method="post" action="{base}rotate" onsubmit="return confirm('لینک عوض بشه؟ لینک قبلی از کار می‌افته.');">
              <input type="hidden" name="notify" value="1"><button type="submit" class="secondary sm">🔄 تغییر لینک + ارسال به کاربر</button></form>
            <form method="post" action="{base}delete" class="flex" onsubmit="return confirm('کانفیگ حذف بشه؟ غیرقابل بازگشته.');">
              <input type="number" name="refund" min="0" placeholder="بازگشت وجه (تومان)" style="width:150px;">
              <label class="flex" style="margin:0;"><input type="checkbox" name="force" value="1"> حتی با خطای پنل از دیتابیس پاک شه</label>
              <button type="submit" class="danger sm">🗑 حذف</button></form>
          </div>
        </div>"""
    if not cards:
        cards = '<div class="card"><p class="empty-note">این کاربر کانفیگی ندارد.</p></div>'
    warn = "" if CONFIG_KEY else '<div class="alert">⚠️ متغیر CONFIG_KEY تو Environment پنل ست نشده؛ عملیات روی پنل اصلی (تمدید، توقف، حذف، ساخت) کار نمی‌کنه.</div>'
    content = f"""
    <p><a class="btn secondary sm" href="{url_for('user_detail', user_id=user_id)}">‹ بازگشت به کاربر</a></p>
    {warn}
    <div class="card"><h3>🎁 ساخت کانفیگ هدیه / دستی برای {user_display(u[2], u[1], user_id)}</h3>
      <form method="post" action="{url_for('user_config_create', user_id=user_id)}" class="flex">
        <input type="text" name="gb" inputmode="decimal" placeholder="حجم (گیگ)" style="width:110px;" required>
        <input type="number" name="days" min="1" placeholder="روز" style="width:90px;" required>
        <input type="text" name="label" placeholder="نام (اختیاری)" style="width:150px;">
        <select name="proto" style="width:150px;">
          <option value="both">هر دو</option><option value="xray">فقط کانفیگ</option><option value="wireguard">وایرگارد</option>
          <option value="openvpn">OpenVPN</option><option value="dns">DNS بازی</option></select>
        <label class="flex" style="margin:0;"><input type="checkbox" name="notify" value="1" checked> لینک برای کاربر ارسال بشه</label>
        <button type="submit">ساخت</button></form>
      <small class="muted">این عملیات از موجودی کاربر کم نمی‌کنه و قیمتش صفر ثبت می‌شه.</small></div>
    {cards}
    <p><small class="muted">تغییرات این صفحه مستقیم روی پنل اصلی و دیتابیس ربات اعمال می‌شه و از کیف پول کاربر چیزی کم نمی‌شه.</small></p>"""
    return render_page(f"کانفیگ‌های کاربر {user_id}", "users", content)


@app.route("/users/<int:user_id>/configs/create", methods=["POST"])
@login_required
def user_config_create(user_id):
    back = redirect(url_for("user_configs_admin", user_id=user_id))
    gb, days = parse_gb_delta(request.form.get("gb")), to_int(request.form.get("days"))
    proto = request.form.get("proto", "both")
    if gb is None or gb <= 0 or gb > 100000 or not days or not (1 <= days <= 3650) or proto not in PROTO_TO_TYPE:
        flash("⚠️ حجم، روز یا نوع نامعتبره.")
        return back
    if not CONFIG_KEY:
        flash("⚠️ CONFIG_KEY تنظیم نشده.")
        return back
    label = clean = re.sub(r"[<>&]", "", request.form.get("label", "")).strip()[:40] or "GIFT-" + secrets.token_hex(3).upper()
    try:
        res = SESSION.post(CONFIG_API, headers={"Authorization": "Bearer " + CONFIG_KEY},
                           json={"gb": gb, "label": label, "expiryDays": days, "proto": proto}, timeout=25)
        data = res.json() if res.status_code in (200, 201) else {}
    except Exception as e:
        flash("⚠️ ساخت ناموفق: " + str(e)[:120])
        return back
    sub_url = data.get("subUrl")
    if not sub_url:
        flash(f"⚠️ پنل کانفیگ نساخت (کد {res.status_code}): {res.text[:120]}")
        return back
    cid = data.get("id") or data.get("uuid") or data.get("username")
    now = datetime.now()
    db_run("INSERT INTO user_configs (user_id, sub_url, config_id, gb, label, days, price, type, status, created_at, expires_at) "
           "VALUES (?, ?, ?, ?, ?, ?, 0, ?, 'active', ?, ?)",
           (user_id, sub_url, cid, gb, label, days, PROTO_TO_TYPE[proto], now.isoformat(), (now + timedelta(days=days)).isoformat()))
    cfg_call("PUT", "/note", cid, {"note": "ساخته‌شده از پنل وب (هدیه/دستی)"})
    flash(f"کانفیگ «{label}» ساخته شد.")
    if request.form.get("notify") == "1":
        sent = _notify(user_id, f"🎁 <b>یک کانفیگ برای شما ساخته شد</b>\n📶 {gb:g} گیگ — ⏳ {days} روز\n🔗 <code>{esc(sub_url)}</code>")
        flash("لینک برای کاربر ارسال شد." if sent else "⚠️ ارسال پیام به کاربر ناموفق بود.")
    return back


@app.route("/users/<int:user_id>/configs/<int:rid>/<action>", methods=["POST"])
@login_required
def user_config_action(user_id, rid, action):
    back = redirect(url_for("user_configs_admin", user_id=user_id))
    row = get_cfg_row(user_id, rid)
    if not row:
        flash("⚠️ کانفیگ پیدا نشد.")
        return back
    _id, sub_url, config_id, gb, label, days, price, ctype, status, created_at, expires_at = row
    notify = request.form.get("notify") == "1"

    if action == "extend":
        egb = parse_gb_delta(request.form.get("gb")) or 0
        edays = to_int(request.form.get("days"), 0) or 0
        if egb < 0 or edays < 0 or (egb == 0 and edays == 0) or egb > 100000 or edays > 3650:
            flash("⚠️ حجم/روز نامعتبره (هر دو نمی‌تونن صفر باشن).")
            return back
        r = cfg_call("POST", "/extend", config_id, {"gb": egb, "days": edays})
        if not r["success"]:
            flash("⚠️ تمدید روی پنل ناموفق: " + r["error"])
            return back
        base = parse_ts(expires_at)
        base = base.replace(tzinfo=None) if base else datetime.now()
        base = max(base, datetime.now())
        db_run("UPDATE user_configs SET base_gb=COALESCE(base_gb, ?), base_days=COALESCE(base_days, ?), "
               "gb=?, days=?, expires_at=? WHERE id=?",
               (gb or 0, days or 0, (gb or 0) + egb, (days or 0) + edays, (base + timedelta(days=edays)).isoformat(), rid))
        flash(f"تمدید شد: +{egb:g} گیگ، +{edays} روز.")
        if notify:
            _notify(user_id, f"✅ کانفیگ «{esc(label)}» تمدید شد: +{egb:g} گیگ، +{edays} روز.")
    elif action == "rename":
        new = re.sub(r"[<>&]", "", request.form.get("label", "")).strip()[:40]
        if not new:
            flash("⚠️ نام خالیه.")
            return back
        r = cfg_call("PUT", "/label", config_id, {"label": new})
        if not r["success"]:
            flash("⚠️ تغییر نام روی پنل ناموفق: " + r["error"])
            return back
        db_run("UPDATE user_configs SET label=? WHERE id=?", (new, rid))
        flash("نام تغییر کرد (برای اعمال تو لینک، «تغییر لینک» رو هم بزنید).")
    elif action in ("pause", "resume"):
        r = cfg_call("POST", "/" + action, config_id)
        if not r["success"]:
            flash("⚠️ عملیات روی پنل ناموفق: " + r["error"])
            return back
        db_run("UPDATE user_configs SET status=? WHERE id=?", ("paused" if action == "pause" else "active", rid))
        flash("کانفیگ متوقف شد." if action == "pause" else "کانفیگ ازسرگرفته شد.")
    elif action == "rotate":
        r = cfg_call("POST", "/rotate-link", config_id)
        if not r["success"]:
            flash("⚠️ تغییر لینک ناموفق: " + r["error"])
            return back
        d = r["data"]
        new_url = d.get("sub_url") or d.get("subUrl") or d.get("url")
        if new_url:
            db_run("UPDATE user_configs SET sub_url=? WHERE id=?", (new_url, rid))
            flash("لینک تغییر کرد.")
            if notify:
                _notify(user_id, f"🔄 لینک کانفیگ «{esc(label)}» تغییر کرد:\n<code>{esc(new_url)}</code>")
        else:
            flash("لینک تغییر کرد ولی پنل لینک جدید رو برنگردوند.")
    elif action == "delete":
        r = cfg_call("DELETE", "", config_id)
        if not r["success"] and request.form.get("force") != "1":
            flash("⚠️ حذف روی پنل ناموفق: " + r["error"] + " (برای حذف فقط از دیتابیس، گزینه‌ی اجباری رو تیک بزنید)")
            return back
        db_run("DELETE FROM user_configs WHERE id=?", (rid,))
        refund = to_int(request.form.get("refund"), 0) or 0
        if refund > 0:
            update_wallet(user_id, refund)
        flash("کانفیگ حذف شد" + (f" و {refund:,} تومان به کیف پول برگشت." if refund > 0 else "."))
        if not r["success"]:
            flash("⚠️ توجه: روی پنل اصلی حذف نشد: " + r["error"])
    else:
        abort(404)
    return back


# ---------- سفارش‌ها ----------

@app.route("/orders")
@login_required
def orders_page():
    q = to_int(request.args.get("q"))
    offset = max(0, to_int(request.args.get("offset"), 0))
    where, params = ("WHERE user_id=?", [q]) if q else ("", [])
    rows = db_rows(f"SELECT id, user_id, label, gb, days, price, type, created_at FROM orders {where} "
                   "ORDER BY id DESC LIMIT 30 OFFSET ?", params + [offset])
    tot = (db_rows(f"SELECT COUNT(*), COALESCE(SUM(price),0), COALESCE(SUM(gb),0) FROM orders {where}", params) or [(0, 0, 0)])[0]
    body = "".join(
        f'<tr><td data-label="#">{r[0]}</td><td data-label="کاربر"><a class="num" href="{url_for("user_detail", user_id=r[1])}">{r[1]}</a></td>'
        f'<td data-label="نام">{esc(r[2])}</td><td data-label="نوع">{esc(r[6])}</td>'
        f'<td data-label="حجم" class="num">{float(r[3] or 0):g}</td><td data-label="روز" class="num">{r[4]}</td>'
        f'<td data-label="مبلغ" class="num">{int(r[5] or 0):,}</td><td data-label="زمان"><small class="muted">{fmt_dt(r[7])}</small></td></tr>'
        for r in rows)
    pager = ""
    if offset > 0:
        pager += f'<a class="btn secondary" href="{url_for("orders_page", q=q or "", offset=max(0, offset - 30))}">‹ قبل</a>'
    if offset + 30 < tot[0]:
        pager += f'<a class="btn secondary" href="{url_for("orders_page", q=q or "", offset=offset + 30)}">بعد ›</a>'
    content = f"""
    <div class="stats">
      <div class="stat"><span>تعداد سفارش</span><b class="num">{tot[0]:,}</b></div>
      <div class="stat"><span>مجموع فروش</span><b class="num">{int(tot[1]):,}</b><small>تومان</small></div>
      <div class="stat"><span>مجموع حجم</span><b class="num">{float(tot[2]):,.1f}</b><small>گیگ</small></div>
    </div>
    <div class="card"><form method="get" class="flex">
      <input type="number" name="q" value="{q or ''}" placeholder="فیلتر با آیدی عددی کاربر" style="flex:1;min-width:200px;">
      <button type="submit">فیلتر</button></form></div>
    <table class="rt"><thead><tr><th>#</th><th>کاربر</th><th>نام</th><th>نوع</th><th>حجم</th><th>روز</th><th>مبلغ</th><th>زمان</th></tr></thead>
      <tbody>{body if body else '<tr><td colspan="8">سفارشی نیست.</td></tr>'}</tbody></table>
    <div class="pager">{pager}</div>"""
    return render_page("سفارش‌ها", "orders", content)


# ---------- بکاپ و خروجی ----------

EXPORT_TABLES = {
    "users": "user_id, username, first_name, wallet, joined_at, last_active, lang",
    "orders": "id, user_id, label, gb, days, price, type, config_id, created_at",
    "user_configs": "id, user_id, sub_url, config_id, gb, label, days, price, type, status, created_at, expires_at",
    "topup_requests": "id, user_id, amount, status, created_at, method, coin_symbol, coin_qty, tx_hash",
    "tickets": "id, user_id, message, status, admin_reply, created_at",
    "discount_codes": "code, percent, max_uses, used_count, active, created_at",
    "referral_rewards": "invitee_id, inviter_id, inviter_amount, invitee_amount, created_at",
}
TABLE_TITLES = {"users": "کاربران", "orders": "سفارش‌ها", "user_configs": "کانفیگ‌ها", "topup_requests": "شارژها",
                "tickets": "تیکت‌ها", "discount_codes": "کدهای تخفیف", "referral_rewards": "پاداش‌های دعوت"}


def _csv_cell(v):
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s


@app.route("/backup")
@login_required
def backup_page():
    links = "".join(f'<a class="btn secondary" href="{url_for("export_csv", name=n)}">⬇️ {TABLE_TITLES[n]} (CSV)</a> ' for n in EXPORT_TABLES)
    content = f"""
    <div class="card"><h3>⬇️ خروجی جدول‌ها</h3><div class="flex">{links}</div></div>
    <div class="card"><h3>💾 بکاپ کامل</h3>
      <div class="flex"><a class="btn" href="{url_for('export_all')}">همه‌ی جدول‌ها (JSON)</a>
        <a class="btn secondary" href="{url_for('export_settings')}">تنظیمات و متن‌ها (JSON)</a></div>
      <small class="muted">فایل‌ها شامل اطلاعات کاربران‌اند؛ جای امن نگه دارید. جدول فروشنده‌ها و رمزها عمداً تو خروجی نیست.</small></div>
    <div class="card"><h3>♻️ بازگردانی تنظیمات</h3>
      <form method="post" action="{url_for('restore_settings')}" enctype="multipart/form-data" onsubmit="return confirm('تنظیمات فعلی با فایل جایگزین/ادغام بشه؟');">
        <input type="file" name="file" accept=".json,application/json" required>
        <div style="margin-top:10px;"><button type="submit" class="danger">بازگردانی از فایل</button></div></form>
      <small class="muted">فقط فایل «تنظیمات» که از همین صفحه گرفتید. کلیدهای موجود بازنویسی می‌شن.</small></div>"""
    return render_page("بکاپ و خروجی", "backup", content)


def _dl(name, data, mime):
    return Response(data, mimetype=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.route("/export/<name>.csv")
@login_required
def export_csv(name):
    if name not in EXPORT_TABLES:
        abort(404)
    try:
        rows = db_rows(f"SELECT {EXPORT_TABLES[name]} FROM {name}")
    except Exception as e:
        flash("⚠️ خروجی ناموفق: " + str(e)[:120])
        return redirect(url_for("backup_page"))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c.strip() for c in EXPORT_TABLES[name].split(",")])
    for r in rows:
        w.writerow([_csv_cell(v) for v in r])
    return _dl(f"{name}.csv", "\ufeff" + buf.getvalue(), "text/csv; charset=utf-8")


@app.route("/export/all.json")
@login_required
def export_all():
    out = {"exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tables": {}}
    for n, cols in EXPORT_TABLES.items():
        try:
            out["tables"][n] = {"columns": [c.strip() for c in cols.split(",")],
                                "rows": [list(r) for r in db_rows(f"SELECT {cols} FROM {n}")]}
        except Exception as e:
            out["tables"][n] = {"error": str(e)[:120]}
    return _dl("skytunnel-backup.json", json.dumps(out, ensure_ascii=False), "application/json")


@app.route("/export/settings.json")
@login_required
def export_settings():
    safe = {k: v for k, v in get_all_settings().items() if not _is_secret_setting(k)}
    return _dl("skytunnel-settings.json", json.dumps(safe, ensure_ascii=False, indent=1), "application/json")


def _is_secret_setting(k):
    return k.startswith("env_") or k == "donito_token"


@app.route("/backup/restore", methods=["POST"])
@login_required
def restore_settings():
    f = request.files.get("file")
    try:
        data = json.loads(f.read().decode("utf-8")) if f else None
    except Exception:
        data = None
    if (not isinstance(data, dict) or not data or len(data) > 3000
            or not all(isinstance(k, str) and isinstance(v, str) and len(k) <= 100 and len(v) <= 20000 for k, v in data.items())):
        flash("⚠️ فایل معتبر نیست (باید خروجی «تنظیمات» همین پنل باشه).")
        return redirect(url_for("backup_page"))
    for k, v in data.items():
        set_setting(k, v)
    flash(f"{len(data)} تنظیم بازگردانی شد.")
    return redirect(url_for("backup_page"))



# ---------------------------------------------------------------------------
# 💎 مرکز مالی + ⚡️ مانیتور دونیتو
# ---------------------------------------------------------------------------
DONITO_API_BASE = os.getenv("DONITO_API_BASE", "https://donito.me/api/v1/thirdparty").rstrip("/")
DONITO_DEFAULT_TOKEN = "BKEXR_KnkwEh1jEHov5oDOPvxAVfps1MwXHBpc"

ICONS["finance"] = '<path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 5-6"/>'
ICONS["donito"] = '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>'
NAV[2][1].append(("finance", "مرکز مالی", "finance_page"))
NAV[2][1].append(("donito", "مانیتور دونیتو", "donito_page"))
NAV[2][1].append(("plans", "بسته‌های آماده", "plans_page"))
NAV[2][1].append(("alerts", "هشدار انقضا و حجم", "alerts_page"))
NAV[3][1].append(("envvars", "متغیرهای محیطی", "env_page"))
ICONS["plans"] = '<path d="M21 8l-9-5-9 5 9 5 9-5z"/><path d="M3 8v8l9 5 9-5V8"/>'
ICONS["alerts"] = '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>'
ICONS["envvars"] = '<path d="M4 6h16M4 12h16M4 18h10"/><circle cx="18" cy="18" r="2"/>'

METHOD_LABELS = {"card": "💳 کارت‌به‌کارت", "crypto": "🪙 رمزارز", "donito": "⚡️ دونیتو", "donito_manual": "🧾 دونیتو (دستی)"}
STATUS_LABELS = {"pending": "در انتظار", "approved": "تایید شده", "rejected": "رد شده", "expired": "منقضی شده"}


def donito_token():
    return (get_setting("donito_token", "") or os.getenv("DONITO_TOKEN", "") or DONITO_DEFAULT_TOKEN).strip()


def donito_masked():
    t = donito_token()
    return (t[:6] + "••••••" + t[-3:]) if len(t) > 12 else "—"


def donito_scrub(text):
    t = str(text)
    tok = donito_token()
    return t.replace(tok, "***") if tok else t


def donito_fetch_recent():
    """۵۰ دونیت آخر از API دونیتو → لیست dict (id, amount تومان, currency, created_at, ts). خطا: RuntimeError بدون توکن."""
    try:
        r = requests.get(f"{DONITO_API_BASE}/{donito_token()}/donations/recent", timeout=12,
                         headers={"Accept": "application/json"})
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        raise RuntimeError(donito_scrub(e)) from None
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise RuntimeError("پاسخ نامعتبر: " + donito_scrub(str(data)[:160]))
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        cur = str(it.get("currency_type") or "IRT").strip().upper()
        try:
            amount = int(round(float(str(it.get("amount")).replace(",", "").strip())))
        except (TypeError, ValueError):
            continue
        if cur in ("IRR", "RIAL", "RLS"):
            amount //= 10
        out.append({"id": str(it.get("id") or ""), "amount": amount, "currency": cur,
                    "created_at": it.get("created_at"), "ts": parse_ts(it.get("created_at"))})
    out.sort(key=lambda d: d["ts"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return out


@with_db_retry
def fin_rows(days=30):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, user_id, amount, status, COALESCE(method, 'card'), created_at, matched_tx "
              "FROM topup_requests WHERE created_at >= ? ORDER BY id DESC", (cutoff,))
    rows = c.fetchall()
    conn.close()
    return rows


@with_db_retry
def donito_requests(status=None, limit=30):
    conn = get_conn()
    c = conn.cursor()
    sql = ("SELECT id, user_id, amount, status, created_at, req_ts, matched_tx FROM topup_requests "
           "WHERE method='donito'")
    args = []
    if status:
        sql += " AND status=?"
        args.append(status)
    c.execute(sql + " ORDER BY id DESC LIMIT ?", tuple(args) + (limit,))
    rows = c.fetchall()
    conn.close()
    return rows


def _day_label(d):
    jy, jm, jd = g2j(d.year, d.month, d.day)
    return fa(f"{jm:02d}/{jd:02d}")


PAGE_CSS_FIN = """
<style>
  .mrow { margin: 12px 0; }
  .mhead { display: flex; justify-content: space-between; gap: 8px; font-size: 13.5px; margin-bottom: 5px; }
  .mbar { height: 10px; border-radius: 999px; background: var(--surface-2); overflow: hidden; border: 1px solid var(--border); }
  .mbar i { display: block; height: 100%; background: var(--grad); border-radius: 999px; transition: width .6s; }
  .big-ok { color: var(--ok); } .big-warn { color: var(--warn); }
  .cd { font-variant-numeric: tabular-nums; font-weight: 700; }
  .cd.low { color: var(--danger); }
  .amt-copy { display: inline-flex; align-items: center; gap: 6px; }
  .live-dot { display:inline-block; width:9px; height:9px; border-radius:50%; background:#2fd48a; box-shadow:0 0 0 4px var(--ok-dim); animation: pulse 1.6s infinite; }
  @keyframes pulse { 50% { box-shadow: 0 0 0 7px transparent; } }
</style>
"""


@app.route("/finance")
@login_required
def finance_page():
    rows = fin_rows(30)
    today = datetime.now(TEHRAN).date()
    by_day = {today - timedelta(days=i): 0 for i in range(13, -1, -1)}
    tot = {"today": 0, "d7": 0, "d30": 0}
    cnt, by_method, top = {}, {}, {}
    dn = {"created": 0, "approved": 0, "expired": 0, "pending": 0, "rejected": 0}
    approved_n = 0
    for _rid, uid, amt, status, method, created, _mt in rows:
        dt = parse_ts(created)
        if not dt:
            continue
        d = dt.astimezone(TEHRAN).date()
        age = (today - d).days
        amt = int(amt or 0)
        cnt[status] = cnt.get(status, 0) + 1
        if status == "approved":
            approved_n += 1
            tot["d30"] += amt
            if age <= 6:
                tot["d7"] += amt
            if age == 0:
                tot["today"] += amt
            if d in by_day:
                by_day[d] += amt
            by_method[method] = by_method.get(method, 0) + amt
            top[uid] = top.get(uid, 0) + amt
        if method == "donito" and age <= 6:
            dn["created"] += 1
            dn[status] = dn.get(status, 0) + 1

    avg = tot["d30"] // approved_n if approved_n else 0
    settled = dn["created"] - dn["pending"]
    rate = f"{dn['approved'] * 100 // settled}٪" if settled > 0 else "—"
    chart = bar_chart([(_day_label(d), v) for d, v in by_day.items()], lambda v: f"{int(v):,} تومان")

    mtot = sum(by_method.values()) or 1
    methods_html = ""
    for m, v in sorted(by_method.items(), key=lambda kv: -kv[1]):
        pct = v * 100 // mtot
        methods_html += (f'<div class="mrow"><div class="mhead"><span>{METHOD_LABELS.get(m, esc(m))}</span>'
                         f'<b class="num">{v:,} تومان · {fa(str(pct))}٪</b></div>'
                         f'<div class="mbar"><i style="width:{pct}%"></i></div></div>')
    if not methods_html:
        methods_html = '<p class="empty-note">هنوز شارژ تاییدشده‌ای نیست.</p>'

    top_html = ""
    for uid, v in sorted(top.items(), key=lambda kv: -kv[1])[:6]:
        top_html += (f'<a class="row-link" href="{url_for("user_detail", user_id=uid)}">'
                     f'<span class="row-main"><b class="num">{uid}</b><small>شارژ ۳۰ روز اخیر</small></span>'
                     f'<b class="num">{v:,}</b></a>')
    if not top_html:
        top_html = '<p class="empty-note">—</p>'

    content = f"""{PAGE_CSS_FIN}
    <div class="stats">
      <div class="stat"><span>شارژ امروز</span><b class="num big-ok">{tot['today']:,}</b><small>تومان</small></div>
      <div class="stat"><span>۷ روز اخیر</span><b class="num">{tot['d7']:,}</b><small>تومان</small></div>
      <div class="stat"><span>۳۰ روز اخیر</span><b class="num">{tot['d30']:,}</b><small>تومان</small></div>
      <div class="stat"><span>میانگین هر شارژ</span><b class="num">{avg:,}</b><small>تومان · {approved_n:,} شارژ</small></div>
      <div class="stat"><span>در انتظار تایید</span><b class="num {'big-warn' if cnt.get('pending') else ''}">{cnt.get('pending', 0):,}</b>
        <small>{cnt.get('rejected', 0):,} رد · {cnt.get('expired', 0):,} منقضی</small></div>
      <div class="stat"><span>موفقیت دونیتو (۷ روز)</span><b class="num">{rate}</b>
        <small>{dn['approved']:,} از {settled:,} درخواست</small></div>
    </div>
    <div class="card"><h3>شارژ تاییدشده‌ی ۱۴ روز اخیر</h3>
      <small class="muted num">{sum(by_day.values()):,} تومان</small>{chart}</div>
    <div class="grid cols-2">
      <div class="card"><h3>سهم روش‌های پرداخت (۳۰ روز)</h3>{methods_html}</div>
      <div class="card"><h3>پرشارژترین کاربران (۳۰ روز)</h3>{top_html}</div>
    </div>
    <div class="flex" style="margin-top:6px;">
      <a class="btn secondary sm" href="{url_for('topups_page')}">📋 همه‌ی شارژها</a>
      <a class="btn secondary sm" href="{url_for('donito_page')}">⚡️ مانیتور دونیتو</a>
      <a class="btn secondary sm" href="{url_for('export_csv', name='topup_requests')}">⬇️ خروجی CSV شارژها</a>
    </div>"""
    return render_page("مرکز مالی", "finance", content)


@app.route("/donito")
@login_required
def donito_page():
    ensure_settings_table()
    enabled = get_setting("donito_enabled", "1") == "1"
    page_url = get_setting("donito_page_url", DEFAULT_DONITO_PAGE_URL) or DEFAULT_DONITO_PAGE_URL
    try:
        window = max(10, int(float(get_setting("donito_window_min", "180") or 180))) * 60
    except (TypeError, ValueError):
        window = 180 * 60
    live = request.args.get("live") == "1"
    now = time.time()

    hist = donito_requests(limit=200)
    pend = [r for r in hist if r[3] == "pending"]
    matched = {r[6]: (r[0], r[1]) for r in hist if r[6] and str(r[6]).startswith("donito:")}
    pend_amounts = {r[2]: r[0] for r in pend}

    # --- درخواست‌های در انتظار (شمارش معکوس) ---
    pend_html = ""
    for rid, uid, amt, _st, created, req_ts, _mt in pend:
        exp = (req_ts or now) + window
        pend_html += f"""
        <tr>
          <td data-label="شماره">#{rid}</td>
          <td data-label="کاربر"><a class="num" href="{url_for('user_detail', user_id=uid)}">{uid}</a></td>
          <td data-label="مبلغ دقیق"><span class="amt-copy"><b class="num">{int(amt):,}</b>
            <button type="button" class="sm secondary" onclick="cp('{int(amt)}', this)">📋</button></span></td>
          <td data-label="زمان باقی‌مانده"><span class="cd" data-exp="{exp:.0f}">…</span></td>
          <td data-label="عملیات">
            <form method="post" action="{url_for('topup_approve', req_id=rid)}" style="display:inline;"
                  onsubmit="return confirm('درخواست #{rid} دستی تایید بشه؟ (فقط اگه پرداخت رو تو دونیتو دیدی)');">
              <button type="submit" class="sm">✅ تایید دستی</button></form>
            <form method="post" action="{url_for('topup_reject', req_id=rid)}" style="display:inline;"
                  onsubmit="return confirm('رد بشه؟');"><button type="submit" class="danger sm">❌</button></form>
          </td>
        </tr>"""
    pend_block = (f'<table class="rt"><thead><tr><th>شماره</th><th>کاربر</th><th>مبلغ دقیق</th><th>زمان باقی‌مانده</th>'
                  f'<th>عملیات</th></tr></thead><tbody>{pend_html}</tbody></table>') if pend_html else \
        '<p class="empty-note">الان درخواست پرداخت بازی نیست. ✨</p>'

    # --- دونیت‌های زنده از API دونیتو ---
    live_block = ""
    if live:
        try:
            dons = donito_fetch_recent()
        except RuntimeError as e:
            dons = None
            live_block = f'<div class="alert">⚠️ خواندن از دونیتو ناموفق بود: {esc(str(e)[:250])}</div>'
        if dons is not None:
            body = ""
            for d in dons[:30]:
                key = "donito:" + d["id"]
                if key in matched:
                    rid, uid = matched[key]
                    status = f'<span class="badge approved">✅ شارژ شد</span> <small class="muted">#{rid} · کاربر {uid}</small>'
                elif d["amount"] in pend_amounts:
                    status = (f'<span class="badge pending">⏳ در انتظار تطبیق</span> '
                              f'<small class="muted">#{pend_amounts[d["amount"]]}</small>')
                else:
                    status = '<span class="badge closed">❔ بدون درخواست</span>'
                body += (f'<tr><td data-label="مبلغ" class="num">{d["amount"]:,}</td>'
                         f'<td data-label="زمان"><small class="muted">{fmt_dt(d["created_at"])}</small></td>'
                         f'<td data-label="شناسه"><small class="muted num" dir="ltr">{esc(d["id"])}</small></td>'
                         f'<td data-label="وضعیت">{status}</td></tr>')
            live_block = (f'<table class="rt"><thead><tr><th>مبلغ (تومان)</th><th>زمان</th><th>شناسه</th><th>وضعیت</th>'
                          f'</tr></thead><tbody>{body or "<tr><td colspan=4>دونیتی نیست.</td></tr>"}</tbody></table>'
                          f'<p><small class="muted">«بدون درخواست» یعنی دونیتی که مبلغش با هیچ درخواست شارژی نخورده '
                          f'(حامی عادی یا مبلغ اشتباه). اگه کاربر مبلغ اشتباه داد، از صفحه‌ی کاربر کیف پولش رو دستی شارژ کن.</small></p>')
    else:
        live_block = ('<p class="empty-note">برای دیدن ۵۰ دونیت آخر مستقیم از دونیتو و اینکه کدوم‌ها شارژ شدن، دکمه‌ی زیر رو بزن.</p>')

    # --- تاریخچه‌ی اخیر ---
    hist_html = ""
    for rid, uid, amt, st, created, _rt, mt in hist[:12]:
        hist_html += (f'<tr><td data-label="شماره">#{rid}</td><td data-label="کاربر"><a class="num" href="{url_for("user_detail", user_id=uid)}">{uid}</a></td>'
                      f'<td data-label="مبلغ" class="num">{int(amt or 0):,}</td>'
                      f'<td data-label="وضعیت"><span class="badge {esc(st)}">{esc(STATUS_LABELS.get(st, st))}</span></td>'
                      f'<td data-label="تاریخ"><small class="muted">{fmt_dt(created)}</small></td></tr>')

    live_dot_html = '<span class="live-dot"></span>'
    dot_on = (live_dot_html + " ") if enabled else ""
    dot_live = (" " + live_dot_html) if live else ""
    state_txt = "روشن" if enabled else "خاموش"
    content = f"""{PAGE_CSS_FIN}
    <div class="card">
      <div class="switch-row" style="padding-top:0;">
        <div><b>{dot_on}پرداخت ریالی خودکار — {state_txt}</b><br>
          <small class="muted">صفحه‌ی دونیت: <span dir="ltr">{esc(page_url)}</span> · توکن: <span dir="ltr">{esc(donito_masked())}</span>
          · مهلت هر درخواست: {fa(str(window // 60))} دقیقه</small></div>
        <form method="post" action="{url_for('donito_master')}">{tgl_btn(enabled)}</form>
      </div>
      <div class="flex" style="margin-top:10px;">
        <a class="btn sm" href="{url_for('donito_page')}?live=1">🔄 دونیت‌های زنده از دونیتو</a>
        <form method="post" action="{url_for('donito_test')}" style="display:inline;"><button type="submit" class="secondary sm">🔌 تست اتصال</button></form>
        <a class="btn secondary sm" href="{url_for('settings_page')}">⚙️ تنظیمات</a>
        <a class="btn secondary sm" href="{url_for('finance_page')}">💎 مرکز مالی</a>
      </div>
    </div>
    <div class="card"><h3>درخواست‌های در انتظار پرداخت <span class="badge pending">{len(pend)}</span></h3>{pend_block}</div>
    <div class="card"><h3>دونیت‌های اخیر{dot_live}</h3>{live_block}</div>
    <div class="card"><h3>۱۲ درخواست آخر</h3>
      <table class="rt"><thead><tr><th>شماره</th><th>کاربر</th><th>مبلغ</th><th>وضعیت</th><th>تاریخ</th></tr></thead>
      <tbody>{hist_html or '<tr><td colspan="5">هنوز درخواستی نیست.</td></tr>'}</tbody></table></div>
    <script>
      function cp(t, b) {{
        function ok() {{ if (b) {{ var o = b.textContent; b.textContent = '✔️'; setTimeout(function () {{ b.textContent = o; }}, 1200); }} }}
        if (navigator.clipboard && navigator.clipboard.writeText) {{ navigator.clipboard.writeText(t).then(ok, ok); return; }}
        var a = document.createElement('textarea'); a.value = t; document.body.appendChild(a); a.select();
        try {{ document.execCommand('copy'); }} catch (e) {{}} document.body.removeChild(a); ok();
      }}
      (function () {{
        var els = document.querySelectorAll('.cd[data-exp]');
        function tick() {{
          var now = Date.now() / 1000;
          els.forEach(function (el) {{
            var left = Math.floor(parseFloat(el.dataset.exp) - now);
            if (left <= 0) {{ el.textContent = 'منقضی'; el.classList.add('low'); return; }}
            var m = Math.floor(left / 60), s = left % 60;
            el.textContent = m + ':' + (s < 10 ? '0' : '') + s;
            el.classList.toggle('low', left < 300);
          }});
        }}
        if (els.length) {{ tick(); setInterval(tick, 1000); setTimeout(function () {{ location.reload(); }}, 20000); }}
      }})();
    </script>"""
    return render_page("مانیتور دونیتو", "donito", content)


@app.route("/donito/test", methods=["POST"])
@login_required
def donito_test():
    try:
        dons = donito_fetch_recent()
        last = dons[0] if dons else None
        flash(f"✅ اتصال به دونیتو برقراره؛ {len(dons)} دونیت خونده شد"
              + (f" (آخرین: {last['amount']:,} تومان)" if last else "") + ".")
    except RuntimeError as e:
        flash("⚠️ اتصال به دونیتو ناموفق بود: " + str(e)[:250])
    return redirect(url_for("donito_page"))



def _keepalive_url(port):
    """آدرس عمومی سرویس برای پینگ. Render خودش RENDER_EXTERNAL_URL رو ست می‌کنه (نیازی به تنظیم دستی نیست)."""
    for cand in (os.getenv("KEEPALIVE_URL", ""), os.getenv("RENDER_EXTERNAL_URL", "")):
        cand = (cand or "").strip().rstrip("/")
        if cand:
            return cand + "/healthz"
    return "http://127.0.0.1:%d/healthz" % port


def start_keepalive(port, interval=300):
    """هر ۵ دقیقه به آدرس عمومیِ خودِ سرویس درخواست می‌زنه تا Render (پلن رایگان) بعد از ۱۵ دقیقه بی‌ترافیکی سرویس رو نخوابونه."""
    def _loop():
        time.sleep(60)
        while True:
            try:
                requests.get(_keepalive_url(port), timeout=20)
            except Exception as e:
                print("⚠️ keepalive:", e)
            time.sleep(interval)
    threading.Thread(target=_loop, daemon=True).start()


# ---------------------------------------------------------------------------
# بسته‌های آماده (پلن‌ها) — ذخیره تو settings با کلید plans (JSON)؛ بات از همین‌جا می‌خونه
# ---------------------------------------------------------------------------
PLAN_TYPES = {"both": "هر دو (کانفیگ + وایرگارد)", "config": "کانفیگ", "wireguard": "وایرگارد",
              "openvpn": "OpenVPN", "dns": "DNS بازی"}


def _load_plans():
    try:
        data = json.loads(get_setting("plans", "") or "[]")
    except Exception:
        data = []
    return data if isinstance(data, list) else []


def _save_plans(lst):
    set_setting("plans", json.dumps(lst, ensure_ascii=False))


def _parse_plan_form(prefix=""):
    """(plan_dict | None, خطا). فیلدها: title, gb, days, price, type, active."""
    f = request.form
    title = (f.get(prefix + "title") or "").strip()[:40]
    try:
        gb = float((f.get(prefix + "gb") or "").replace(",", "."))
        days = int(f.get(prefix + "days") or 0)
        price = int((f.get(prefix + "price") or "0").replace(",", ""))
    except ValueError:
        return None, "حجم، مدت و قیمت باید عدد باشن."
    if not (0 < gb <= 100000) or gb != gb:
        return None, "حجم باید بین ۰ و ۱۰۰۰۰۰ گیگ باشه."
    if not (1 <= days <= 3650):
        return None, "مدت باید بین ۱ تا ۳۶۵۰ روز باشه."
    if not (0 <= price <= 1_000_000_000):
        return None, "قیمت نامعتبره."
    ptype = f.get(prefix + "type") or "both"
    if ptype not in PLAN_TYPES:
        return None, "نوع سرویس نامعتبره."
    gb = int(gb) if gb == int(gb) else round(gb, 3)
    return {"title": title, "gb": gb, "days": days, "price": price, "type": ptype,
            "active": f.get(prefix + "active") == "1"}, None


def _plan_type_select(name, cur):
    opts = "".join(f'<option value="{k}"{" selected" if k == cur else ""}>{esc(v)}</option>' for k, v in PLAN_TYPES.items())
    return f'<select name="{name}">{opts}</select>'


@app.route("/plans")
@login_required
def plans_page():
    plans = _load_plans()
    rows = ""
    for i, p in enumerate(plans):
        pid = esc(str(p.get("id", "")))
        rows += f"""
        <form method="post" action="{url_for('plans_act')}" class="card">
          <input type="hidden" name="pid" value="{pid}">
          <div class="grid cols-2">
            <div><label>عنوان دکمه (خالی = خودکار)</label><input type="text" name="title" maxlength="40" value="{esc(p.get('title', ''))}"></div>
            <div><label>نوع سرویس</label>{_plan_type_select('type', p.get('type', 'both'))}</div>
            <div><label>حجم (گیگ)</label><input type="text" name="gb" inputmode="decimal" value="{esc(str(p.get('gb', '')))}" required></div>
            <div><label>مدت (روز)</label><input type="number" name="days" min="1" value="{esc(str(p.get('days', '')))}" required></div>
            <div><label>قیمت (تومان)</label><input type="number" name="price" min="0" value="{esc(str(p.get('price', '')))}" required></div>
            <div><label>نمایش در ربات</label>
              <label style="display:flex;gap:8px;align-items:center;"><input type="checkbox" name="active" value="1"{' checked' if p.get('active', True) else ''}> فعال</label></div>
          </div>
          <div class="flex" style="margin-top:12px;">
            <button type="submit" name="act" value="save" class="sm">💾 ذخیره</button>
            <button type="submit" name="act" value="up" class="secondary sm" formnovalidate>▲</button>
            <button type="submit" name="act" value="down" class="secondary sm" formnovalidate>▼</button>
            <button type="submit" name="act" value="delete" class="danger sm" formnovalidate
                    onclick="return confirm('این بسته حذف بشه؟');">🗑 حذف</button>
          </div>
        </form>"""
    if not rows:
        rows = '<div class="card"><p class="muted">هنوز بسته‌ای نساختی؛ تا وقتی بسته‌ای نباشه، ربات خرید دلخواه (حجم و مدت) رو مستقیم نشون می‌ده.</p></div>'
    content = f"""
    <div class="card"><small class="muted">بسته‌های فعال تو منوی خرید ربات به‌صورت دکمه نشون داده می‌شن و زیرشون دکمه‌ی «خرید دلخواه» هست. ترتیب نمایش همین ترتیب لیسته.</small></div>
    {rows}
    <form method="post" action="{url_for('plans_act')}" class="card">
      <h3>➕ بسته‌ی جدید</h3>
      <input type="hidden" name="act" value="add">
      <div class="grid cols-2">
        <div><label>عنوان دکمه (اختیاری)</label><input type="text" name="title" maxlength="40" placeholder="مثلاً ۲۰ گیگ / ۳۰ روزه"></div>
        <div><label>نوع سرویس</label>{_plan_type_select('type', 'both')}</div>
        <div><label>حجم (گیگ)</label><input type="text" name="gb" inputmode="decimal" required></div>
        <div><label>مدت (روز)</label><input type="number" name="days" min="1" required></div>
        <div><label>قیمت (تومان)</label><input type="number" name="price" min="0" required></div>
        <div><label>نمایش در ربات</label><label style="display:flex;gap:8px;align-items:center;"><input type="checkbox" name="active" value="1" checked> فعال</label></div>
      </div>
      <div style="margin-top:12px;"><button type="submit">➕ افزودن بسته</button></div>
    </form>"""
    return render_page("بسته‌های آماده", "plans", content)


@app.route("/plans/act", methods=["POST"])
@login_required
def plans_act():
    act = request.form.get("act")
    pid = (request.form.get("pid") or "").strip()
    plans = _load_plans()
    if act == "add":
        p, err = _parse_plan_form()
        if err:
            flash("⚠️ " + err)
        elif len(plans) >= 30:
            flash("⚠️ حداکثر ۳۰ بسته مجازه.")
        else:
            p["id"] = secrets.token_hex(3)
            plans.append(p)
            _save_plans(plans)
            flash("بسته اضافه شد.")
        return redirect(url_for("plans_page"))
    idx = next((i for i, x in enumerate(plans) if str(x.get("id")) == pid), None)
    if idx is None:
        flash("⚠️ بسته پیدا نشد.")
    elif act == "save":
        p, err = _parse_plan_form()
        if err:
            flash("⚠️ " + err)
        else:
            p["id"] = plans[idx]["id"]
            plans[idx] = p
            _save_plans(plans)
            flash("بسته ذخیره شد.")
    elif act == "delete":
        plans.pop(idx)
        _save_plans(plans)
        flash("بسته حذف شد.")
    elif act in ("up", "down"):
        j = idx - 1 if act == "up" else idx + 1
        if 0 <= j < len(plans):
            plans[idx], plans[j] = plans[j], plans[idx]
            _save_plans(plans)
    return redirect(url_for("plans_page"))


# ---------------------------------------------------------------------------
# هشدار انقضا و اتمام حجم (تنظیمات؛ خودِ ارسال کار بات است)
# ---------------------------------------------------------------------------
@app.route("/alerts")
@login_required
def alerts_page():
    st = get_all_settings()
    on = st.get("alerts_enabled", "1") == "1"
    exp_notice = st.get("alert_expired_notice", "1") == "1"
    content = f"""
    <form method="post" action="{url_for('alerts_save')}">
      <div class="card">
        <label style="display:flex;gap:8px;align-items:center;"><input type="checkbox" name="alerts_enabled" value="1"{' checked' if on else ''}> <b>⏰ هشدارهای انقضا و حجم فعال باشه</b></label>
        <label style="display:flex;gap:8px;align-items:center;margin-top:12px;"><input type="checkbox" name="alert_expired_notice" value="1"{' checked' if exp_notice else ''}> وقتی کانفیگ منقضی شد هم پیام بده (فقط برای منقضی‌های ۲ روز اخیر)</label>
        <label style="margin-top:12px;">چند روز مونده به انقضا هشدار بره؟</label>
        <input type="number" name="alert_expiry_days" min="1" max="60" value="{esc(st.get('alert_expiry_days', '3'))}">
        <label style="margin-top:12px;">هشدار حجم وقتی چند درصد مصرف شد؟</label>
        <input type="number" name="alert_volume_percent" min="1" max="99" value="{esc(st.get('alert_volume_percent', '90'))}">
        <label style="margin-top:12px;">هر چند دقیقه یک‌بار بررسی بشه؟ (حداقل ۵)</label>
        <input type="number" name="alert_interval_min" min="5" max="1440" value="{esc(st.get('alert_interval_min', '30'))}">
        <hr style="margin:18px 0;border:0;border-top:1px solid var(--border,#ddd);">
        <label style="display:flex;gap:8px;align-items:center;"><input type="checkbox" name="nudge_trial_enabled" value="1"{' checked' if st.get('nudge_trial_enabled', '1') == '1' else ''}> <b>👋 یادآوری به کسی که تست گرفته و نخریده (فقط یک‌بار)</b></label>
        <label style="margin-top:12px;">چند ساعت بعد از گرفتن تست پیام بره؟</label>
        <input type="number" name="nudge_trial_hours" min="1" max="168" value="{esc(st.get('nudge_trial_hours', '48'))}">
        <div style="margin-top:14px;"><button type="submit">💾 ذخیره</button></div>
      </div>
    </form>
    <div class="card"><small class="muted">هر هشدار برای هر کانفیگ فقط یک‌بار فرستاده می‌شه و بعد از تمدید دوباره مجازه. کانفیگ‌های تست رایگان و متوقف‌شده هشدار نمی‌گیرن. پیام «حجم تموم شد» هم جداست. متن هشدارها از صفحه‌ی «متن‌های ربات» قابل ویرایشه.</small></div>"""
    return render_page("هشدارها و یادآوری‌ها", "alerts", content)


@app.route("/alerts/save", methods=["POST"])
@login_required
def alerts_save():
    f = request.form

    def num(name, lo, hi, default):
        try:
            return str(min(hi, max(lo, int(f.get(name) or default))))
        except ValueError:
            return str(default)
    set_setting("alerts_enabled", "1" if f.get("alerts_enabled") == "1" else "0")
    set_setting("alert_expired_notice", "1" if f.get("alert_expired_notice") == "1" else "0")
    set_setting("alert_expiry_days", num("alert_expiry_days", 1, 60, 3))
    set_setting("alert_volume_percent", num("alert_volume_percent", 1, 99, 90))
    set_setting("alert_interval_min", num("alert_interval_min", 5, 1440, 30))
    set_setting("nudge_trial_enabled", "1" if f.get("nudge_trial_enabled") == "1" else "0")
    set_setting("nudge_trial_hours", num("nudge_trial_hours", 1, 168, 48))
    flash("تنظیمات هشدار ذخیره شد.")
    return redirect(url_for("alerts_page"))


# ---------------------------------------------------------------------------
# متغیرهای محیطی قابل تغییر از پنل (بات و پنل حداکثر ~۱۵ ثانیه بعد اعمالش می‌کنن)
# ---------------------------------------------------------------------------
ENV_FIELDS = [
    # (کلید settings, عنوان, راهنما, مخفی؟)
    ("donito_token", "توکن دونیتو", "برای شارژ خودکار با دونیتو", True),
    ("env_bot_token", "توکن ربات (BOT_TOKEN)", "قبل از ذخیره با getMe تست می‌شه؛ اشتباه بودنش ربات رو از کار می‌ندازه", True),
    ("env_seller_api_key", "کلید Seller API (SELLER_API_KEY)", "برای حساب فروشنده‌ها", True),
    ("env_seller_api_base", "آدرس Seller API (SELLER_API_BASE)", "مثلاً https://su.randomatic.ir/api/v1", False),
    ("env_config_key", "کلید ساخت کانفیگ (CONFIG_KEY)", "", True),
    ("env_config_api", "آدرس ساخت کانفیگ (CONFIG_API)", "", False),
    ("env_nobitex_api_key", "کلید نوبیتکس (NOBITEX_API_KEY)", "برای تشخیص خودکار واریز رمزارز", True),
    ("env_nobitex_api_secret", "رمز نوبیتکس (NOBITEX_API_SECRET)", "", True),
]


def _mask_secret(v):
    v = v or ""
    return ("•" * 8 + v[-4:]) if len(v) > 8 else "•" * len(v)


@app.route("/env")
@login_required
def env_page():
    st = get_all_settings()
    rows = ""
    for key, label, hint, secret in ENV_FIELDS:
        cur = st.get(key) or ""
        if cur:
            shown = _mask_secret(cur) if secret else cur
            badge = f'<span class="badge approved">از پنل: <span dir="ltr">{esc(shown)}</span></span>'
        else:
            badge = '<span class="badge open">از Environment / پیش‌فرض کد</span>'
        rows += f"""
        <div class="card">
          <label><b>{esc(label)}</b></label>
          <div style="margin:6px 0;">{badge}</div>
          <input type="{'password' if secret else 'text'}" name="{key}" dir="ltr" autocomplete="off" placeholder="مقدار جدید (خالی = بدون تغییر)">
          {f'<small class="muted">{esc(hint)}</small><br>' if hint else ''}
          <label style="display:flex;gap:8px;align-items:center;margin-top:8px;"><input type="checkbox" name="reset_{key}" value="1"> حذفِ مقدار پنل و برگشت به Environment/پیش‌فرض</label>
        </div>"""
    content = f"""
    <div class="card"><small class="muted">مقدارهایی که اینجا ذخیره کنی روی Environment اولویت دارن و بدون ری‌استارت اعمال می‌شن. این مقدارها تو خروجی بکاپ تنظیمات <b>نمی‌آن</b>.
    آدرس/توکن دیتابیس (Turso) و رمز ورود خود پنل رو نمی‌شه از اینجا عوض کرد؛ اون‌ها فقط از Environment خونده می‌شن.</small></div>
    <form method="post" action="{url_for('env_save')}">{rows}
      <div><button type="submit">💾 ذخیره</button></div>
    </form>"""
    return render_page("متغیرهای محیطی", "envvars", content)


@app.route("/env/save", methods=["POST"])
@login_required
def env_save():
    changed, errors = 0, []
    for key, label, _hint, _secret in ENV_FIELDS:
        if request.form.get("reset_" + key) == "1":
            delete_setting(key)
            changed += 1
            continue
        val = (request.form.get(key) or "").strip()
        if not val:
            continue
        if len(val) > 500 or re.search(r"\s", val):
            errors.append(f"{label}: مقدار نامعتبره.")
            continue
        if key in ("env_seller_api_base", "env_config_api") and not val.startswith(("http://", "https://")):
            errors.append(f"{label}: باید با http:// یا https:// شروع بشه.")
            continue
        if key == "env_bot_token":
            try:
                ok = requests.get(f"https://api.splus.ir/bot{val}/getMe", timeout=8).json().get("ok")
            except Exception:
                ok = False
            if not ok:
                errors.append("توکن ربات رد شد: getMe با این توکن موفق نبود، پس ذخیره نشد.")
                continue
        set_setting(key, val)
        changed += 1
    try:
        apply_env_overrides(force=True)
    except Exception as e:
        print("⚠️ apply_env_overrides:", e)
    for e in errors:
        flash("⚠️ " + e)
    if changed:
        flash(f"{changed} مقدار ذخیره شد؛ بات حداکثر تا ~۱۵ ثانیه‌ی دیگه اعمالش می‌کنه.")
    elif not errors:
        flash("تغییری ثبت نشد.")
    return redirect(url_for("env_page"))




@app.route("/healthz")
def healthz():
    return "ok", 200


if __name__ == "__main__":
    try:
        ensure_schema()
    except Exception as e:
        print("⚠️ ensure_schema:", e)
    port = int(os.getenv("PORT", "8080"))
    start_keepalive(port)
    app.run(host="0.0.0.0", port=port)
