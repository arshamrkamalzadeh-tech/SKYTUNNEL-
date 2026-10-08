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

BOT_TOKEN = os.getenv("BOT_TOKEN", "69786607:p-AAjsil8xAOknphz-PxbDBsvFxFSWknCMg")
BASE_URL = "https://api.splus.ir/bot" + BOT_TOKEN

PANEL_USERNAME = os.getenv("PANEL_USERNAME", "admin")
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "change-me-please")
SECRET_KEY = os.getenv("SECRET_KEY", "x7Kp9mZq2vLwR4tYbN8jFcH1")
INSECURE_DEFAULTS = (PANEL_PASSWORD == "change-me-please") or (SECRET_KEY == "sky-panel-secret-change-me")

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
        ("min_topup", "حداقل مبلغ شارژ کیف پول (تومان)", DEFAULT_MIN_TOPUP, "number"),
        ("topup_multiplier", "ضریب واریزی (مثلاً 2 یعنی دو برابر مبلغ واریزی به کیف پول اضافه شود)", "1", "float"),
    ]),
    ("🧪 تست رایگان و خرید", [
        ("trial_gb", "حجم تست رایگان (گیگ — اعشاری مجاز، مثل 0.1)", "0.1", "float"),
        ("trial_days", "مدت تست رایگان (روز)", "1", "number"),
        ("trial_label", "اسم کانفیگ تست رایگان (همون اسمی که تو پنل اصلی ثبت می‌شه)", "تست رایگان", "text"),
        ("default_gb", "حجم پیش‌فرض صفحه‌ی خرید (گیگ)", "1", "number"),
        ("default_days", "مدت پیش‌فرض صفحه‌ی خرید (روز)", "30", "number"),
        ("refund_ratio", "نسبت بازگشت وجه هنگام حذف کانفیگ (بین 0 تا 1؛ مثلاً 0.5 یعنی نصف ارزش باقی‌مانده)", "0.5", "float"),
    ]),
    ("🧑‍💼 فروشندگی (ریسلر)", [
        ("reseller_min_gb", "حداقل خرید برای فعال‌سازی فروشندگی (گیگ)", "50", "number"),
        ("reseller_price_per_gb", "قیمت هر گیگ هنگام فعال‌سازی فروشندگی (تومان)", "2000", "number"),
        ("reseller_topup_min_gb", "حداقل خرید در «افزایش استخر گیگ» (گیگ)", "1", "number"),
        ("reseller_topup_tiers", "قیمت پله‌ای افزایش استخر — قالب «سقف:قیمت» با کاما؛ آخرین پله با ستاره. مثل 10:3500,20:3000,30:2500,*:2000",
         "10:3500,20:3000,30:2500,*:2000", "tiers"),
        ("reseller_panel_url", "آدرس پنلی که به فروشنده‌ها نشون داده می‌شه", DEFAULT_RESELLER_PANEL_URL, "url"),
    ]),
    ("📲 لینک‌های دانلود اپ", [
        ("app_link_android", "لینک اندروید", os.getenv("APP_LINK_ANDROID", "https://play.google.com/store/apps/details?id=com.v2pro.client"), "url"),
        ("app_link_ios", "لینک iOS", os.getenv("APP_LINK_IOS", "https://apps.apple.com/us/app/v2pro/id6801607092"), "url"),
        ("app_link_windows", "لینک ویندوز", os.getenv("APP_LINK_WINDOWS", "https://su.randomatic.ir/v2pro/1.1.2/V2Pro-Setup-x64.exe"), "url"),
        ("app_link_mac", "لینک مک", os.getenv("APP_LINK_MAC", "https://su.randomatic.ir/v2pro/1.1.2/v2pro-macos-universal.zip"), "url"),
        ("app_link_linux", "لینک لینوکس", os.getenv("APP_LINK_LINUX", "https://su.randomatic.ir/v2pro/1.1.2/v2pro-linux-x64.tar.gz"), "url"),
    ]),
    ("🛠 مدیریت و نگهداری ربات", [
        ("admin_id", "آیدی عددی ادمین (تیکت‌ها و رسیدهای شارژ برای این آیدی میاد)", os.getenv("ADMIN_ID", "48198481"), "number"),
        ("maintenance_text", "پیامی که تو «حالت تعمیر» به کاربران نشون داده می‌شه",
         "🛠 ربات موقتاً در حال بروزرسانی است. لطفاً کمی بعد دوباره تلاش کنید.", "text"),
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
    ]),
]
# نسخه‌ی تخت برای اعتبارسنجی/ذخیره
CONFIG_SETTINGS = [(k, label, default, kind) for _title, items in CONFIG_GROUPS for k, label, default, kind in items]

# (متن‌های ربات از «رجیستری» که خود bot.py موقع استارت تو دیتابیس می‌نویسه خونده می‌شن؛ صفحه‌ی /texts)

# متن دکمه‌های منوی اصلی: (کلید داخلی ثابت, عنوان تو پنل, متن پیش‌فرض دکمه)
BOT_BUTTONS = [
    ("recentorders", "دکمه‌ی سفارشات اخیر من", "🧾 سفارشات اخیر من"),
    ("buy", "دکمه‌ی خرید کانفیگ", "🛍 خرید کانفیگ"),
    ("trial", "دکمه‌ی تست رایگان", "🧪 تست رایگان"),
    ("topup", "دکمه‌ی شارژ کیف پول", "💠 شارژ کیف پول"),
    ("account", "دکمه‌ی حساب من", "👤 حساب من"),
    ("myconfigs", "دکمه‌ی کانفیگ‌های من", "🗂 کانفیگ‌های من"),
    ("delete", "دکمه‌ی حذف کانفیگ", "🗑 حذف کانفیگ"),
    ("support", "دکمه‌ی پشتیبانی", "🎧 پشتیبانی"),
    ("guide", "دکمه‌ی اپ مخصوص کانفیگ‌ها", "📲 اپ مخصوص کانفیگ‌ها"),
    ("language", "دکمه‌ی تغییر زبان", "🌐 تغییر زبان"),
    ("reseller", "دکمه‌ی فروشنده شو", "🧑‍💼 فروشنده شو"),
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
    "delete_config": "🗑 حذف کانفیگ",
    "support": "🎧 پشتیبانی",
    "reseller": "🧑‍💼 فروشنده شو",
    "guide": "📲 اپ مخصوص کانفیگ‌ها",
    "recentorders": "🧾 سفارشات اخیر من",
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
    c.execute("SELECT user_id FROM users")
    res = [r[0] for r in c.fetchall()]
    conn.close()
    return res


@with_db_retry
def toggle_reseller_status(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE resellers SET status = CASE WHEN status='active' THEN 'blocked' ELSE 'active' END "
              "WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


@with_db_retry
def update_reseller_price(user_id, price):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE resellers SET price_per_gb=? WHERE user_id=?", (price, user_id))
    conn.commit()
    conn.close()


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
            "ALTER TABLE resellers ADD COLUMN username TEXT",
            "ALTER TABLE resellers ADD COLUMN password_hash TEXT",
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
    "reseller_activate_confirm": "تایید پرداخت فعال‌سازی فروشندگی",
}
CB_PREFIXES = (
    ("reply_ticket_", "پاسخ به تیکت"), ("close_ticket_", "بستن تیکت"),
    ("topup_acc_", "تایید شارژ"), ("topup_rej_", "رد شارژ"),
)
STEP_LABELS = {
    "ask_label": "در حال انتخاب اسم کانفیگ", "confirm_buy": "در صفحه‌ی تایید خرید",
    "buy_enter_discount": "در حال وارد کردن کد تخفیف", "waiting_receipt": "در حال ارسال رسید شارژ",
    "admin_reply": "در حال پاسخ به تیکت",
}


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


def _users_where(search, only_recent):
    where, params = [], []
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
def get_users_count(search=None, only_recent=False):
    conn = get_conn()
    c = conn.cursor()
    where, params = _users_where(search, only_recent)
    c.execute(f"SELECT COUNT(*) FROM users {where}", params)
    total = c.fetchone()[0]
    conn.close()
    return total


@with_db_retry
def get_users_page(offset=0, limit=USERS_PAGE_SIZE, search=None, sort="active", only_recent=False):
    conn = get_conn()
    c = conn.cursor()
    where, params = _users_where(search, only_recent)
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
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, user_id, amount, status, created_at FROM topup_requests ORDER BY id DESC LIMIT ?", (limit,))
    res = c.fetchall()
    conn.close()
    return res


@with_db_retry
def get_all_resellers():
    """(user_id, username_ورود, رمز_تنظیم_شده؟, gb_balance, price_per_gb, status, revenue, configs_count, tg_username, tg_name)"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT r.user_id, r.username,
               CASE WHEN r.password_hash IS NOT NULL AND r.password_hash <> '' THEN 1 ELSE 0 END,
               r.gb_balance, r.price_per_gb, r.status,
               COALESCE((SELECT SUM(price) FROM reseller_pool_log WHERE user_id = r.user_id), 0),
               COALESCE((SELECT COUNT(*) FROM reseller_api_configs WHERE reseller_id = r.user_id AND active = 1), 0),
               u.username, u.first_name
        FROM resellers r LEFT JOIN users u ON u.user_id = r.user_id
        ORDER BY r.created_at DESC
    """)
    res = c.fetchall()
    conn.close()
    return res


@with_db_retry
def get_reseller(user_id):
    rows = [r for r in get_all_resellers() if r[0] == user_id]
    return rows[0] if rows else None


@with_db_retry
def get_reseller_created(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT created_at FROM resellers WHERE user_id=?", (user_id,))
    r = c.fetchone()
    conn.close()
    return r[0] if r else None


@with_db_retry
def reseller_username_taken(username, except_user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT 1 FROM resellers WHERE username=? AND user_id<>?", (username, except_user_id))
    r = c.fetchone()
    conn.close()
    return bool(r)


@with_db_retry
def set_reseller_login(user_id, username=None, password_hash=None):
    conn = get_conn()
    c = conn.cursor()
    if username is not None:
        c.execute("UPDATE resellers SET username=? WHERE user_id=?", (username, user_id))
    if password_hash is not None:
        c.execute("UPDATE resellers SET password_hash=? WHERE user_id=?", (password_hash, user_id))
    conn.commit()
    conn.close()


@with_db_retry
def add_reseller_gb(user_id, delta):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE resellers SET gb_balance = MAX(0, gb_balance + ?) WHERE user_id=?", (delta, user_id))
    conn.commit()
    conn.close()


@with_db_retry
def get_reseller_configs(reseller_id, limit=100):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT label, type, gb, days, active, created_at, source, config_id "
              "FROM reseller_api_configs WHERE reseller_id=? ORDER BY id DESC LIMIT ?", (reseller_id, limit))
    res = c.fetchall()
    conn.close()
    return res


@with_db_retry
def get_reseller_api_keys(reseller_id):
    """کلیدهای API برنامه‌نویسی فروشنده (جدول seller_api_keys که پنل فروشندگان می‌سازه). فقط پیشوند نمایش داده می‌شه."""
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("SELECT id, name, prefix, created_at, last_used, COALESCE(revoked,0) FROM seller_api_keys "
                  "WHERE reseller_id=? ORDER BY created_at DESC", (reseller_id,))
        res = c.fetchall()
    except Exception as e:
        if "stream" in str(e).lower():
            raise
        res = []
    conn.close()
    return res


@with_db_retry
def revoke_reseller_api_key(reseller_id, key_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE seller_api_keys SET revoked=1 WHERE id=? AND reseller_id=?", (key_id, reseller_id))
    conn.commit()
    conn.close()


RESELLER_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.]{3,20}$")
RESELLER_PASSWORD_MIN, RESELLER_PASSWORD_MAX = 6, 64
_PBKDF2_ITERS = 200_000


def hash_reseller_password(password):
    """همون فرمتی که bot.py و پنل فروشندگان (app.py) انتظار دارن: pbkdf2_sha256$تکرار$salt$hash"""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERS)
    return f"pbkdf2_sha256${_PBKDF2_ITERS}${salt}${dk.hex()}"


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


@app.before_request
def _before_request():
    if request.endpoint == "static":
        return None
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
    if (!t) t = (window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', t);
  })();
</script>
<style>
  :root {
    --bg: #f3f5fa; --surface: #ffffff; --surface-2: #f6f8fc; --border: #e2e7f0; --ink: #14213d; --muted: #66748f;
    --brand: #3b5bfd; --brand-ink: #ffffff; --brand-dim: rgba(59,91,253,.10);
    --side: #101a33; --side-ink: #b4c0de; --side-active: rgba(255,255,255,.09); --sun: #ffb324;
    --ok: #0f8a63; --ok-dim: rgba(15,138,99,.12); --warn: #9a5b00; --warn-dim: rgba(255,179,36,.22);
    --danger: #cf3d3d; --danger-dim: rgba(207,61,61,.10);
    --shadow: 0 1px 2px rgba(16,26,51,.05), 0 6px 20px rgba(16,26,51,.05);
    --radius: 16px; --nav-h: 66px;
  }
  [data-theme="dark"] {
    --bg: #0b1226; --surface: #131d38; --surface-2: #19254a; --border: #26345c; --ink: #e8edfb; --muted: #94a3c6;
    --brand: #6f86ff; --brand-ink: #0b1226; --brand-dim: rgba(111,134,255,.16);
    --side: #0a1020; --side-ink: #9fb0d8; --side-active: rgba(255,255,255,.07);
    --ok: #3ddc97; --ok-dim: rgba(61,220,151,.14); --warn: #ffc457; --warn-dim: rgba(255,179,36,.16);
    --danger: #ff7b7b; --danger-dim: rgba(255,123,123,.14);
    --shadow: 0 1px 2px rgba(0,0,0,.25), 0 6px 20px rgba(0,0,0,.2);
  }
  * { box-sizing: border-box; }
  html { scroll-behavior: smooth; }
  body { margin: 0; font-family: 'Vazirmatn', Tahoma, sans-serif; font-size: 14.5px; line-height: 1.8; background: var(--bg); color: var(--ink); -webkit-text-size-adjust: 100%; }
  a { color: var(--brand); }
  :focus-visible { outline: 3px solid var(--brand); outline-offset: 2px; }
  code { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: .92em; background: var(--surface-2); padding: 1px 6px; border-radius: 6px; direction: ltr; unicode-bidi: embed; }
  h2, h3, h4 { margin: 0; }
  h3 { font-size: 16.5px; margin: 0 0 12px; font-weight: 700; }
  .muted, small.muted { color: var(--muted); }
  .num { font-variant-numeric: tabular-nums; }

  /* ---------- سایدبار (دسکتاپ) ---------- */
  .sidebar { display: none; }
  @media (min-width: 1000px) {
    :root { --nav-h: 0px; }
    .sidebar { display: flex; flex-direction: column; position: fixed; top: 0; right: 0; bottom: 0; width: 262px; background: var(--side); color: var(--side-ink); padding: 22px 14px; overflow-y: auto; z-index: 30; }
    .shell { margin-right: 262px; }
    .bottom-nav, .topbar { display: none !important; }
    .app { padding-bottom: 48px !important; }
  }
  .brand { display: flex; align-items: center; gap: 12px; padding: 4px 8px 20px; }
  .mark { width: 38px; height: 38px; border-radius: 50%; background: var(--sun); position: relative; overflow: hidden; flex-shrink: 0; }
  .mark::after { content: ''; position: absolute; left: 0; right: 0; bottom: 0; height: 42%; background: var(--side); border-top: 2px solid #26345c; }
  .brand b { display: block; color: #fff; font-size: 18px; line-height: 1.3; }
  .brand span { font-size: 12px; opacity: .8; display: flex; align-items: center; gap: 6px; }
  .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; background: #3ddc97; }
  .dot.off { background: #7d8aab; }
  .nav-group { font-size: 11.5px; font-weight: 700; letter-spacing: .3px; opacity: .55; padding: 16px 12px 6px; }
  .side-link { display: flex; align-items: center; gap: 12px; padding: 10px 12px; border-radius: 12px; color: var(--side-ink); text-decoration: none; font-weight: 500; font-size: 14.5px; }
  .side-link svg { width: 20px; height: 20px; flex-shrink: 0; }
  .side-link:hover { background: var(--side-active); color: #fff; }
  .side-link.active { background: var(--brand); color: #fff; font-weight: 700; }
  .side-foot { margin-top: auto; padding-top: 16px; display: flex; gap: 8px; }
  .side-foot a, .side-foot button { flex: 1; text-align: center; padding: 9px 10px; border-radius: 10px; font-size: 13px; background: var(--side-active); color: #fff; border: none; text-decoration: none; cursor: pointer; font-family: inherit; font-weight: 600; }

  /* ---------- نوار بالا و پایین (موبایل) ---------- */
  .topbar { position: sticky; top: 0; z-index: 20; background: var(--side); color: #fff; padding: calc(env(safe-area-inset-top, 0px) + 10px) 16px 10px; display: flex; align-items: center; justify-content: space-between; border-bottom: 3px solid var(--sun); }
  .topbar .brand { padding: 0; }
  .topbar .brand b { font-size: 17px; }
  .icon-btn { width: 38px; height: 38px; border-radius: 10px; border: 1px solid rgba(255,255,255,.16); background: transparent; color: #dbe3f7; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; font-size: 17px; text-decoration: none; font-family: inherit; }
  .bottom-nav { position: fixed; bottom: 0; left: 0; right: 0; z-index: 40; background: var(--side); padding-bottom: env(safe-area-inset-bottom, 0px); }
  .nav-inner { max-width: 760px; margin: 0 auto; display: flex; }
  .bottom-nav a { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 9px 4px 8px; color: var(--side-ink); text-decoration: none; font-size: 11.5px; border-top: 3px solid transparent; }
  .bottom-nav a svg { width: 22px; height: 22px; }
  .bottom-nav a.active { color: #fff; font-weight: 700; border-top-color: var(--sun); }
  .drawer-overlay { display: none; position: fixed; inset: 0; background: rgba(8,13,28,.6); z-index: 50; }
  .drawer-overlay:target { display: block; }
  .drawer { position: absolute; bottom: 0; left: 50%; transform: translateX(-50%); width: 100%; max-width: 760px; background: var(--surface); border-radius: 22px 22px 0 0; padding: 10px 20px calc(env(safe-area-inset-bottom, 0px) + 24px); max-height: 84vh; overflow-y: auto; }
  .drawer .handle { width: 40px; height: 4px; background: var(--border); border-radius: 4px; margin: 8px auto 12px; }
  .drawer h4 { font-size: 12px; color: var(--muted); margin: 16px 0 2px; }
  .drawer a.dl { display: flex; align-items: center; gap: 12px; padding: 12px 2px; color: var(--ink); text-decoration: none; font-weight: 600; border-bottom: 1px solid var(--border); }
  .drawer a.dl svg { width: 20px; height: 20px; color: var(--brand); }

  /* ---------- محتوا ---------- */
  .app { max-width: 1120px; margin: 0 auto; padding: 22px 16px calc(var(--nav-h) + env(safe-area-inset-bottom, 0px) + 40px); }
  @media (min-width: 1000px) { .app { padding: 32px 36px 48px; } }
  .page-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 18px; }
  .page-title { font-size: 26px; font-weight: 800; line-height: 1.4; margin: 0; }
  .panel, .card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 18px 20px; margin-bottom: 16px; box-shadow: var(--shadow); }
  .panel > h3:first-child, .card > h3:first-child { margin-top: 0; }
  .grid { display: grid; gap: 14px; }
  .grid.cols-2 { grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-bottom: 16px; }
  .stat { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px; box-shadow: var(--shadow); display: flex; flex-direction: column; gap: 2px; }
  .stat span { font-size: 12.5px; color: var(--muted); }
  .stat b { font-size: 22px; font-weight: 800; line-height: 1.4; }
  .stat small { color: var(--muted); font-size: 12px; }
  .hero { background: linear-gradient(135deg, #1b2c5c, #101a33); color: #fff; border-radius: 22px; padding: 24px; margin-bottom: 16px; position: relative; overflow: hidden; }
  .hero::after { content: ''; position: absolute; left: -50px; bottom: -80px; width: 190px; height: 190px; border-radius: 50%; background: var(--sun); opacity: .95; }
  .hero > * { position: relative; z-index: 1; }
  .hero-label { font-size: 13px; color: #b4c0de; }
  .hero-number { font-size: 44px; font-weight: 800; line-height: 1.3; margin: 2px 0 8px; }
  .hero-unit { font-size: 16px; margin-right: 8px; color: #b4c0de; font-weight: 500; }
  .hero-meta { display: flex; gap: 26px; flex-wrap: wrap; padding-top: 12px; border-top: 1px solid rgba(255,255,255,.14); }
  .hero-meta div { display: flex; flex-direction: column; }
  .hero-meta b { font-size: 18px; }
  .hero-meta span { font-size: 12px; color: #b4c0de; }
  .ledger-row { display: flex; justify-content: space-between; gap: 12px; padding: 10px 0; border-bottom: 1px dashed var(--border); }
  .ledger-row:last-child { border-bottom: none; }
  .ledger-row span { color: var(--muted); }
  .row-link { display: flex; align-items: center; gap: 12px; padding: 11px 0; text-decoration: none; color: var(--ink); border-bottom: 1px solid var(--border); }
  .row-link:last-child { border-bottom: none; }
  .row-main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
  .row-main small { color: var(--muted); font-size: 12.5px; }
  .chev { color: var(--muted); font-size: 22px; }
  .icon-badge { width: 38px; height: 38px; border-radius: 11px; background: var(--warn-dim); display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
  .empty-note { color: var(--muted); margin: 4px 0 0; }
  .alert { background: var(--warn-dim); color: var(--warn); border-radius: 12px; padding: 12px 16px; margin-bottom: 16px; font-weight: 600; font-size: 13.5px; }
  .chart { width: 100%; height: auto; display: block; }
  .chart .bar { fill: var(--brand); }
  .chart .bar:hover { opacity: .75; }
  .chart text { fill: var(--muted); font-size: 10px; font-family: inherit; }
  .chart .gridline { stroke: var(--border); stroke-width: 1; }

  /* ---------- جدول ---------- */
  table { display: block; max-width: 100%; overflow-x: auto; border-collapse: collapse; background: var(--surface); border-radius: 14px; border: 1px solid var(--border); margin-bottom: 14px; box-shadow: var(--shadow); }
  th, td { padding: 11px 14px; text-align: right; border-bottom: 1px solid var(--border); font-size: 13.5px; white-space: nowrap; vertical-align: middle; }
  th { background: var(--surface-2); color: var(--muted); font-weight: 600; font-size: 12.5px; }
  tr:last-child td { border-bottom: none; }
  tbody tr:hover td { background: var(--surface-2); }
  td.wrap { white-space: normal; min-width: 180px; }
  @media (max-width: 700px) {
    table.rt { display: block; border: none; background: none; box-shadow: none; overflow: visible; }
    table.rt thead { display: none; }
    table.rt tbody, table.rt tr { display: block; }
    table.rt tr { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; margin-bottom: 10px; padding: 6px 14px; box-shadow: var(--shadow); }
    table.rt td { display: flex; justify-content: space-between; align-items: center; gap: 14px; border: none; padding: 7px 0; white-space: normal; text-align: left; }
    table.rt td::before { content: attr(data-label); color: var(--muted); font-size: 12px; flex-shrink: 0; text-align: right; }
    table.rt tbody tr:hover td { background: none; }
  }

  /* ---------- فرم‌ها ---------- */
  input[type=text], input[type=number], input[type=password], textarea, select {
    background: var(--surface); border: 1.5px solid var(--border); color: var(--ink); border-radius: 11px; padding: 10px 14px; font-size: 14.5px; width: 100%; font-family: inherit; }
  input:focus, textarea:focus, select:focus { outline: none; border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-dim); }
  textarea { min-height: 110px; resize: vertical; }
  label { display: block; margin: 14px 0 6px; font-size: 13px; color: var(--muted); font-weight: 600; }
  input[type=radio], input[type=checkbox] { width: auto; accent-color: var(--brand); }
  .reorder-row { display: flex; align-items: flex-end; gap: 8px; }
  .reorder-row > div:first-child { flex: 1; min-width: 0; }
  .reorder-row label { margin-top: 0; }
  .reorder-arrows { display: flex; flex-direction: column; gap: 4px; margin-bottom: 1px; }
  .reorder-arrows button { padding: 4px 11px; font-size: 11px; line-height: 1.4; }
  button, .btn { background: var(--brand); color: var(--brand-ink); border: 1.5px solid var(--brand); border-radius: 11px; padding: 9px 18px; font-size: 14px; font-weight: 700; cursor: pointer; font-family: inherit; text-decoration: none; display: inline-block; line-height: 1.7; }
  button:hover, .btn:hover { filter: brightness(1.08); }
  button.secondary, .btn.secondary { background: transparent; color: var(--ink); border-color: var(--border); }
  button.secondary:hover, .btn.secondary:hover { background: var(--surface-2); filter: none; }
  button.danger, .btn.danger { background: transparent; color: var(--danger); border-color: var(--danger-dim); }
  button.danger:hover, .btn.danger:hover { background: var(--danger-dim); filter: none; }
  button.sm, .btn.sm { padding: 4px 12px; font-size: 12.5px; border-radius: 9px; }
  .btn.block, button.block { width: 100%; text-align: center; }
  .badge { padding: 2px 11px; border-radius: 999px; font-size: 12px; font-weight: 700; display: inline-block; white-space: nowrap; }
  .badge.on, .badge.answered, .badge.approved { background: var(--ok-dim); color: var(--ok); }
  .badge.off, .badge.rejected { background: var(--danger-dim); color: var(--danger); }
  .badge.open, .badge.pending { background: var(--warn-dim); color: var(--warn); }
  .badge.closed { background: var(--surface-2); color: var(--muted); }
  .flash { background: var(--ok-dim); color: var(--ok); padding: 11px 16px; border-radius: 12px; margin-bottom: 12px; font-size: 14px; font-weight: 600; }
  .flash.error { background: var(--danger-dim); color: var(--danger); }
  .flex { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .pager { display: flex; gap: 8px; margin: 14px 0; flex-wrap: wrap; }
  .chips-row { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
  .pill { padding: 6px 14px; border-radius: 999px; border: 1px solid var(--border); background: var(--surface); color: var(--ink); text-decoration: none; font-size: 13px; font-weight: 600; }
  .pill.active { background: var(--brand); color: var(--brand-ink); border-color: var(--brand); }
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

  /* ---------- ورود ---------- */
  .login-wrap { min-height: 100vh; background: var(--side); display: flex; flex-direction: column; align-items: center; justify-content: flex-end; padding: 0 16px 40px; }
  .sunrise { width: min(420px, 100%); height: auto; margin-bottom: -1px; }
  .sun { animation: rise 1.6s cubic-bezier(.2,.8,.2,1) both; }
  @keyframes rise { from { transform: translateY(70px); } to { transform: translateY(0); } }
  .login-box { background: var(--surface); border-radius: 20px; padding: 26px 24px 24px; width: 100%; max-width: 390px; }
  .login-box h2 { margin: 0 0 8px; font-size: 24px; text-align: center; }
  @media (prefers-reduced-motion: reduce) { .sun { animation: none; } html { scroll-behavior: auto; } }
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
    "more": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5M21 12H9"/>',
}


def icon(name):
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>')


NAV = [
    ("نمای کلی", [("dashboard", "داشبورد", "dashboard")]),
    ("مشتریان", [("users", "کاربران", "users"), ("tickets", "تیکت‌ها", "tickets"), ("resellers", "فروشنده‌ها", "resellers_page")]),
    ("فروش", [("discounts", "کدهای تخفیف", "discount_codes"), ("topups", "شارژهای کیف پول", "topups_page"),
              ("broadcast", "پیام همگانی", "broadcast")]),
    ("ربات", [("settings", "تنظیمات ربات", "settings_page"), ("texts", "متن‌های ربات", "texts_page"),
              ("appearance", "دکمه‌ها و ظاهر", "appearance_page")]),
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
        <div class="page-head"><h2 class="page-title">{title}</h2><div class="flex">{actions}</div></div>
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
  <svg class="sunrise" viewBox="0 0 320 130" aria-hidden="true">
    <defs><clipPath id="sky"><rect x="0" y="0" width="320" height="120"/></clipPath></defs>
    <g clip-path="url(#sky)"><circle class="sun" cx="160" cy="120" r="70" fill="#ffb324"/></g>
    <line x1="0" y1="120" x2="320" y2="120" stroke="#26345c" stroke-width="3"/>
  </svg>
  <form method="post" class="login-box">
    <h2>ورود به پنل مدیریت</h2>
    __ERROR__
    <label for="username">نام کاربری</label>
    <input id="username" type="text" name="username" autocapitalize="off" autocorrect="off" spellcheck="false" autocomplete="username" required>
    <label for="password">رمز عبور</label>
    <input id="password" type="password" name="password" autocapitalize="off" autocorrect="off" spellcheck="false" autocomplete="current-password" required>
    <div style="margin-top:20px;"><button type="submit" class="block">ورود</button></div>
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
    if INSECURE_DEFAULTS:
        warn = ('<div class="alert">⚠️ هنوز رمز پیش‌فرض پنل (<code>PANEL_PASSWORD</code>) یا کلید نشست (<code>SECRET_KEY</code>) '
                'رو تو Environment عوض نکردید. حتماً مقدار امن بذارید.</div>')
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
    offset = max(0, to_int(request.args.get("offset"), 0))
    total = get_users_count(search or None, only_recent)
    rows = get_users_page(offset=offset, search=search or None, sort=sort, only_recent=only_recent)

    rows_html = ""
    for user_id, username, first_name, wallet, joined_at, last_active, last_action in rows:
        state = activity_state(last_active)
        rows_html += f"""
        <tr>
          <td data-label="کاربر" class="wrap">{user_display(first_name, username, user_id)}<br><small class="muted num">{user_id}</small></td>
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
          <td data-label=""><a class="btn secondary sm" href="{url_for('user_detail', user_id=user_id)}">مشاهده</a></td>
        </tr>"""

    def link(**kw):
        params = {"q": search, "sort": sort, "recent": "1" if only_recent else ""}
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

    content = f"""
    <div class="card">
      <form method="get" class="flex">
        <input type="hidden" name="sort" value="{esc(sort)}">
        {'<input type="hidden" name="recent" value="1">' if only_recent else ''}
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
    <p><small class="muted num">{total:,} کاربر{' (با فیلتر فعلی)' if (search or only_recent) else ' ثبت‌شده'}</small></p>
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


# ---------- شارژهای کیف پول (فقط مشاهده) ----------

@app.route("/topups")
@login_required
def topups_page():
    rows = get_topups()
    rows_html = ""
    for rid, user_id, amount, status, created_at in rows:
        rows_html += f"""
        <tr>
          <td data-label="شماره">#{rid}</td>
          <td data-label="کاربر"><a class="num" href="{url_for('user_detail', user_id=user_id)}">{user_id}</a></td>
          <td data-label="مبلغ" class="num">{int(amount or 0):,} تومان</td>
          <td data-label="وضعیت"><span class="badge {esc(status)}">{esc({'pending': 'در انتظار', 'approved': 'تایید شده', 'rejected': 'رد شده'}.get(status, status))}</span></td>
          <td data-label="تاریخ"><small class="muted">{fmt_dt(created_at)}</small></td>
        </tr>"""
    content = f"""
    <table class="rt">
      <thead><tr><th>شماره</th><th>کاربر</th><th>مبلغ واریزی</th><th>وضعیت</th><th>تاریخ</th></tr></thead>
      <tbody>{rows_html if rows_html else '<tr><td colspan="5">درخواستی ثبت نشده.</td></tr>'}</tbody>
    </table>
    <p><small class="muted">تایید یا رد رسیدها همچنان از طریق پیام ادمین داخل خود ربات انجام می‌شود (دکمه‌های تایید/رد)؛ این صفحه فقط برای مشاهده‌ی تاریخچه است.</small></p>"""
    return render_page("شارژهای کیف پول", "topups", content)


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
          <div><span>آیدی عددی ادمین فعلی</span><b class="num">{esc(all_settings.get('admin_id', os.getenv('ADMIN_ID', '48198481')))}</b></div>
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
          <button type="submit" class="{'danger' if maint_on else ''}">{'خاموش کن' if maint_on else 'روشن کن'}</button>
        </form>
      </div>
      <div><span class="badge {'off' if maint_on else 'on'}">{'ربات در حالت تعمیر است' if maint_on else 'ربات عادی کار می‌کند'}</span></div>
    </div>"""

    chips, groups_html = "", ""
    for idx, (title, items) in enumerate(CONFIG_GROUPS):
        rows = ""
        for key, label, default, kind in items:
            value = all_settings.get(key, default)
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
        badge = '<span class="badge on">روشن</span>' if enabled else '<span class="badge off">خاموش</span>'
        rows_html += f"""
        <div class="switch-row"><div><b>{label}</b> {badge}</div>
          <form method="post" action="{url_for('toggle_setting', key=key)}">
            <button type="submit" class="{'danger' if enabled else ''} sm">{'خاموش کن' if enabled else 'روشن کن'}</button>
          </form></div>"""

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

@app.route("/resellers")
@login_required
def resellers_page():
    rows = get_all_resellers()
    rows_html = ""
    for user_id, login_name, has_pw, gb_balance, price_per_gb, status, revenue, configs_count, tg_user, tg_name in rows:
        badge = '<span class="badge on">فعال</span>' if status == "active" else '<span class="badge off">مسدود</span>'
        login_cell = f'<code>{esc(login_name)}</code>' if login_name else '<span class="badge open">تعیین نشده</span>'
        pw_cell = '<span class="badge on">تنظیم شده</span>' if has_pw else '<span class="badge open">تنظیم نشده</span>'
        rows_html += f"""
        <tr>
          <td data-label="فروشنده" class="wrap">{user_display(tg_name, tg_user, user_id)}<br><small class="muted num">{user_id}</small></td>
          <td data-label="نام کاربری ورود">{login_cell}</td>
          <td data-label="رمز عبور">{pw_cell}</td>
          <td data-label="استخر باقیمانده" class="num">{float(gb_balance or 0):g} گیگ</td>
          <td data-label="قیمت هر گیگ" class="num">{int(price_per_gb or 0):,}</td>
          <td data-label="درآمد" class="num">{int(revenue or 0):,}</td>
          <td data-label="کانفیگ فعال" class="num">{configs_count}</td>
          <td data-label="وضعیت">{badge}</td>
          <td data-label="عملیات">
            <div class="flex">
              <form method="post" action="{url_for('reseller_price', user_id=user_id)}" class="flex">
                <input type="hidden" name="next" value="list">
                <input type="number" name="price_per_gb" value="{int(price_per_gb or 0)}" min="1" style="width:100px;" required>
                <button type="submit" class="secondary sm">ذخیره</button>
              </form>
              <form method="post" action="{url_for('reseller_toggle', user_id=user_id)}">
                <input type="hidden" name="next" value="list">
                <button type="submit" class="{'danger' if status == 'active' else ''} sm">{'مسدود کن' if status == 'active' else 'فعال کن'}</button>
              </form>
              <a class="btn secondary sm" href="{url_for('reseller_detail', user_id=user_id)}">جزئیات / ورود</a>
            </div></td>
        </tr>"""
    content = f"""
    <div class="card"><small class="muted">فروشنده‌ها دیگه با «کلید API» وارد پنل فروشندگان نمی‌شن؛ با <b>نام کاربری و رمز عبور</b> وارد می‌شن
    که خودشون از داخل ربات می‌سازن. از صفحه‌ی «مدیریت» هر فروشنده می‌تونید نام کاربری و رمزش رو عوض (ریست) کنید.</small></div>
    <table class="rt">
      <thead><tr><th>فروشنده</th><th>نام کاربری ورود</th><th>رمز عبور</th><th>استخر</th><th>قیمت هر گیگ</th><th>درآمد (تومان)</th><th>کانفیگ فعال</th><th>وضعیت</th><th>عملیات</th></tr></thead>
      <tbody>{rows_html if rows_html else '<tr><td colspan="9">هنوز فروشنده‌ای فعال نشده.</td></tr>'}</tbody>
    </table>"""
    return render_page("فروشنده‌ها", "resellers", content)


@app.route("/resellers/<int:user_id>")
@login_required
def reseller_detail(user_id):
    r = get_reseller(user_id)
    if not r:
        flash("⚠️ فروشنده پیدا نشد.")
        return redirect(url_for("resellers_page"))
    _uid, login_name, has_pw, gb_balance, price_per_gb, status, revenue, configs_count, tg_user, tg_name = r
    created = get_reseller_created(user_id)
    configs = get_reseller_configs(user_id)
    keys = get_reseller_api_keys(user_id)

    cfg_rows = ""
    for label, ctype, gb, days, active, created_at, source, config_id in configs:
        badge = '<span class="badge on">فعال</span>' if active else '<span class="badge off">حذف‌شده</span>'
        src = "🛠 از تو بات" if source == "bot" else "🔌 از طریق API"
        cfg_rows += f"""
        <tr><td data-label="لیبل">{esc(label)}</td><td data-label="نوع">{esc(ctype)}</td>
        <td data-label="حجم" class="num">{float(gb or 0):g} گیگ</td><td data-label="مدت" class="num">{days} روز</td>
        <td data-label="منبع">{src}</td><td data-label="تاریخ ساخت"><small class="muted">{fmt_dt(created_at)}</small></td>
        <td data-label="وضعیت">{badge}</td></tr>"""

    key_rows = ""
    for kid, kname, prefix, kcreated, klast, krevoked in keys:
        state = '<span class="badge off">ابطال‌شده</span>' if krevoked else '<span class="badge on">فعال</span>'
        action = "" if krevoked else f"""
            <form method="post" action="{url_for('reseller_revoke_key', user_id=user_id, key_id=kid)}" onsubmit="return confirm('این کلید API ابطال بشه؟');">
              <button type="submit" class="danger sm">ابطال</button></form>"""
        key_rows += f"""
        <tr><td data-label="نام">{esc(kname or '-')}</td><td data-label="کلید"><code>{esc(prefix)}…</code></td>
        <td data-label="ساخت"><small class="muted">{fmt_dt(kcreated, with_time=False)}</small></td>
        <td data-label="آخرین استفاده"><small class="muted">{fmt_dt(klast) if klast else '—'}</small></td>
        <td data-label="وضعیت">{state}</td><td data-label="">{action}</td></tr>"""

    content = f"""
    <p><a class="btn secondary sm" href="{url_for('resellers_page')}">‹ بازگشت به فروشنده‌ها</a></p>
    <div class="card"><div class="kv">
      <div><span>فروشنده</span><b>{user_display(tg_name, tg_user, user_id)}</b></div>
      <div><span>آیدی عددی</span><b class="num">{user_id}</b></div>
      <div><span>وضعیت</span><b>{'<span class="badge on">فعال</span>' if status == 'active' else '<span class="badge off">مسدود</span>'}</b></div>
      <div><span>استخر باقیمانده</span><b class="num">{float(gb_balance or 0):g} گیگ</b></div>
      <div><span>درآمد از فروشندگی</span><b class="num">{int(revenue or 0):,} تومان</b></div>
      <div><span>کانفیگ فعال</span><b class="num">{configs_count}</b></div>
      <div><span>تاریخ فعال‌سازی</span><b>{fmt_dt(created)}</b></div>
    </div></div>

    <div class="card">
      <h3>🔐 اطلاعات ورود به پنل فروشندگان</h3>
      <div class="kv" style="margin-bottom:6px;">
        <div><span>نام کاربری فعلی</span><b>{f'<code>{esc(login_name)}</code>' if login_name else '— تعیین نشده —'}</b></div>
        <div><span>رمز عبور</span><b>{'تنظیم شده (به‌صورت هش ذخیره می‌شه و قابل نمایش نیست)' if has_pw else 'هنوز تنظیم نشده'}</b></div>
      </div>
      <form method="post" action="{url_for('reseller_credentials', user_id=user_id)}" autocomplete="off">
        <label for="new_username">نام کاربری جدید (اختیاری — حرف انگلیسی، عدد، _ و نقطه؛ ۳ تا ۲۰ کاراکتر)</label>
        <input id="new_username" type="text" name="username" dir="ltr" autocapitalize="off" spellcheck="false" placeholder="{esc(login_name or 'مثلاً ali_shop')}">
        <label for="new_password">رمز عبور جدید (اختیاری — {RESELLER_PASSWORD_MIN} تا {RESELLER_PASSWORD_MAX} کاراکتر)</label>
        <div class="flex"><input id="new_password" type="password" name="password" dir="ltr" autocomplete="new-password" style="flex:1;min-width:180px;">
          <button type="button" class="secondary" onclick="genPw('new_password')">🎲 ساخت رمز تصادفی</button></div>
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer;margin-top:14px;">
          <input type="checkbox" name="notify" value="1"> <span>اطلاعات جدید رو توی ربات برای خود فروشنده هم بفرست (رمز به‌صورت متن ساده تو چت می‌ره)</span></label>
        <div style="margin-top:14px;"><button type="submit">💾 ذخیره‌ی اطلاعات ورود</button></div>
      </form>
    </div>

    <div class="grid cols-2">
      <div class="card"><h3>قیمت هر گیگ فروشنده</h3>
        <form method="post" action="{url_for('reseller_price', user_id=user_id)}" class="flex">
          <input type="number" name="price_per_gb" value="{int(price_per_gb or 0)}" min="1" style="flex:1;min-width:120px;" required>
          <button type="submit">ذخیره</button></form></div>
      <div class="card"><h3>تغییر استخر گیگ</h3>
        <form method="post" action="{url_for('reseller_pool', user_id=user_id)}" class="flex">
          <input type="text" name="delta" inputmode="decimal" placeholder="مثلاً 20 یا -5 (گیگ)" style="flex:1;min-width:120px;" required>
          <button type="submit">اعمال</button></form></div>
    </div>
    <div class="card"><h3>وضعیت حساب</h3>
      <form method="post" action="{url_for('reseller_toggle', user_id=user_id)}" class="flex">
        <button type="submit" class="{'danger' if status == 'active' else ''}">{'⛔ مسدود کردن فروشنده' if status == 'active' else '✅ فعال کردن فروشنده'}</button>
        <small class="muted">فروشنده‌ی مسدود نمی‌تونه وارد پنل بشه یا کانفیگ بسازه.</small></form></div>

    <h3>کلیدهای API برنامه‌نویسی</h3>
    <p class="muted" style="margin-top:-6px;font-size:12.5px;">این‌ها جدا از ورود به پنل هستن؛ فروشنده خودش از پنل فروشندگان می‌سازه و فقط پیشوند اون‌ها نمایش داده می‌شه.</p>
    <table class="rt"><thead><tr><th>نام</th><th>کلید</th><th>ساخت</th><th>آخرین استفاده</th><th>وضعیت</th><th></th></tr></thead>
      <tbody>{key_rows if key_rows else '<tr><td colspan="6">این فروشنده کلید API نساخته.</td></tr>'}</tbody></table>

    <h3>کانفیگ‌های ساخته‌شده</h3>
    <table class="rt"><thead><tr><th>لیبل</th><th>نوع</th><th>حجم</th><th>مدت</th><th>منبع</th><th>تاریخ ساخت</th><th>وضعیت</th></tr></thead>
      <tbody>{cfg_rows if cfg_rows else '<tr><td colspan="7">این فروشنده هنوز کانفیگی نساخته.</td></tr>'}</tbody></table>
    """
    return render_page(f"فروشنده {user_id}", "resellers", content)


@app.route("/resellers/<int:user_id>/credentials", methods=["POST"])
@login_required
def reseller_credentials(user_id):
    back = redirect(url_for("reseller_detail", user_id=user_id))
    r = get_reseller(user_id)
    if not r:
        flash("⚠️ فروشنده پیدا نشد.")
        return redirect(url_for("resellers_page"))
    current_username = r[1]
    new_username = request.form.get("username", "").strip().lower()
    new_password = request.form.get("password", "")
    if not new_username and not new_password:
        flash("⚠️ چیزی برای ذخیره وارد نکردید.")
        return back
    if new_username:
        if not RESELLER_USERNAME_RE.match(new_username):
            flash("⚠️ نام کاربری معتبر نیست (فقط حرف انگلیسی، عدد، _ و نقطه؛ ۳ تا ۲۰ کاراکتر).")
            return back
        if reseller_username_taken(new_username, user_id):
            flash("⚠️ این نام کاربری قبلاً برای فروشنده‌ی دیگه‌ای ثبت شده.")
            return back
    if new_password and not (RESELLER_PASSWORD_MIN <= len(new_password) <= RESELLER_PASSWORD_MAX):
        flash(f"⚠️ رمز باید بین {RESELLER_PASSWORD_MIN} تا {RESELLER_PASSWORD_MAX} کاراکتر باشه.")
        return back
    if new_password and not (new_username or current_username):
        flash("⚠️ این فروشنده هنوز نام کاربری نداره؛ همراه رمز یه نام کاربری هم وارد کنید.")
        return back
    set_reseller_login(user_id, username=new_username or None,
                       password_hash=hash_reseller_password(new_password) if new_password else None)
    done = []
    if new_username:
        done.append("نام کاربری")
    if new_password:
        done.append("رمز عبور")
    flash(" و ".join(done) + " فروشنده‌ی " + str(user_id) + " ذخیره شد.")
    if request.form.get("notify") == "1":
        lines = ["🔐 <b>اطلاعات ورود شما به پنل فروشندگان بروزرسانی شد:</b>", ""]
        lines.append(f"👤 نام کاربری: <code>{esc(new_username or current_username)}</code>")
        if new_password:
            lines.append(f"🔑 رمز عبور: <code>{esc(new_password)}</code>")
        lines.append("\nبعد از ورود، رمز رو تو جای امن نگه دارید.")
        flash("پیام اطلاعات ورود برای فروشنده ارسال شد." if send_telegram_message(user_id, "\n".join(lines))
              else "⚠️ اطلاعات ذخیره شد ولی ارسال پیام به فروشنده ناموفق بود.")
    return back


@app.route("/resellers/<int:user_id>/toggle", methods=["POST"])
@login_required
def reseller_toggle(user_id):
    toggle_reseller_status(user_id)
    flash(f"وضعیت فروشنده {user_id} تغییر کرد.")
    if request.form.get("next") == "list":
        return redirect(url_for("resellers_page"))
    return redirect(url_for("reseller_detail", user_id=user_id))


@app.route("/resellers/<int:user_id>/price", methods=["POST"])
@login_required
def reseller_price(user_id):
    price = to_int(request.form.get("price_per_gb"))
    if price is None or price <= 0:
        flash("⚠️ قیمت هر گیگ باید عدد صحیح مثبت باشد.")
    else:
        update_reseller_price(user_id, price)
        flash(f"قیمت هر گیگ فروشنده {user_id} به {price:,} تومان تغییر کرد.")
    if request.form.get("next") == "list":
        return redirect(url_for("resellers_page"))
    return redirect(url_for("reseller_detail", user_id=user_id))


@app.route("/resellers/<int:user_id>/pool", methods=["POST"])
@login_required
def reseller_pool(user_id):
    try:
        delta = float(request.form.get("delta", "").replace(",", ".").strip())
    except ValueError:
        flash("⚠️ مقدار گیگ باید عدد باشه (مثلاً 20 یا -5).")
        return redirect(url_for("reseller_detail", user_id=user_id))
    if delta == 0 or abs(delta) > 100000:
        flash("⚠️ مقدار نامعتبره.")
    else:
        add_reseller_gb(user_id, delta)
        flash(f"استخر فروشنده {user_id} به اندازه‌ی {delta:+g} گیگ تغییر کرد.")
    return redirect(url_for("reseller_detail", user_id=user_id))


@app.route("/resellers/<int:user_id>/keys/<key_id>/revoke", methods=["POST"])
@login_required
def reseller_revoke_key(user_id, key_id):
    revoke_reseller_api_key(user_id, key_id)
    flash("کلید API ابطال شد.")
    return redirect(url_for("reseller_detail", user_id=user_id))


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
    var ta = btn.closest('.txt').querySelector('textarea');
    var ph = btn.getAttribute('data-ph');
    var s = ta.selectionStart || 0, e = ta.selectionEnd || 0;
    ta.value = ta.value.slice(0, s) + ph + ta.value.slice(e);
    ta.focus(); ta.selectionStart = ta.selectionEnd = s + ph.length;
  }
  function resetTxt(btn) {
    var box = btn.closest('.txt');
    box.querySelector('textarea').value = box.getAttribute('data-default');
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


@app.route("/texts")
@login_required
def texts_page():
    lang = "en" if request.args.get("lang") == "en" else "fa"
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
            chips = "".join(
                f'<button type="button" class="chip" data-ph="{{{esc(p)}}}" onclick="insertAt(this)">{{{esc(p)}}}</button>'
                for p in it.get("p", [])
            )
            chips_html = f'<div class="chips">{chips}</div>' if chips else ""
            ref = it.get("ref", "")
            ref_html = f'<div class="ref">متن فارسی (مرجع):\n{esc(ref)}</div>' if (ref and not default) else ""
            ph_attr = f' placeholder="{esc(ref)}"' if (ref and not default) else ""
            badge = '<span class="badge on">سفارشی</span>' if overridden else ""
            search = esc((key + " " + default + " " + value + " " + ref).lower())
            boxes += f"""
            <div class="txt" data-default="{esc(default)}" data-search="{search}">
              <label>{badge}<code class="key">{esc(key)}</code></label>
              {chips_html}
              <textarea name="t__{esc(setting)}" rows="{rows}"{ph_attr}>{esc(value)}</textarea>
              {ref_html}
              <div class="txt-actions"><button type="button" class="secondary" onclick="resetTxt(this)">↩ پیش‌فرض</button></div>
            </div>"""
        groups_html += f'<details class="grp"><summary><span>{g}</span><small>{len(by_group[g])} متن</small></summary>{boxes}</details>'

    tab_fa = "btn" if lang == "fa" else "btn secondary"
    tab_en = "btn" if lang == "en" else "btn secondary"
    note_en = ("<p class='muted' style='font-size:12.5px;'>متن‌هایی که ترجمه‌ی انگلیسی ندارن (کادرشون خالیه) فعلاً برای کاربران انگلیسی‌زبان "
               "به‌صورت فارسی نمایش داده می‌شن؛ اگه ترجمه‌شون رو بنویسید جایگزین می‌شه.</p>") if lang == "en" else ""

    content = f"""
    {TEXTS_CSS_JS}
    <div class="panel">
      <div class="flex" style="margin-bottom:12px;">
        <a class="{tab_fa}" href="{url_for('texts_page', lang='fa')}">🇮🇷 فارسی</a>
        <a class="{tab_en}" href="{url_for('texts_page', lang='en')}">🇬🇧 English</a>
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
      {groups_html}
      <div class="savebar"><button type="submit" class="block">💾 ذخیره‌ی تغییرات ({'فارسی' if lang == 'fa' else 'English'})</button></div>
    </form>
    <p><small class="muted">دکمه‌های اصلی منو، نام نوع سرویس‌های فارسی و ترتیبشان در صفحه‌ی «متن‌ها و ظاهر ربات» هستند.</small></p>
    """
    return render_page("همه‌ی متن‌های ربات", "texts", content)


@app.route("/texts/save", methods=["POST"])
@login_required
def texts_save():
    lang = "en" if request.form.get("lang") == "en" else "fa"
    registry = load_text_registry()
    if not registry:
        flash("⚠️ لیست متن‌ها از ربات دریافت نشده؛ ربات را ری‌استارت کنید.")
        return redirect(url_for("texts_page", lang=lang))

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
    return redirect(url_for("texts_page", lang=lang))


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




if __name__ == "__main__":
    try:
        ensure_schema()
    except Exception as e:
        print("⚠️ ensure_schema:", e)
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
