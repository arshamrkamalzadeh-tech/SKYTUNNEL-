import os
import re
import json
import string
import html as html_lib
import time
import threading
from datetime import datetime
from functools import wraps

import requests
import turso_serverless
from flask import Flask, request, session, redirect, url_for, render_template_string, flash

# ---------------------------------------------------------------------------
# تنظیمات (از Environment Variables می‌خونه، دقیقاً هم‌نام با bot.py)
# ---------------------------------------------------------------------------

TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN")

BOT_TOKEN = os.getenv("BOT_TOKEN", "69786607:p-AAjsil8xAOknphz-PxbDBsvFxFSWknCMg")
BASE_URL = "https://api.splus.ir/bot" + BOT_TOKEN

PANEL_USERNAME = os.getenv("PANEL_USERNAME", "admin")
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "change-me-please")

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
app.secret_key = os.getenv("SECRET_KEY", "sky-panel-secret-change-me")

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
def get_users_count(search=None):
    conn = get_conn()
    c = conn.cursor()
    if search:
        like = f"%{search}%"
        c.execute(
            "SELECT COUNT(*) FROM users WHERE CAST(user_id AS TEXT) LIKE ? OR username LIKE ? OR first_name LIKE ?",
            (like, like, like),
        )
    else:
        c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]
    conn.close()
    return total


@with_db_retry
def get_users_page(offset=0, limit=USERS_PAGE_SIZE, search=None):
    conn = get_conn()
    c = conn.cursor()
    if search:
        like = f"%{search}%"
        c.execute(
            """SELECT user_id, username, first_name, wallet FROM users
               WHERE CAST(user_id AS TEXT) LIKE ? OR username LIKE ? OR first_name LIKE ?
               ORDER BY user_id LIMIT ? OFFSET ?""",
            (like, like, like, limit, offset),
        )
    else:
        c.execute(
            "SELECT user_id, username, first_name, wallet FROM users ORDER BY user_id LIMIT ? OFFSET ?",
            (limit, offset),
        )
    res = c.fetchall()
    conn.close()
    return res


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
def get_all_resellers():
    """هر ردیف: (user_id, api_key, gb_balance, price_per_gb, status, revenue, configs_count)."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT r.user_id, r.api_key, r.gb_balance, r.price_per_gb, r.status,
               COALESCE((SELECT SUM(price) FROM reseller_pool_log WHERE user_id = r.user_id), 0) AS revenue,
               COALESCE((SELECT COUNT(*) FROM reseller_api_configs WHERE reseller_id = r.user_id AND active = 1), 0) AS configs_count
        FROM resellers r
        ORDER BY r.created_at DESC
    """)
    res = c.fetchall()
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
def get_reseller_configs(reseller_id, limit=100):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT label, type, gb, days, active, created_at, source, config_id "
              "FROM reseller_api_configs WHERE reseller_id=? ORDER BY id DESC LIMIT ?", (reseller_id, limit))
    res = c.fetchall()
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
# ارسال پیام به کاربران (همون API که bot.py استفاده می‌کنه)
# ---------------------------------------------------------------------------

def send_telegram_message(chat_id, text):
    if not BOT_TOKEN:
        return False
    try:
        res = SESSION.post(
            BASE_URL + "/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
        return res.json().get("ok", False)
    except Exception:
        return False


def broadcast_worker(text, user_ids):
    sent, failed = 0, 0
    for uid in user_ids:
        ok = send_telegram_message(uid, text)
        if ok:
            sent += 1
        else:
            failed += 1
        time.sleep(0.05)
    print(f"📣 پیام همگانی تمام شد: {sent} موفق، {failed} ناموفق")


# ---------------------------------------------------------------------------
# احراز هویت ساده
# ---------------------------------------------------------------------------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------------
# قالب پایه (RTL، تم تیره)
# ---------------------------------------------------------------------------

BASE_HTML = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#13203a">
<title>پنل مدیریت SkyTunnel</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Lalezar&family=Vazirmatn:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  /* افق: آبی سرمه‌ای شب، آسمان روز، و یک خورشید کهربایی فقط برای نکته‌های مهم */
  :root {
    --ink: #13203a;
    --ink-2: #22335a;
    --bg: #edf1f7;
    --surface: #ffffff;
    --surface-2: #f4f6fb;
    --border: #d9e0ec;
    --muted: #5d6b85;
    --accent: #2f5bff;
    --accent-ink: #ffffff;
    --accent-dim: rgba(47,91,255,0.10);
    --sun: #ffb324;
    --ok: #12805c;
    --ok-dim: rgba(18,128,92,0.12);
    --warn: #8a5300;
    --warn-dim: rgba(255,179,36,0.24);
    --danger: #c73a3a;
    --danger-dim: rgba(199,58,58,0.10);
    --display: 'Lalezar', 'Vazirmatn', Tahoma, sans-serif;
  }
  * { box-sizing: border-box; }
  html { scroll-behavior: smooth; }
  body {
    margin: 0; font-family: 'Vazirmatn', Tahoma, sans-serif; font-size: 14.5px; line-height: 1.75;
    background: var(--bg); color: var(--ink);
  }
  :focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
  a { color: var(--accent); }

  /* ---------- نوار بالا (افق) ---------- */
  .topbar-wrap { background: var(--ink); border-bottom: 3px solid var(--sun); padding-top: env(safe-area-inset-top, 0px); }
  .topbar { max-width: 720px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between; padding: 14px 18px; }
  .brand { display: flex; align-items: center; gap: 12px; }
  .mark { width: 34px; height: 34px; border-radius: 50%; background: var(--sun); position: relative; overflow: hidden; flex-shrink: 0; }
  .mark::after { content: ''; position: absolute; left: 0; right: 0; bottom: 0; height: 42%; background: var(--ink); border-top: 2px solid var(--ink-2); }
  .topbar h1 { font-family: var(--display); font-weight: 400; font-size: 24px; margin: 0; color: #fff; line-height: 1.2; letter-spacing: .3px; }
  .topbar .sub { font-size: 12px; color: #a9b7d6; display: flex; align-items: center; gap: 6px; }
  .status-dot { width: 7px; height: 7px; border-radius: 50%; background: #3ddc97; }
  .icon-btn { width: 38px; height: 38px; border-radius: 10px; border: 1px solid var(--ink-2); display: flex; align-items: center; justify-content: center; text-decoration: none; color: #cfd9ef; font-size: 16px; }
  .icon-btn:hover { background: var(--ink-2); }

  /* ---------- محتوا ---------- */
  .app { max-width: 720px; margin: 0 auto; padding: 0 16px 110px; }
  .content { padding-top: 20px; }
  .page-title { font-family: var(--display); font-weight: 400; font-size: 30px; line-height: 1.3; margin: 0 0 16px; }
  h3 { font-family: var(--display); font-weight: 400; font-size: 20px; margin: 26px 0 8px; }
  h4 { font-size: 14px; margin: 18px 0 6px; }
  .panel { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 16px 18px; margin-bottom: 16px; }
  .panel > h3:first-child { margin-top: 0; }

  /* ---------- داشبورد ---------- */
  .hero { background: var(--ink); color: #fff; border-radius: 20px; padding: 22px 22px 18px; margin-bottom: 16px; position: relative; overflow: hidden; }
  .hero::after { content: ''; position: absolute; left: -46px; bottom: -70px; width: 170px; height: 170px; border-radius: 50%; background: var(--sun); opacity: .95; }
  .hero > * { position: relative; z-index: 1; }
  .hero-label { font-size: 13px; color: #a9b7d6; }
  .hero-number { font-family: var(--display); font-size: 52px; line-height: 1.15; margin: 2px 0 14px; }
  .hero-unit { font-size: 18px; margin-right: 8px; color: #a9b7d6; font-family: 'Vazirmatn', sans-serif; }
  .hero-meta { display: flex; gap: 22px; flex-wrap: wrap; padding-top: 14px; border-top: 1px solid var(--ink-2); }
  .hero-meta div { display: flex; flex-direction: column; }
  .hero-meta b { font-size: 19px; font-weight: 700; }
  .hero-meta span { font-size: 12px; color: #a9b7d6; }
  .ledger-row { display: flex; justify-content: space-between; gap: 12px; padding: 11px 0; border-bottom: 1px dashed var(--border); }
  .ledger-row:last-child { border-bottom: none; }
  .ledger-row span { color: var(--muted); }
  .ledger-row b { font-weight: 700; }
  .row-link { display: flex; align-items: center; gap: 12px; padding: 12px 0; text-decoration: none; color: var(--ink); border-bottom: 1px solid var(--border); }
  .row-link:last-child { border-bottom: none; }
  .row-main { flex: 1; display: flex; flex-direction: column; }
  .row-main small { color: var(--muted); font-size: 12.5px; }
  .chev { color: var(--muted); font-size: 22px; }
  .icon-badge { width: 36px; height: 36px; border-radius: 10px; background: var(--warn-dim); display: flex; align-items: center; justify-content: center; font-size: 16px; flex-shrink: 0; }
  .empty-note { color: var(--muted); margin: 4px 0 0; }

  /* ---------- جدول‌ها ---------- */
  table { display: block; max-width: 100%; overflow-x: auto; border-collapse: collapse; background: var(--surface); border-radius: 14px; border: 1px solid var(--border); margin-bottom: 14px; }
  th, td { padding: 11px 14px; text-align: right; border-bottom: 1px solid var(--border); font-size: 13.5px; white-space: nowrap; }
  th { background: var(--surface-2); color: var(--muted); font-weight: 600; font-size: 12.5px; }
  tr:last-child td { border-bottom: none; }
  tbody tr:hover td { background: var(--surface-2); }

  /* ---------- فرم‌ها ---------- */
  input[type=text], input[type=number], input[type=password], textarea, select {
    background: var(--surface); border: 1.5px solid var(--border); color: var(--ink);
    border-radius: 10px; padding: 11px 14px; font-size: 14.5px; width: 100%; font-family: inherit;
  }
  input:focus, textarea:focus, select:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-dim); }
  textarea { min-height: 100px; resize: vertical; }
  label { display: block; margin: 14px 0 6px; font-size: 13px; color: var(--muted); font-weight: 600; }
  input[type=radio] { width: auto; accent-color: var(--accent); }

  .reorder-list { margin-bottom: 4px; }
  .reorder-row { display: flex; align-items: flex-end; gap: 8px; }
  .reorder-row > div:first-child { flex: 1; min-width: 0; }
  .reorder-row label { margin-top: 0; }
  .reorder-arrows { display: flex; flex-direction: column; gap: 4px; margin-bottom: 1px; }
  .reorder-arrows button { padding: 5px 11px; font-size: 11px; line-height: 1.4; }

  button, .btn {
    background: var(--accent); color: var(--accent-ink); border: 1.5px solid var(--accent); border-radius: 10px;
    padding: 10px 18px; font-size: 14px; font-weight: 700; cursor: pointer; font-family: inherit;
    text-decoration: none; display: inline-block;
  }
  button:hover, .btn:hover { filter: brightness(1.08); }
  button.secondary, .btn.secondary { background: transparent; color: var(--ink); border-color: var(--border); }
  button.secondary:hover, .btn.secondary:hover { background: var(--surface-2); filter: none; }
  button.danger, .btn.danger { background: transparent; color: var(--danger); border-color: var(--danger-dim); }
  button.danger:hover, .btn.danger:hover { background: var(--danger-dim); filter: none; }
  .btn.block, button.block { width: 100%; text-align: center; }

  .badge { padding: 3px 11px; border-radius: 6px; font-size: 12px; font-weight: 700; display: inline-block; }
  .badge.on, .badge.answered { background: var(--ok-dim); color: var(--ok); }
  .badge.off { background: var(--danger-dim); color: var(--danger); }
  .badge.open { background: var(--warn-dim); color: var(--warn); }
  .badge.closed { background: var(--surface-2); color: var(--muted); }

  .flash { background: var(--ok-dim); color: var(--ok); padding: 11px 16px; border-radius: 10px; margin-bottom: 14px; font-size: 14px; font-weight: 600; }
  .flash.error { background: var(--danger-dim); color: var(--danger); }
  .flex { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .pager { display: flex; gap: 8px; margin-top: 14px; }
  small.muted, .muted { color: var(--muted); }

  /* ---------- نوار پایین ---------- */
  .bottom-nav { position: fixed; bottom: 0; left: 0; right: 0; z-index: 40; background: var(--ink); padding-bottom: env(safe-area-inset-bottom, 0px); }
  .nav-inner { max-width: 720px; margin: 0 auto; display: flex; }
  .bottom-nav a { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 3px; padding: 10px 4px 9px; color: #a9b7d6; text-decoration: none; font-size: 11.5px; border-top: 3px solid transparent; }
  .bottom-nav a svg { width: 22px; height: 22px; }
  .bottom-nav a.active { color: #fff; font-weight: 700; border-top-color: var(--sun); }

  /* ---------- کشوی «بیشتر» ---------- */
  .drawer-overlay { display: none; position: fixed; inset: 0; background: rgba(19,32,58,0.55); z-index: 50; }
  .drawer-overlay:target { display: block; }
  .drawer { position: absolute; bottom: 0; left: 50%; transform: translateX(-50%); width: 100%; max-width: 720px; background: var(--surface); border-radius: 20px 20px 0 0; padding: 10px 20px 28px; max-height: 82vh; overflow-y: auto; }
  .drawer .handle { width: 38px; height: 4px; background: var(--border); border-radius: 4px; margin: 8px auto 14px; }
  .drawer h3 { font-family: 'Vazirmatn', sans-serif; font-size: 12.5px; font-weight: 700; margin: 18px 0 4px; color: var(--muted); }
  .drawer a.drawer-link { display: flex; align-items: center; gap: 10px; padding: 13px 2px; text-decoration: none; color: var(--ink); font-size: 15px; font-weight: 600; border-bottom: 1px solid var(--border); }
  .drawer a.close-drawer { color: var(--muted); text-decoration: none; font-size: 20px; padding: 4px 8px; }
  .drawer-top { display: flex; justify-content: space-between; align-items: center; }
  .drawer-top h2 { margin: 0; font-family: var(--display); font-weight: 400; font-size: 22px; }

  /* ---------- ورود: طلوع خورشید ---------- */
  .login-wrap { min-height: 100vh; background: var(--ink); display: flex; flex-direction: column; align-items: center; justify-content: flex-end; padding: 0 16px 40px; }
  .sunrise { width: min(420px, 100%); height: auto; margin-bottom: -1px; }
  .sun { animation: rise 1.6s cubic-bezier(.2,.8,.2,1) both; }
  @keyframes rise { from { transform: translateY(70px); } to { transform: translateY(0); } }
  .login-box { background: var(--surface); border-radius: 18px; padding: 26px 24px 24px; width: 100%; max-width: 380px; }
  .login-box h2 { margin: 0 0 8px; font-family: var(--display); font-weight: 400; font-size: 26px; text-align: center; }
  @media (prefers-reduced-motion: reduce) { .sun { animation: none; } html { scroll-behavior: auto; } }
</style>
</head>
<body>
{{ body|safe }}
</body>
</html>
"""

# لینک‌های بخش «بیشتر» (منوی کشویی از پایین) — دسته‌بندی‌شده مثل صفحاتی که
# مرجع طراحی بودن
DRAWER_LINKS = """
<div id="more" class="drawer-overlay">
  <div class="drawer">
    <div class="handle"></div>
    <div class="drawer-top">
      <h2>همه‌ی بخش‌ها</h2>
      <a href="#" class="close-drawer" aria-label="بستن">✕</a>
    </div>

    <h3>مدیریت ربات</h3>
    <a class="drawer-link" href="{{ url_for('settings_page') }}">🔌 تنظیمات ربات</a>
    <a class="drawer-link" href="{{ url_for('texts_page') }}">📝 همه‌ی متن‌های ربات</a>
    <a class="drawer-link" href="{{ url_for('appearance_page') }}">🎨 دکمه‌ها و ظاهر ربات</a>

    <h3>فروش</h3>
    <a class="drawer-link" href="{{ url_for('discount_codes') }}">🎟 کدهای تخفیف</a>
    <a class="drawer-link" href="{{ url_for('resellers_page') }}">🧑‍💼 فروشنده‌ها</a>
    <a class="drawer-link" href="{{ url_for('broadcast') }}">📣 پیام همگانی</a>

    <h3>حساب</h3>
    <a class="drawer-link" href="{{ url_for('logout') }}">🚪 خروج از پنل</a>
  </div>
</div>
"""

TOPBAR = """
<header class="topbar-wrap">
  <div class="topbar">
    <div class="brand">
      <div class="mark" aria-hidden="true"></div>
      <div>
        <h1>SkyTunnel</h1>
        <div class="sub"><span class="status-dot"></span>ربات متصل و فعال</div>
      </div>
    </div>
    <a href="{{ url_for('logout') }}" class="icon-btn" title="خروج" aria-label="خروج">⎋</a>
  </div>
</header>
"""

BOTTOM_NAV = """
<nav class="bottom-nav"><div class="nav-inner">
  <a href="{{ url_for('dashboard') }}" class="{{ 'active' if active=='dashboard' else '' }}">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></svg>داشبورد</a>
  <a href="{{ url_for('users') }}" class="{{ 'active' if active=='users' else '' }}">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-3.5 3.2-5.5 6.5-5.5s5.9 2 6.5 5.5"/><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14.7c2 .6 3.3 2.3 3.6 5.3"/></svg>کاربران</a>
  <a href="{{ url_for('tickets') }}" class="{{ 'active' if active=='tickets' else '' }}">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5h16v11H9l-5 4z"/></svg>تیکت‌ها</a>
  <a href="#more" class="{{ 'active' if active in ('settings','appearance','texts','discounts','broadcast','resellers') else '' }}">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg>بیشتر</a>
</div></nav>
"""


def render_page(title, active, content_html):
    flashes = "".join(f'<div class="flash">{esc(m)}</div>' for m in get_flashed())
    body = f"""
    <div class="shell">
      {render_template_string(TOPBAR)}
      <main class="app">
        <div class="content">
          <h2 class="page-title">{title}</h2>
          {flashes}
          {content_html}
        </div>
      </main>
      {render_template_string(BOTTOM_NAV, active=active)}
      {render_template_string(DRAWER_LINKS)}
    </div>
    """
    return render_template_string(BASE_HTML, body=body)


def get_flashed():
    from flask import get_flashed_messages
    return get_flashed_messages()


# ---------------------------------------------------------------------------
# صفحات
# ---------------------------------------------------------------------------

LOGIN_HTML = """
<div class="login-wrap">
  <svg class="sunrise" viewBox="0 0 320 130" aria-hidden="true">
    <defs><clipPath id="sky"><rect x="0" y="0" width="320" height="120"/></clipPath></defs>
    <g clip-path="url(#sky)"><circle class="sun" cx="160" cy="120" r="70" fill="#ffb324"/></g>
    <line x1="0" y1="120" x2="320" y2="120" stroke="#22335a" stroke-width="3"/>
  </svg>
  <form method="post" class="login-box">
    <h2>ورود به پنل</h2>
    {% if error %}<div class="flash error">{{ error }}</div>{% endif %}
    <label for="username">نام کاربری</label>
    <input id="username" type="text" name="username" autocapitalize="off" autocorrect="off" spellcheck="false" required>
    <label for="password">رمز عبور</label>
    <input id="password" type="password" name="password" autocapitalize="off" autocorrect="off" spellcheck="false" required>
    <div style="margin-top:20px;"><button type="submit" class="block">ورود</button></div>
  </form>
</div>
"""


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "").strip()
        if u == PANEL_USERNAME.strip() and p == PANEL_PASSWORD.strip():
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        error = "نام کاربری یا رمز عبور اشتباه است."
    return render_template_string(BASE_HTML, body=render_template_string(LOGIN_HTML, error=error))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    s = get_dashboard_stats()

    tickets_url = url_for("tickets")
    open_tickets = s["open_tickets"]
    pending_topups = s["pending_topups"]
    revenue = int(s["total_revenue"] or 0)
    configs_sold = int(s["total_configs"] or 0)
    avg_price = revenue // configs_sold if configs_sold else 0

    attention_html = ""
    if open_tickets > 0:
        attention_html += f"""
        <a href="{tickets_url}" class="row-link">
          <span class="icon-badge">🎧</span>
          <span class="row-main"><b>تیکت‌های پاسخ‌نداده</b><small>{open_tickets} تیکت در انتظار پاسخ</small></span>
          <span class="chev">‹</span>
        </a>"""
    if pending_topups > 0:
        attention_html += f"""
        <a href="{tickets_url}" class="row-link">
          <span class="icon-badge">💳</span>
          <span class="row-main"><b>شارژهای در انتظار تایید</b><small>{pending_topups} درخواست شارژ کیف پول</small></span>
          <span class="chev">‹</span>
        </a>"""
    if not attention_html:
        attention_html = '<p class="empty-note">چیزی برای رسیدگی فوری نیست.</p>'

    content = f"""
    <section class="hero">
      <div class="hero-label">درآمد کل فروش</div>
      <div class="hero-number">{revenue:,}<span class="hero-unit">تومان</span></div>
      <div class="hero-meta">
        <div><b>{s['total_users']:,}</b><span>کاربر</span></div>
        <div><b>{configs_sold:,}</b><span>کانفیگ فروخته‌شده</span></div>
        <div><b>{float(s['total_gb'] or 0):,.1f}</b><span>گیگ فروخته‌شده</span></div>
      </div>
    </section>

    <div class="panel">
      <div class="ledger-row"><span>مجموع کیف‌پول کاربران</span><b>{int(s['total_wallet'] or 0):,} تومان</b></div>
      <div class="ledger-row"><span>میانگین قیمت هر کانفیگ</span><b>{avg_price:,} تومان</b></div>
    </div>

    <div class="panel">
      <h3>نیاز به توجه</h3>
      {attention_html}
    </div>
    """
    return render_page("پیشخوان", "dashboard", content)


@app.route("/users")
@login_required
def users():
    search = request.args.get("q", "").strip()
    offset = int(request.args.get("offset", 0))
    total = get_users_count(search or None)
    rows = get_users_page(offset=offset, search=search or None)

    rows_html = ""
    for user_id, username, first_name, wallet in rows:
        handle = f"@{esc(username)}" if username else "-"
        name = esc(first_name) if first_name else "-"
        rows_html += f"""
        <tr>
          <td>{user_id}</td>
          <td>{handle}</td>
          <td>{name}</td>
          <td>{wallet:,} تومان</td>
          <td>
            <form method="post" action="{url_for('adjust_wallet')}" class="flex">
              <input type="hidden" name="user_id" value="{user_id}">
              <input type="number" name="amount" placeholder="مبلغ" style="width:110px;" required>
              <button type="submit" name="sign" value="1">➕</button>
              <button type="submit" name="sign" value="-1" class="secondary">➖</button>
            </form>
          </td>
        </tr>
        """

    pager = ""
    if offset > 0:
        pager += f'<a class="btn secondary" href="{url_for("users", q=search, offset=max(0, offset-USERS_PAGE_SIZE))}">صفحه قبل</a>'
    if offset + USERS_PAGE_SIZE < total:
        pager += f'<a class="btn secondary" href="{url_for("users", q=search, offset=offset+USERS_PAGE_SIZE)}">صفحه بعد</a>'

    content = f"""
    <div class="panel">
      <form method="get" class="flex">
        <input type="text" name="q" placeholder="جستجو با آیدی، یوزرنیم یا نام..." value="{esc(search)}">
        <button type="submit">جستجو</button>
      </form>
    </div>
    <table>
      <tr><th>آیدی</th><th>یوزرنیم</th><th>نام</th><th>موجودی</th><th>تغییر موجودی</th></tr>
      {rows_html if rows_html else '<tr><td colspan="5">کاربری یافت نشد.</td></tr>'}
    </table>
    <div class="pager">{pager}</div>
    <p><small class="muted">{total:,} کاربر ثبت‌شده</small></p>
    """
    return render_page("کاربران", "users", content)


@app.route("/users/wallet", methods=["POST"])
@login_required
def adjust_wallet():
    user_id = int(request.form["user_id"])
    amount = int(request.form["amount"])
    sign = int(request.form["sign"])
    if get_wallet(user_id) is None:
        flash("کاربر پیدا نشد.")
    else:
        update_wallet(user_id, amount * sign)
        flash(f"موجودی کاربر {user_id} به مقدار {amount:,} تومان {'افزایش' if sign > 0 else 'کاهش'} یافت.")
    return redirect(url_for("users"))


@app.route("/tickets")
@login_required
def tickets():
    status_filter = request.args.get("status", "open")
    rows = get_tickets(status_filter if status_filter != "all" else None)

    rows_html = ""
    for tid, user_id, message, status, admin_reply, created_at in rows:
        badge_class = status
        rows_html += f"""
        <tr>
          <td>#{tid}</td>
          <td>{user_id}</td>
          <td>{esc(message[:60])}{'...' if len(message) > 60 else ''}</td>
          <td><span class="badge {badge_class}">{status}</span></td>
          <td><a class="btn secondary" href="{url_for('ticket_detail', ticket_id=tid)}">مشاهده</a></td>
        </tr>
        """

    tabs = ""
    for key, label in [("open", "باز"), ("answered", "پاسخ‌داده‌شده"), ("closed", "بسته"), ("all", "همه")]:
        active = "btn" if status_filter == key else "btn secondary"
        tabs += f'<a class="{active}" href="{url_for("tickets", status=key)}">{label}</a> '

    content = f"""
    <div class="panel flex">{tabs}</div>
    <table>
      <tr><th>شماره</th><th>کاربر</th><th>پیام</th><th>وضعیت</th><th></th></tr>
      {rows_html if rows_html else '<tr><td colspan="5">تیکتی یافت نشد.</td></tr>'}
    </table>
    """
    return render_page("تیکت‌های پشتیبانی", "tickets", content)


@app.route("/tickets/<int:ticket_id>")
@login_required
def ticket_detail(ticket_id):
    t = get_ticket(ticket_id)
    if not t:
        flash("تیکت پیدا نشد.")
        return redirect(url_for("tickets"))
    tid, user_id, message, status, admin_reply, created_at = t

    reply_block = f"<p><b>پاسخ قبلی:</b> {esc(admin_reply)}</p>" if admin_reply else ""

    content = f"""
    <div class="panel">
      <p><b>شماره:</b> #{tid} — <b>کاربر:</b> {user_id} — <span class="badge {status}">{status}</span></p>
      <p><b>پیام کاربر:</b><br>{esc(message)}</p>
      {reply_block}
      <form method="post" action="{url_for('ticket_reply', ticket_id=tid)}">
        <label>پاسخ به کاربر</label>
        <textarea name="reply" required></textarea>
        <div style="margin-top:10px;" class="flex">
          <button type="submit">ارسال پاسخ</button>
          <a class="btn danger" href="{url_for('ticket_close', ticket_id=tid)}">بستن تیکت بدون پاسخ</a>
          <a class="btn secondary" href="{url_for('tickets')}">بازگشت</a>
        </div>
      </form>
    </div>
    """
    return render_page(f"تیکت #{tid}", "tickets", content)


@app.route("/tickets/<int:ticket_id>/reply", methods=["POST"])
@login_required
def ticket_reply(ticket_id):
    reply_text = request.form.get("reply", "").strip()
    t = get_ticket(ticket_id)
    if not t:
        flash("تیکت پیدا نشد.")
        return redirect(url_for("tickets"))
    if reply_text:
        update_ticket_status(ticket_id, "answered", reply_text)
        send_telegram_message(t[1], f"📩 پاسخ پشتیبانی برای تیکت #{ticket_id}:\n\n{reply_text}")
        flash("پاسخ برای کاربر ارسال شد.")
    return redirect(url_for("tickets"))


@app.route("/tickets/<int:ticket_id>/close")
@login_required
def ticket_close(ticket_id):
    update_ticket_status(ticket_id, "closed")
    flash(f"تیکت #{ticket_id} بسته شد.")
    return redirect(url_for("tickets"))


@app.route("/settings")
@login_required
def settings_page():
    ensure_settings_table()
    all_settings = get_all_settings()

    groups_html = ""
    for title, items in CONFIG_GROUPS:
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
            <input id="s_{key}" name="{key}" value="{esc(value)}" placeholder="{esc(default)}"{attrs}>
            """
        groups_html += f'<div class="panel"><h3 style="margin-top:0;">{title}</h3>{rows}</div>'

    rows_html = ""
    for key, label in FEATURES.items():
        enabled = all_settings.get(key, "1") == "1"
        badge = '<span class="badge on">روشن</span>' if enabled else '<span class="badge off">خاموش</span>'
        btn_label = "خاموش کن" if enabled else "روشن کن"
        btn_class = "danger" if enabled else ""
        rows_html += f"""
        <tr>
          <td>{label}</td>
          <td>{badge}</td>
          <td>
            <form method="post" action="{url_for('toggle_setting', key=key)}">
              <button type="submit" class="{btn_class}">{btn_label}</button>
            </form>
          </td>
        </tr>
        """

    content = f"""
    <style>.savebar {{ position: sticky; bottom: 76px; z-index: 5; padding: 10px 0; background: linear-gradient(transparent, var(--bg) 35%); }}</style>
    <form method="post" action="{url_for('save_config')}">
      {groups_html}
      <p class="muted" style="font-size:12.5px;">هر فیلد را خالی بگذارید یا برابر مقدار پیش‌فرض (داخل کادر کم‌رنگ) بنویسید تا به پیش‌فرض برگردد. تغییرات حداکثر ~۲۰ ثانیه بعد روی ربات اعمال می‌شود.</p>
      <div class="savebar"><button type="submit" class="block">💾 ذخیره‌ی همه‌ی تغییرات</button></div>
    </form>
    <h3>🔌 روشن/خاموش کردن قابلیت‌ها</h3>
    <table>
      <tr><th>قابلیت</th><th>وضعیت</th><th></th></tr>
      {rows_html}
    </table>
    """
    return render_page("تنظیمات ربات", "settings", content)


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
  .savebar { position: sticky; bottom: 76px; z-index: 5; padding: 10px 0; background: linear-gradient(transparent, var(--bg) 35%); }
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


@app.route("/resellers")
@login_required
def resellers_page():
    rows = get_all_resellers()
    rows_html = ""
    for user_id, api_key, gb_balance, price_per_gb, status, revenue, configs_count in rows:
        badge = '<span class="badge on">فعال</span>' if status == 'active' else '<span class="badge off">مسدود</span>'
        toggle_label = "مسدود کن" if status == 'active' else "فعال کن"
        rows_html += f"""
        <tr>
          <td>{user_id}</td>
          <td><code style="font-size:12px;">{esc(api_key)}</code></td>
          <td>{gb_balance:g} گیگ</td>
          <td>{revenue:,} تومان</td>
          <td>{configs_count}</td>
          <td>{badge}</td>
          <td class="flex">
            <form method="post" action="{url_for('reseller_price', user_id=user_id)}" class="flex">
              <input type="number" name="price_per_gb" value="{price_per_gb}" style="width:100px;" required>
              <button type="submit" class="secondary">ذخیره</button>
            </form>
            <form method="post" action="{url_for('reseller_toggle', user_id=user_id)}">
              <button type="submit" class="{'danger' if status == 'active' else ''}">{toggle_label}</button>
            </form>
            <a class="btn secondary" href="{url_for('reseller_detail', user_id=user_id)}">جزئیات</a>
          </td>
        </tr>
        """
    content = f"""
    <table>
      <tr><th>آیدی</th><th>API Key</th><th>استخر باقیمونده</th><th>درآمد از فروشندگی</th>
          <th>کانفیگ فعال</th><th>وضعیت</th><th>عملیات</th></tr>
      {rows_html if rows_html else '<tr><td colspan="7">هنوز فروشنده‌ای فعال نشده.</td></tr>'}
    </table>
    """
    return render_page("فروشنده‌ها", "resellers", content)


@app.route("/resellers/<int:user_id>/toggle", methods=["POST"])
@login_required
def reseller_toggle(user_id):
    toggle_reseller_status(user_id)
    flash(f"وضعیت فروشنده {user_id} تغییر کرد.")
    return redirect(url_for("resellers_page"))


@app.route("/resellers/<int:user_id>/price", methods=["POST"])
@login_required
def reseller_price(user_id):
    try:
        price = int(request.form.get("price_per_gb", ""))
        if price <= 0:
            raise ValueError
    except ValueError:
        flash("قیمت هر گیگ باید عدد صحیح مثبت باشد.")
        return redirect(url_for("resellers_page"))
    update_reseller_price(user_id, price)
    flash(f"قیمت هر گیگ فروشنده {user_id} به {price:,} تومان تغییر کرد.")
    return redirect(url_for("resellers_page"))


@app.route("/resellers/<int:user_id>")
@login_required
def reseller_detail(user_id):
    configs = get_reseller_configs(user_id)
    rows_html = ""
    for label, ctype, gb, days, active, created_at, source, config_id in configs:
        badge = '<span class="badge on">فعال</span>' if active else '<span class="badge off">حذف‌شده</span>'
        src_label = "🛠 از تو بات" if source == 'bot' else "🔌 از طریق API"
        rows_html += f"""
        <tr>
          <td>{esc(label)}</td>
          <td>{esc(ctype)}</td>
          <td>{gb:g} گیگ</td>
          <td>{days} روز</td>
          <td>{src_label}</td>
          <td>{esc(created_at)[:16]}</td>
          <td>{badge}</td>
        </tr>
        """
    content = f"""
    <p><a class="btn secondary" href="{url_for('resellers_page')}">‹ بازگشت به فروشنده‌ها</a></p>
    <table>
      <tr><th>لیبل</th><th>نوع</th><th>حجم</th><th>مدت</th><th>منبع</th><th>تاریخ ساخت</th><th>وضعیت</th></tr>
      {rows_html if rows_html else '<tr><td colspan="7">این فروشنده هنوز کانفیگی نساخته.</td></tr>'}
    </table>
    """
    return render_page(f"کانفیگ‌های فروشنده {user_id}", "resellers", content)


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


@app.route("/broadcast", methods=["GET", "POST"])
@login_required
def broadcast():
    if request.method == "POST":
        text = request.form.get("text", "").strip()
        if not text:
            flash("متن پیام نمی‌تواند خالی باشد.")
        else:
            user_ids = get_all_user_ids()
            threading.Thread(target=broadcast_worker, args=(text, user_ids), daemon=True).start()
            flash(f"ارسال پیام همگانی برای {len(user_ids):,} کاربر شروع شد (در پس‌زمینه ادامه می‌یابد).")
        return redirect(url_for("broadcast"))

    content = f"""
    <div class="panel">
      <form method="post">
        <label>متن پیام همگانی (فرمت HTML تلگرام پشتیبانی می‌شود، مثل &lt;b&gt;بولد&lt;/b&gt;)</label>
        <textarea name="text" required></textarea>
        <div style="margin-top:12px;"><button type="submit">ارسال به همه‌ی کاربران</button></div>
      </form>
    </div>
    <p><small class="muted">این پیام برای همه‌ی کاربرانی که تا الان با ربات فروش /start زده‌اند ارسال می‌شود.</small></p>
    """
    return render_page("پیام همگانی", "broadcast", content)


if __name__ == "__main__":
    ensure_settings_table()
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
