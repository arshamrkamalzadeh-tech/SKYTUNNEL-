import requests
import re
import time
import json
import os
import io
import math
import html as _html
import threading
import asyncio
import builtins
import getpass
import glob
import inspect
import queue
import turso_serverless
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False

TOKEN = os.getenv("BOT_TOKEN", "69786607:p-AAjsil8xAOknphz-PxbDBsvFxFSWknCMg").strip()
if not TOKEN:
    raise SystemExit("متغیر محیطی BOT_TOKEN تنظیم نشده. بدون اون بات بالا نمیاد.")
BASE_URL = "https://api.splus.ir/bot" + TOKEN
CONFIG_API = os.getenv("CONFIG_API", "https://su.randomatic.ir/api/v1/configs")
CONFIG_KEY = os.getenv("CONFIG_KEY", "").strip()

# --- فروشندگی (reseller): حداقل خرید استخر برای فعال‌سازی و قیمت هر گیگ ---
RESELLER_MIN_GB = int(os.getenv("RESELLER_MIN_GB", "50"))
RESELLER_PRICE_PER_GB = int(os.getenv("RESELLER_PRICE_PER_GB", "2000"))
# قیمت پله‌ای شارژ مجدد استخر: قیمت هر گیگ بر اساس «مجموع گیگی که همین بار می‌خرید» تعیین می‌شه
# (حد بالا شاملِ همون پله است). آخرین ردیف با None یعنی «از اون به بالا».
RESELLER_TOPUP_MIN_GB = 1
RESELLER_TOPUP_TIERS = [(10, 3500), (20, 3000), (30, 2500), (None, 2000)]


def reseller_topup_rate(gb):
    """قیمت هر گیگ (تومان) برای خرید gb گیگ (پله‌ها از پنل ادمین قابل تغییرن)."""
    tiers = get_reseller_topup_tiers()
    for limit, rate in tiers:
        if limit is None or gb <= limit:
            return rate
    return tiers[-1][1]


def reseller_tiers_text(chat_id=None):
    lang = get_user_lang(chat_id) if chat_id is not None else 'fa'
    lines, prev = [], 0
    for limit, rate in get_reseller_topup_tiers():
        if limit is None:
            lines.append(u(lang, 'tier_line_last', prev=prev, rate=f'{rate:,}'))
        elif prev == 0:
            lines.append(u(lang, 'tier_line_first', limit=limit, rate=f'{rate:,}'))
        else:
            lines.append(u(lang, 'tier_line_range', prev=prev, limit=limit, rate=f'{rate:,}'))
        prev = limit
    return '\n'.join(lines)


def reseller_price_range_text(chat_id):
    tiers = get_reseller_topup_tiers()
    return u(chat_id, 'price_range', low=f'{tiers[-1][1]:,}', high=f'{tiers[0][1]:,}')


RESELLER_API_BASE = os.getenv("RESELLER_API_BASE", "http://YOUR-SERVER-IP:8088")
# آدرس پنلی که فروشنده بعد از خرید استخر گیگ باهاش کانفیگ می‌سازه (پیش‌فرض: همون آدرس API)
RESELLER_PANEL_URL = os.getenv("RESELLER_PANEL_URL", "https://just-reseller-panel-six.vercel.app/")
ADMIN_ID = int(os.getenv("ADMIN_ID", "48198481"))

# مقادیر پیش‌فرض (fallback) — اگه از پنل وب مقداری تو جدول settings ثبت نشده
# باشه، همین مقادیر استفاده می‌شن. مقدار واقعی و قابل‌تغییر همیشه با
# get_setting() خونده می‌شه (پایین‌تر) تا بدون نیاز به ری‌استارت ربات، از پنل
# قابل تغییر باشه.
DEFAULT_CARD_NUMBER = os.getenv("CARD_NUMBER", "6219861957006504")
DEFAULT_CARD_OWNER = os.getenv("CARD_OWNER", "کمالزاده")
DEFAULT_MIN_TOPUP = os.getenv("MIN_TOPUP", "10000")

# --- شارژ با رمزارز (دستی: کاربر رسید می‌فرسته، ادمین تایید/رد می‌کنه) ---
# هیچ تنظیمی تو Environment لازم نیست. لیست رمزارزها، اسم نمایشی، نام کوین تو نوبیتکس، آدرس ولت هر کوین
# و روشن/خاموش همه از پنل ادمین، صفحه‌ی «رمزارزها» (کلید crypto_coins تو جدول settings) کنترل می‌شه
# و تغییرات حداکثر ~۲۰ ثانیه بعد روی ربات اعمال می‌شه. تا وقتی از پنل کوینی با آدرس ولت ثبت نشده،
# گزینه‌ی رمزارز تو ربات نشون داده نمی‌شه.
# API عمومی قیمت (بدون کلید). تو مستندات جدید نوبیتکس آدرس رسمی apiv2.nobitex.ir هست؛
# api.nobitex.ir آدرس قدیمیه و از سرور خارج از ایران (مثل Railway) ممکنه DNS اش جواب نده.
# ربات به ترتیب هر دو رو امتحان می‌کنه. اگه خواستی دستی عوض کنی: Environment با اسم NOBITEX_API_BASE
# (یک یا چند آدرس با کاما جدا شده).
NOBITEX_API_BASES = [x.strip().rstrip('/') for x in os.getenv(
    "NOBITEX_API_BASE", "https://apiv2.nobitex.ir,https://api.nobitex.ir").split(',') if x.strip()]
NOBITEX_API_BASE = NOBITEX_API_BASES[0]

# ---------------------------------------------------------------------------
# Service types & per-GB pricing
# ---------------------------------------------------------------------------
# مقدار "proto" طبق مستندات پنل CONFIG_API:
#   both      -> پیش‌فرض، هم xray هم wireguard ساخته می‌شه
#   xray      -> فقط xray، هیچ فایل وایرگاردی ساخته نمی‌شه ("فقط کانفیگ")
#   wireguard -> فقط وایرگارد؛ در این حالت بدنه‌ی sub_url خودِ کانفیگ
#                وایرگارده و ساب‌لینک واقعی وجود نداره
#   openvpn   -> فایل‌های مستقل .ovpn؛ از اعتبار گیگ کم می‌کنه و در صورت
#                بسته بودن فروش جدید توسط پنل با proto_unavailable رد می‌شه
DEFAULT_PRICE_PER_GB_WIREGUARD = os.getenv("PRICE_PER_GB_WIREGUARD", "3500")
DEFAULT_PRICE_PER_GB_CONFIG = os.getenv("PRICE_PER_GB_CONFIG", "3500")
DEFAULT_PRICE_PER_GB_BOTH = os.getenv("PRICE_PER_GB_BOTH", "5500")
DEFAULT_PRICE_PER_GB_OPENVPN = os.getenv("PRICE_PER_GB_OPENVPN", "4000")
DEFAULT_PRICE_PER_GB_DNS = os.getenv("PRICE_PER_GB_DNS", "4000")

CONFIG_TYPE_DEFAULT_LABELS = {
    'wireguard': '🔒 فقط وایرگارد',
    'config': '⚙️ فقط کانفیگ',
    'both': '🔀 هر دو',
    'openvpn': '📱 فقط OpenVPN',
    'dns': '🎮 فقط DNS بازی',
}

# CONFIG_TYPES دیگه یه dict ثابت نیست — get_config_types() هر بار قیمت‌ها *و*
# لیبل‌ها رو فعلی رو از جدول settings می‌خونه تا هم تغییر قیمت و هم تغییر نام
# دکمه از پنل وب فوراً روی ربات هم اعمال بشه (بدون نیاز به ری‌استارت).
def get_config_types():
    return {
        'wireguard': {'label': get_setting('ctype_label_wireguard', CONFIG_TYPE_DEFAULT_LABELS['wireguard']), 'proto': 'wireguard',
                      'price_per_gb': int(get_setting('price_wireguard', DEFAULT_PRICE_PER_GB_WIREGUARD))},
        'config':    {'label': get_setting('ctype_label_config', CONFIG_TYPE_DEFAULT_LABELS['config']), 'proto': 'xray',
                      'price_per_gb': int(get_setting('price_config', DEFAULT_PRICE_PER_GB_CONFIG))},
        'both':      {'label': get_setting('ctype_label_both', CONFIG_TYPE_DEFAULT_LABELS['both']), 'proto': 'both',
                      'price_per_gb': int(get_setting('price_both', DEFAULT_PRICE_PER_GB_BOTH))},
        'openvpn':   {'label': get_setting('ctype_label_openvpn', CONFIG_TYPE_DEFAULT_LABELS['openvpn']), 'proto': 'openvpn',
                      'price_per_gb': int(get_setting('price_openvpn', DEFAULT_PRICE_PER_GB_OPENVPN))},
        # طبق مستندات پنل: با proto='dns' فقط پروفایل DNS بازی ساخته می‌شه (مصرفش
        # از حجم همین کانفیگ کم می‌شه). اگه DNS رو سرور/پلتفرم خاموش باشه، پنل
        # با خطای dns_unavailable / dns_off_for_seller رد می‌کنه و make_config
        # همون رفتار استاندارد proto_unavailable رو نشون می‌ده (چیزی کم نمی‌شه).
        'dns':       {'label': get_setting('ctype_label_dns', CONFIG_TYPE_DEFAULT_LABELS['dns']), 'proto': 'dns',
                      'price_per_gb': int(get_setting('price_dns', DEFAULT_PRICE_PER_GB_DNS))},
    }


def get_card_number():
    return get_setting('card_number', DEFAULT_CARD_NUMBER)


def get_card_owner():
    return get_setting('card_owner', DEFAULT_CARD_OWNER)


def get_min_topup():
    """حداقل شارژ کارت‌به‌کارت (ریالی)."""
    return int(get_setting('min_topup', DEFAULT_MIN_TOPUP))


def get_min_topup_crypto():
    """حداقل شارژ با رمزارز (جدا از کارت‌به‌کارت؛ اگه از پنل ثبت نشده باشه همون حداقل کارت‌به‌کارته)."""
    try:
        return int(get_setting('min_topup_crypto', str(get_min_topup())))
    except Exception:
        return get_min_topup()


def get_min_topup_for(method):
    return get_min_topup_crypto() if method == 'crypto' else get_min_topup()


def get_topup_multiplier():
    """ضریب واریزی: مبلغی که کاربر واریز می‌کنه، وقتی ادمین تاییدش می‌کنه، تو
    این ضریب ضرب می‌شه و همون مقدار به کیف پول اضافه می‌شه (مثلاً با ضریب ۲،
    واریز ۱۰,۰۰۰ تومانی = ۲۰,۰۰۰ تومان شارژ کیف پول). پیش‌فرض ۱ یعنی بدون
    تغییر."""
    try:
        return float(get_setting('topup_multiplier', '1'))
    except (TypeError, ValueError):
        return 1.0


# ---------------------------------------------------------------------------
# پارامترهای قابل‌تغییر از پنل وب (جدول settings). مقدار env/کد فقط fallback است.
# ---------------------------------------------------------------------------
DEFAULT_RESELLER_TIERS_STR = '10:3500,20:3000,30:2500,*:2000'
APP_LINK_DEFAULTS = [
    ('android', os.getenv('APP_LINK_ANDROID', 'https://play.google.com/store/apps/details?id=com.v2pro.client')),
    ('ios', os.getenv('APP_LINK_IOS', 'https://apps.apple.com/us/app/v2pro/id6801607092')),
    ('windows', os.getenv('APP_LINK_WINDOWS', 'https://su.randomatic.ir/v2pro/1.1.2/V2Pro-Setup-x64.exe')),
    ('mac', os.getenv('APP_LINK_MAC', 'https://su.randomatic.ir/v2pro/1.1.2/v2pro-macos-universal.zip')),
    ('linux', os.getenv('APP_LINK_LINUX', 'https://su.randomatic.ir/v2pro/1.1.2/v2pro-linux-x64.tar.gz')),
]


def _setting_int(key, default):
    try:
        return int(float(get_setting(key, str(default))))
    except (TypeError, ValueError):
        return int(default)


def _setting_float(key, default):
    try:
        return float(get_setting(key, str(default)))
    except (TypeError, ValueError):
        return float(default)


def get_reseller_min_gb():
    return max(1, _setting_int('reseller_min_gb', RESELLER_MIN_GB))


def get_reseller_price_per_gb():
    return max(0, _setting_int('reseller_price_per_gb', RESELLER_PRICE_PER_GB))


def get_reseller_topup_min_gb():
    return max(1, _setting_int('reseller_topup_min_gb', RESELLER_TOPUP_MIN_GB))


def get_reseller_panel_url():
    return get_setting('reseller_panel_url', RESELLER_PANEL_URL) or RESELLER_PANEL_URL


def parse_reseller_tiers(raw):
    """'10:3500,20:3000,*:2000' -> [(10, 3500), (20, 3000), (None, 2000)]"""
    finite, rest = [], []
    for part in str(raw or '').split(','):
        part = part.strip()
        if ':' not in part:
            continue
        lim, rate = (x.strip() for x in part.split(':', 1))
        try:
            rate_i = int(rate)
            lim_v = None if lim in ('*', '') else int(lim)
        except ValueError:
            continue
        (rest if lim_v is None else finite).append((lim_v, rate_i))
    finite.sort(key=lambda t: t[0])
    if not finite and not rest:
        return list(RESELLER_TOPUP_TIERS)
    if not rest:
        rest = [(None, finite[-1][1])]
    return finite + rest[:1]


def get_reseller_topup_tiers():
    return parse_reseller_tiers(get_setting('reseller_topup_tiers', DEFAULT_RESELLER_TIERS_STR))


def get_trial_gb():
    return max(0.01, _setting_float('trial_gb', 0.1))


def get_trial_days():
    return max(1, _setting_int('trial_days', 1))


def get_trial_label():
    return get_setting('trial_label', 'تست رایگان') or 'تست رایگان'


def get_refund_ratio():
    return min(1.0, max(0.0, _setting_float('refund_ratio', 0.5)))


def get_default_gb():
    return max(1, _setting_int('default_gb', 1))


def get_default_days():
    return max(1, _setting_int('default_days', 30))


def get_app_links():
    return [(k, get_setting('app_link_' + k, d) or d) for k, d in APP_LINK_DEFAULTS]


TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "libsql://skytunnel-mikekamalzadeh-sys.aws-eu-west-1.turso.io")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3ODkwNzE5MDcsImlkIjoiMDFhMDhjZmQtMmMwMS03YWViLTlmYzQtOWYzMTkwNzEwMjA0Iiwia2lkIjoiNmltOXd5bGxUd2luNkVHWEJWNHVJUE01ZWNPM2JyZmJ3NzFqWTFIanFCTSIsInJpZCI6ImU5N2NmZmQwLTgxZDYtNDA3Yi1hZGQ4LTEzMTRjY2MyZTkxYyJ9.tZj3mmc_tNCVRPsLkwuWdrGsXZXmFCcvRCEPcN0iclAMk0QrHWfZxZiGqB5otvhlZaT9fs_WzsO6kTS_gnk1Bw")

DIVIDER = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"

# دکمه‌ی «انصراف» که زیر پیام‌های «فقط عدد/متن ارسال کنید» گذاشته می‌شه، تا تو
# سبک کیبورد اینلاین هم کاربر یه راه برگشت به منو داشته باشه (قبلاً فقط با
# تایپ‌کردن یه چیزی یا رفتن به /start می‌شد از این مرحله‌ها خارج شد).

# ---------------------------------------------------------------------------
# چندزبانه (فارسی/انگلیسی)
# ---------------------------------------------------------------------------
# متن‌های اصلی/پیش‌فرض ربات (main_menu، buy_menu، account و ...) همچنان از
# get_bot_text_fmt خونده می‌شن تا سفارشی‌سازی‌های ادمین از پنل وب دست‌نخورده
# بمونه (اون‌ها فقط فارسی‌ان). این دیکشنری برای متن‌ها/دکمه‌هایی است که یا
# تازه اضافه شدن (سفارشات اخیر، تغییر زبان) یا قبلاً مستقیم تو کد فارسی
# نوشته شده بودن (فاکتور خرید، صفحه‌ی حجم/روز، پیام‌های مدیریت کانفیگ و...)
# — این‌ها حالا هم فارسی هم انگلیسی دارن و با تابع u() انتخاب می‌شن.
UI_TEXT = {
    'fa': {
        'cur': 'تومان', 'unit_gb': 'گیگ', 'unit_day': 'روز',
        'btn_topup': '💠 شارژ کیف پول',
        'btn_cancel': '❌ انصراف',
        'btn_recentorders': '🧾 سفارشات اخیر من',
        'btn_language': '🌐 تغییر زبان',
        'svc_wireguard': '🔒 فقط وایرگارد', 'svc_config': '⚙️ فقط کانفیگ',
        'svc_both': '🔀 هر دو', 'svc_openvpn': '📱 فقط OpenVPN', 'svc_dns': '🎮 فقط DNS بازی',
        'qty_screen': (
            '📦 <b>{ctype_label}</b>\n'
            'هر گیگابایت: <b>{price_per_gb}</b> تومان\n'
            '💳 موجودی: <b>{wallet}</b> تومان\n\n'
            'حجم و مدت اعتبار رو با دکمه‌های + / - تنظیم کن:\n\n'
            '💰 قیمت فعلی: <b>{price}</b> تومان'
        ),
        'qty_continue': '✅ ادامه',
        'ask_label_prompt': '🏷 یک نام دلخواه برای این کانفیگ ارسال کنید:',
        'ask_label_skip': '➡️ رد شدن (اسم پیش‌فرض)',
        'invoice_title': '🧾 <b>فاکتور خرید کانفیگ</b>',
        'invoice_type': '📦 نوع سرویس: <b>{ctype_label}</b>',
        'invoice_volume': '📶 حجم: <b>{gb}</b> گیگابایت',
        'invoice_name': '🏷 نام: <b>{label}</b>',
        'invoice_duration': '⏳ مدت اعتبار: <b>{days}</b> روز',
        'invoice_discount_line': '🎟 کد تخفیف: <b>{code}</b> (٪{percent})',
        'invoice_base_price': '💵 مبلغ فاکتور: <s>{base_price:,}</s> تومان',
        'invoice_final_price': '💰 مبلغ نهایی: <b>{price:,}</b> تومان',
        'invoice_price': '💵 مبلغ قابل پرداخت: <b>{price:,}</b> تومان',
        'invoice_footer': 'برای پرداخت روی «✅ تایید» بزنید، یا اگه کد تخفیف دارید اول اعمالش کنید.',
        'btn_confirm_purchase': '✅ تایید',
        'btn_cancel_purchase': '❌ لغو خرید',
        'btn_apply_discount': '🎟 اعمال کد تخفیف',
        'discount_ask_prompt': '🎟 کد تخفیف را ارسال کنید:',
        'discount_invalid': '❌ کد تخفیف نامعتبر است.',
        'discount_inactive': '⛔ این کد تخفیف غیرفعال شده است.',
        'discount_capacity': '⚠️ ظرفیت استفاده از این کد تخفیف تمام شده است.',
        'building_config': '⏳ در حال ساخت کانفیگ، لطفاً شکیبا باشید...',
        'insufficient_balance': (
            '⚠️ <b>موجودی کیف پول شما کافی نیست.</b>\n{divider}\n'
            '💳 موجودی فعلی شما: <b>{wallet:,}</b> تومان\n'
            '💰 مبلغ این خرید: <b>{price:,}</b> تومان\n'
            '📉 کسری: <b>{shortfall:,}</b> تومان\n\n'
            'در صورتی که می‌خواهید این کانفیگ را تهیه کنید، ابتدا کیف پول خود را شارژ کنید:'
        ),
        'purchase_success': (
            '🎉 <b>کانفیگ شما با موفقیت ساخته شد</b>\n{divider}\n'
            '📦 نوع سرویس: <b>{ctype_label}</b>\n'
            '📶 حجم: <b>{gb}</b> گیگابایت\n'
            '🏷 نام: <b>{label}</b>\n'
            '⏳ مدت اعتبار: <b>{days}</b> روز\n'
            '💵 قیمت: <b>{price:,}</b> تومان\n{divider}\n'
            '{output_label}\n<code>{sub_url}</code>'
        ),
        'output_label_wireguard': '📄 کانفیگ وایرگارد:',
        'output_label_openvpn': '📄 فایل OpenVPN:',
        'output_label_default': '🔗 لینک سابسکریپشن:',
        'proto_unavailable': (
            '⛔ فروش سرویس «{ctype_label}» در حال حاضر توسط پنل بسته است.\n'
            'لطفاً نوع سرویس دیگری را انتخاب کنید یا بعداً دوباره تلاش کنید.\n'
            '(مبلغی از کیف پول شما کسر نشد.)'
        ),
        'dns_unavailable': (
            '⛔ سرویس «{ctype_label}» در حال حاضر روی پلتفرم یا سرورهای شما خاموش است.\n'
            'لطفاً نوع سرویس دیگری را انتخاب کنید یا بعداً دوباره تلاش کنید.\n'
            '(مبلغی از کیف پول شما کسر نشد.)'
        ),
        'server_error': '❌ خطا در ارتباط با سرور پنل. لطفاً دوباره تلاش کنید.',
        'config_not_found': '⚠️ این کانفیگ یافت نشد.',
        'myconfigs_header': '🗂 <b>لیست کانفیگ‌های شما</b>',
        'myconfigs_status_active': '🟢 فعاله',
        'myconfigs_status_paused': '⚪ متوقف‌شده',
        'myconfigs_status_expired': '🔴 منقضی‌شده',
        'myconfigs_card': (
            '<b>{idx}. {label}</b> {status}\n'
            '{bar}\n'
            '📶 باقی‌مانده از {gb} گیگ: <b>{remaining_gb}</b> گیگ\n'
            '📊 مصرف‌شده: <b>{used_gb}</b> گیگ\n'
            '⏳ اعتبار باقی‌مانده: <b>{remaining_days}</b> روز\n'
            '📦 نوع سرویس: {ctype_label}\n'
            '🔗 <code>{sub_url}</code>'
        ),
        'myconfigs_usage_unknown': '📊 مصرف این کانفیگ در حال حاضر از پنل قابل بررسی نیست.',
        'btn_manage_config': '⚙️ مدیریت #{idx} — {label}',
        'manage_title': '⚙️ <b>مدیریت کانفیگ</b>',
        'manage_name': '🏷 نام: <b>{label}</b>',
        'manage_volume': '📶 حجم: <b>{gb}</b> گیگابایت',
        'manage_duration': '⏳ مدت: <b>{days}</b> روز',
        'manage_status_active': '▶️ وضعیت: <b>فعال</b>\n',
        'manage_status_paused': '⏸ وضعیت: <b>متوقف</b>\n',
        'manage_footer': 'یکی از عملیات زیر را انتخاب کنید:',
        'btn_extend': '➕ تمدید (حجم/روز)',
        'btn_rename': '✏️ تغییر نام',
        'btn_qr': '📷 دریافت QR Code',
        'btn_pause': '⏸ توقف',
        'btn_resume': '▶️ از سرگیری',
        'btn_rotate': '🔄 تغییر لینک',
        'btn_close': '❌ بستن',
        'ext_ask_gb': '➕ چند گیگابایت به این کانفیگ اضافه شود؟ (فقط عدد ارسال کنید)',
        'ext_ask_days': '⏳ چند روز به مدت اعتبار اضافه شود؟ (فقط عدد ارسال کنید)',
        'ext_number_error': '⚠️ عددی بزرگ‌تر از صفر وارد کنید.',
        'ext_confirm_title': (
            '🧾 <b>تایید تمدید کانفیگ</b>\n{divider}\n'
            '🏷 نام: <b>{label}</b>\n'
            '➕ افزایش حجم: <b>{extra_gb}</b> گیگابایت\n'
            '⏳ افزایش مدت: <b>{extra_days}</b> روز\n'
            '💵 هزینه: <b>{price:,}</b> تومان'
        ),
        'btn_confirm_pay': '✅ تایید و پرداخت',
        'ext_success': '✅ کانفیگ «{label}» تمدید شد: +{extra_gb} گیگابایت، +{extra_days} روز — <b>{price:,}</b> تومان کسر شد.',
        'ext_panel_error': '❌ خطا در تمدید کانفیگ از سمت پنل. لطفاً بعداً دوباره تلاش کنید.',
        'ext_cancelled': '❌ تمدید لغو شد.',
        'ext_insufficient': '⚠️ موجودی کیف پول کافی نیست.',
        'rename_ask': '✏️ نام جدید کانفیگ را ارسال کنید:',
        'rename_empty_error': '⚠️ نام نمی‌تواند خالی باشد.',
        'rename_success_new_url': '✅ نام کانفیگ به «{label}» تغییر کرد.\n🔗 لینک به‌روزشده:\n<code>{sub_url}</code>\n\n⚠️ لطفاً این لینک جدید را دوباره در برنامه‌ی خود وارد کنید.',
        'rename_success_no_url': '✅ نام کانفیگ به «{label}» تغییر کرد.\nبرای دیدن لینک فعلی، دوباره «🗂 کانفیگ‌های من» را بزنید.',
        'rename_panel_error': '❌ خطا در تغییر نام از سمت پنل. لطفاً بعداً دوباره تلاش کنید.',
        'qr_not_available': '❌ ساخت QR Code روی سرور فعال نیست.\nادمین باید کتابخونه‌ی لازم رو نصب کند.',
        'qr_caption': '📷 <b>QR Code کانفیگ «{label}»</b>\n{divider}\n🔗 <code>{sub_url}</code>',
        'qr_error': '❌ خطا در ساخت QR Code. لطفاً دوباره تلاش کنید.',
        'pause_success': '⏸ کانفیگ «{label}» متوقف شد.',
        'pause_error': '❌ خطا در توقف کانفیگ. لطفاً بعداً دوباره تلاش کنید.',
        'resume_success': '▶️ کانفیگ «{label}» از سر گرفته شد.',
        'resume_error': '❌ خطا در از سرگیری کانفیگ. لطفاً بعداً دوباره تلاش کنید.',
        'rotate_success': '🔄 لینک کانفیگ «{label}» تغییر کرد:\n<code>{sub_url}</code>',
        'rotate_success_no_url': '🔄 لینک تغییر کرد؛ برای دیدن لینک جدید، دوباره «کانفیگ‌های من» را بزنید.',
        'rotate_error': '❌ خطا در تغییر لینک. لطفاً بعداً دوباره تلاش کنید.',
        'myconfigs_empty': '📭 هنوز هیچ کانفیگی ثبت نکرده‌اید.',
        'delete_prompt': '🗑 شماره ردیف کانفیگ مورد نظر برای حذف را ارسال کنید:',
        'delete_empty': '📭 کانفیگی برای حذف وجود ندارد.',
        'delete_invalid_index': '⚠️ شماره ردیف نامعتبر است.',
        'delete_confirm_title': (
            '🗑 <b>تایید حذف کانفیگ</b>\n{divider}\n'
            '🏷 نام: <b>{label}</b>\n'
            '📶 حجم خریداری‌شده: <b>{gb}</b> گیگابایت\n'
            '📊 مصرف‌شده: <b>{used_gb}</b> گیگابایت\n'
            '💵 قیمت خرید: <b>{price:,}</b> تومان\n{divider}\n'
            '💰 مبلغی که به کیف پولتان بازمی‌گردد (نصف ارزش باقیمانده): <b>{refund:,}</b> تومان\n\n'
            '{usage_note}'
            '⚠️ این عملیات غیرقابل بازگشت است. مطمئنید می‌خواهید این کانفیگ حذف شود؟'
        ),
        'delete_usage_unknown': '⚠️ مصرف این کانفیگ از پنل قابل بررسی نبود؛ برای احتیاط مبلغی بازگردانده نمی‌شود.\n\n',
        'btn_delete_yes': '✅ بله، حذف کن',
        'delete_row_number_error': '⚠️ لطفاً فقط شماره ردیف را وارد کنید.',
        'delete_success': '✅ کانفیگ حذف شد و مبلغ <b>{refund:,}</b> تومان به کیف پول شما اضافه شد.',
        'delete_success_no_refund': '✅ کانفیگ حذف شد.',
        'delete_panel_error': '⚠️ خطا در حذف کانفیگ. لطفاً دوباره تلاش کنید.',
        'delete_cancelled': '❌ عملیات حذف لغو شد.',
        'support_reply_received': '📩 پاسخ پشتیبانی برای تیکت #{tid}:\n\n{reply_text}',
        'trial_used': '⚠️ شما پیش‌تر از تست رایگان استفاده کرده‌اید.',
        'trial_used_on_panel': '⚠️ شما قبلاً تست رایگان دریافت کرده‌اید.',
        'trial_building': '⏳ در حال ساخت کانفیگ تست...',
        'trial_ready': (
            '🎁 <b>کانفیگ تست رایگان شما آماده شد</b>\n{divider}\n'
            '📶 حجم: <b>{trial_gb}</b> گیگابایت\n'
            '⏳ مدت اعتبار: <b>{trial_days}</b> روز\n{divider}\n'
            '🔗 لینک سابسکریپشن:\n<code>{sub_url}</code>'
        ),
        'trial_error': '❌ خطا در ساخت کانفیگ تست. لطفاً بعداً دوباره تلاش کنید.',
        'topup_prompt': '💠 مبلغ مورد نظر برای شارژ کیف پول را به تومان وارد کنید.\nحداقل مبلغ شارژ: <b>{min_topup}</b> تومان',
        'topup_card_info': (
            '💳 <b>اطلاعات پرداخت</b>\n{divider}\n'
            '💵 مبلغ: <b>{amount}</b> تومان\n'
            '💳 شماره کارت: <code>{card_number}</code>\n'
            '👤 به نام: <b>{card_owner}</b>\n\n'
            '📸 پس از واریز، تصویر رسید را ارسال کنید تا برای بررسی به پشتیبانی ارجاع داده شود.'
        ),
        'topup_min_error': '⚠️ حداقل مبلغ شارژ <b>{min_topup:,}</b> تومان است.',
        'topup_amount_error': '⚠️ لطفاً مبلغ را فقط به‌صورت عدد (تومان) وارد کنید.',
        'number_only_error': '⚠️ لطفاً فقط عدد وارد کنید.',
        'topup_need_photo': '📸 لطفاً تصویر رسید واریزی را ارسال کنید.',
        'topup_receipt_ok': '✅ رسید شما دریافت شد و برای بررسی ارسال گردید. پس از تایید، کیف پول شما شارژ خواهد شد.',
        'account_info': (
            '👤 <b>حساب کاربری شما</b>\n{divider}\n'
            '🆔 شناسه: <code>{chat_id}</code>\n'
            '💳 موجودی کیف پول: <b>{wallet}</b> تومان\n'
            '📊 مجموع خرید: <b>{total_gb}</b> گیگابایت\n'
            '💵 مجموع پرداختی: <b>{total_price}</b> تومان'
        ),
        'support_prompt': '🎧 پیام خود را برای پشتیبانی ارسال کنید:',
        'support_ticket_created': '✅ پیام شما با شناسه تیکت #{tid} برای پشتیبانی ثبت شد و به‌زودی پاسخ داده می‌شود.',
        'recentorders_header': '🧾 <b>۳ سفارش اخیر شما</b>',
        'recentorders_empty': '📭 هنوز هیچ سفارشی ثبت نکرده‌اید.',
        'recentorders_item': '<b>{idx}. {label}</b> — {gb} گیگ — {days} روز — {ctype_label}\n💵 مبلغ پرداختی: <b>{price:,}</b> تومان',
        'btn_reorder': '🔁 سفارش مجدد #{idx}',
        'reorder_not_found': '⚠️ این سفارش یافت نشد.',
        'lang_prompt': '🌐 لطفاً زبان مورد نظر خود را انتخاب کنید:',
        'lang_btn_fa': '🇮🇷 فارسی',
        'lang_btn_en': '🇬🇧 English',
        'lang_changed': '✅ زبان ربات به فارسی تغییر کرد.',
        'btn_guide': '📲 اپ مخصوص کانفیگ‌ها',
        'btn_reseller': '🧑‍💼 فروشنده شو',
        'reseller_intro': (
            '🧑‍💼 <b>فروشنده شوید</b>\n{divider}\n'
            'با فعال‌سازی فروشندگی، یه «استخر گیگ» می‌خرید که با قیمت ویژه‌ی '
            '<b>{price_per_gb}</b> تومان به‌ازای هر گیگ پر می‌شه (نصف قیمت عادی) و '
            'شامل همه‌ی نوع کانفیگ‌ها می‌شه (کانفیگ، وایرگارد، اوپن‌وی‌پی‌ان و DNS).\n\n'
            'بعد از فعال‌سازی، یه نام کاربری و رمز عبور برای ورود به پنل انتخاب می‌کنید و از همون‌جا برای '
            'مشتری‌هاتون کانفیگ می‌سازید — هر بار ساخت، از همون استخر گیگ کم می‌شه.\n\n'
            '📦 حداقل خرید فعال‌سازی: <b>{min_gb} گیگ</b>\n'
            '💵 مبلغ فعال‌سازی: <b>{activation_price}</b> تومان\n'
        ),
        'btn_reseller_activate': '✅ فعال‌سازی فروشندگی',
        'reseller_activated': (
            '🎉 <b>فروشندگی شما فعال شد!</b>\n{divider}\n'
            '📦 استخر اولیه: <b>{gb} گیگ</b>\n\n'
            '🌐 <b>آدرس پنل:</b>\n<code>{panel_url}</code>\n\n'
            '⚠️ <b>توجه:</b> اگه پنل باز نشد یا لود نمی‌شد، حتماً با <b>VPN</b> تست کنید.\n\n'
            '👇 حالا یه <b>نام کاربری</b> و <b>رمز عبور</b> برای ورود به پنل انتخاب کنید.'
        ),
        'reseller_ask_username': (
            '👤 یه <b>نام کاربری</b> برای ورود به پنل بفرستید.\n'
            'فقط حرف انگلیسی، عدد، _ و نقطه — بین {min_len} تا {max_len} کاراکتر.'
        ),
        'reseller_username_bad': '⚠️ نام کاربری معتبر نیست. فقط حرف انگلیسی، عدد، _ و نقطه (۳ تا ۲۰ کاراکتر) مجازه.',
        'reseller_username_taken': '⚠️ این نام کاربری قبلاً گرفته شده؛ یکی دیگه انتخاب کنید.',
        'reseller_ask_password': (
            '🔑 حالا یه <b>رمز عبور</b> بفرستید (حداقل {min_len} کاراکتر).\n'
            'پیامی که رمز توشه بعد از ارسال حذف می‌شه؛ رمز تو دیتابیس به‌صورت هش‌شده ذخیره می‌شه.'
        ),
        'reseller_password_bad': '⚠️ رمز باید بین {min_len} تا {max_len} کاراکتر باشه و فاصله‌ی ابتدا/انتها نداشته باشه.',
        'reseller_creds_done': (
            '✅ <b>اطلاعات ورود ذخیره شد.</b>\n{divider}\n'
            '👤 نام کاربری: <code>{username}</code>\n'
            '🔑 رمز عبور: همونی که فرستادید (برای امنیت نمایش داده نمی‌شه)\n\n'
            '🌐 آدرس پنل:\n<code>{panel_url}</code>\n\n'
            'هر وقت خواستید از منوی «فروشنده شو ← تغییر نام کاربری / رمز» عوضش کنید.'
        ),
        'reseller_creds_menu': (
            '🔑 <b>اطلاعات ورود به پنل</b>\n{divider}\n'
            '👤 نام کاربری فعلی: <code>{username}</code>\n\n'
            'کدوم رو می‌خواید عوض کنید؟'
        ),
        'btn_change_username': '👤 تغییر نام کاربری',
        'btn_change_password': '🔑 تغییر رمز عبور',
        'reseller_ask_new_username': '👤 <b>نام کاربری جدید</b> رو بفرستید (حرف انگلیسی، عدد، _ و نقطه؛ ۳ تا ۲۰ کاراکتر).',
        'reseller_ask_new_password': (
            '🔑 <b>رمز عبور جدید</b> رو بفرستید (حداقل {min_len} کاراکتر).\n'
            'پیامی که رمز توشه بعد از ارسال حذف می‌شه.'
        ),
        'reseller_username_changed': '✅ نام کاربری به <code>{username}</code> تغییر کرد. دفعه‌ی بعد با همین وارد پنل بشید.',
        'reseller_password_changed': '✅ رمز عبور تغییر کرد. دفعه‌ی بعد با رمز جدید وارد پنل بشید.',
        'reseller_creds_missing': '⚠️ هنوز نام کاربری و رمز ورود به پنل رو تنظیم نکردید.',
        'reseller_activate_confirm_title': (
            '🧾 <b>تایید فعال‌سازی فروشندگی</b>\n{divider}\n'
            '📦 استخر اولیه: <b>{gb}</b> گیگ\n'
            '💰 قیمت هر گیگ: <b>{price_per_gb}</b> تومان\n'
            '{divider}\n'
            '💵 مبلغ قابل پرداخت: <b>{price}</b> تومان\n\n'
            'مبلغ از کیف پولتون کم می‌شه و بعد از تایید، آدرس پنل تحویل داده می‌شه و نام کاربری و رمز ورودتون رو انتخاب می‌کنید. تایید می‌کنید؟'
        ),
        'reseller_dashboard': (
            '🧑‍💼 <b>پنل فروشندگی</b>\n{divider}\n'
            '📦 استخر باقیمونده: <b>{gb_balance}</b> گیگ\n'
            '💰 قیمت هر گیگ برای شما: <b>{price_per_gb}</b> تومان\n'
            '📡 وضعیت: <b>{status}</b>\n'
            '🌐 آدرس پنل: <code>{panel_url}</code>\n'
            '{creds_line}\n'
        ),
        'btn_reseller_topup': '➕ افزایش استخر گیگ',
        'btn_reseller_regen': '🔑 تغییر نام کاربری / رمز',
        'reseller_topup_prompt': (
            '➕ <b>افزایش استخر گیگ</b>\n{divider}\n'
            '💰 قیمت هر گیگ بر اساس حجم خرید:\n{tiers}\n\n'
            'چند گیگ می‌خواید به استخرتون اضافه بشه؟ فقط عدد بفرستید (حداقل {min_gb} گیگ).'
        ),
        'reseller_topup_min': '⚠️ حداقل خرید {min_gb} گیگ است. یه عدد بزرگ‌تر بفرستید.',
        'reseller_topup_confirm_title': (
            '📦 <b>{gb}</b> گیگ × <b>{rate:,}</b> تومان = <b>{price:,}</b> تومان\n'
            'از کیف پولتون کم می‌شه و به استخر اضافه می‌شه. تایید می‌کنید؟'
        ),
        'reseller_topup_done': '✅ {gb} گیگ به استخر شما اضافه شد. موجودی جدید: {gb_balance} گیگ.',
        'btn_reseller_make': '🛠 ساخت کانفیگ جدید',
        'btn_reseller_mylist': '📋 کانفیگ‌های ساخته‌شده‌ی من',
        'reseller_mk_ask_type': '🛠 <b>ساخت کانفیگ جدید</b>\n{divider}\nنوع کانفیگ رو انتخاب کنید:',
        'reseller_mk_ask_gb': '📶 چند گیگابایت از استخرتون کم بشه؟ (فقط عدد بفرستید — موجودی فعلی: {gb_balance} گیگ)',
        'reseller_mk_ask_days': '⏳ مدت اعتبار چند روز باشه؟ (فقط عدد بفرستید)',
        'reseller_mk_ask_label': '🏷 یه اسم/لیبل براش بفرستید (برای اسم خودکار، فقط - بفرستید).',
        'reseller_mk_confirm_title': (
            '🧾 <b>تایید ساخت کانفیگ</b>\n{divider}\n'
            '🏷 نام: <b>{label}</b>\n'
            '🧩 نوع: <b>{ctype_label}</b>\n'
            '📶 حجم: <b>{gb}</b> گیگابایت (از استخر کم می‌شه)\n'
            '⏳ مدت: <b>{days}</b> روز (تا {expiry})\n\n'
            'موجودی استخر بعد از این ساخت: <b>{gb_after}</b> گیگ'
        ),
        'reseller_mk_insufficient': '⚠️ استخر گیگ شما کافی نیست. موجودی فعلی: {gb_balance} گیگ.',
        'reseller_mk_panel_error': '❌ خطا در ساخت کانفیگ از سمت پنل. گیگ به استخرتون برگشت. لطفاً بعداً دوباره تلاش کنید.',
        'reseller_mk_success': (
            '✅ <b>کانفیگ ساخته شد</b>\n{divider}\n'
            '🏷 نام: <b>{label}</b>\n'
            '🧩 نوع: <b>{ctype_label}</b>\n'
            '📶 حجم: <b>{gb}</b> گیگابایت\n'
            '📅 تاریخ ساخت: <b>{created}</b>\n'
            '⏳ تاریخ انقضا: <b>{expiry}</b>\n'
            '📦 موجودی باقیمونده‌ی استخر: <b>{gb_after}</b> گیگ\n{divider}\n'
            '🔗 لینک اتصال:\n<code>{sub_url}</code>'
        ),
        'reseller_mylist_empty': '📭 هنوز از پنل فروشندگی کانفیگی نساختید.',
        'reseller_mylist_header': '📋 <b>{n} کانفیگ آخر شما</b>',
        'reseller_mylist_item': (
            '<b>{i}. {label}</b> — {ctype_label} — {gb} گیگ — {days} روز\n'
            '📅 {created} {status}'
        ),
        'guide_text': (
            '📲 <b>برنامه‌ی اتصال V2Pro</b>\n{divider}\n'
            'با این برنامه می‌تونید کانفیگ، DNS و همه‌ی سرویس‌هایی که از ربات می‌خرید رو وارد و مدیریت کنید.\n\n'
            'نسخه‌ی مناسب دستگاهتون رو انتخاب کنید 👇'
        ),
        'guide_fallback_title': '📲 <b>اپ مخصوص کانفیگ‌ها</b>',
        'plat_android': '🤖 اندروید',
        'plat_ios': '🍎 آیفون (iOS)',
        'plat_windows': '🪟 ویندوز',
        'plat_mac': '💻 مک (macOS)',
        'plat_linux': '🐧 لینوکس',
    },
    'en': {
        'cur': 'Toman', 'unit_gb': 'GB', 'unit_day': 'day(s)',
        'btn_cancel': '❌ Cancel',
        'btn_buy': '🛍 Buy Config',
        'btn_trial': '🧪 Free Trial',
        'btn_topup': '💠 Top Up Wallet',
        'btn_account': '👤 My Account',
        'btn_myconfigs': '🗂 My Configs',
        'btn_delete': '🗑 Delete Config',
        'btn_support': '🎧 Support',
        'btn_recentorders': '🧾 My Recent Orders',
        'btn_language': '🌐 Language',
        'welcome_intro': 'Welcome to the sales bot',
        'main_menu_text': (
            '✨ <b>{welcome_intro}</b>\n{divider}\n'
            '🔒 WireGuard only: <b>{wireguard_price}</b> Toman/GB\n'
            '⚙️ Config only: <b>{config_price}</b> Toman/GB\n'
            '🔀 Both: <b>{both_price}</b> Toman/GB\n'
            '📱 OpenVPN only: <b>{openvpn_price}</b> Toman/GB\n'
            '🎮 Gaming DNS only: <b>{dns_price}</b> Toman/GB\n'
            '💳 Wallet balance: <b>{wallet}</b> Toman'
        ),
        'svc_wireguard': '🔒 WireGuard only', 'svc_config': '⚙️ Config only',
        'svc_both': '🔀 Both', 'svc_openvpn': '📱 OpenVPN only', 'svc_dns': '🎮 Gaming DNS only',
        'buy_menu_text': (
            '🛍 Please choose the service type you want:\n{divider}\n'
            '🔒 WireGuard only: <b>{wireguard_price}</b> Toman/GB\n'
            '⚙️ Config only: <b>{config_price}</b> Toman/GB\n'
            '🔀 Both: <b>{both_price}</b> Toman/GB\n'
            '📱 OpenVPN only: <b>{openvpn_price}</b> Toman/GB\n'
            '🎮 Gaming DNS only: <b>{dns_price}</b> Toman/GB\n\n'
            '💳 Current balance: <b>{wallet}</b> Toman'
        ),
        'qty_screen': (
            '📦 <b>{ctype_label}</b>\n'
            'Per GB: <b>{price_per_gb}</b> Toman\n'
            '💳 Balance: <b>{wallet}</b> Toman\n\n'
            'Adjust the volume and duration with the +/- buttons:\n\n'
            '💰 Current price: <b>{price}</b> Toman'
        ),
        'qty_continue': '✅ Continue',
        'ask_label_prompt': '🏷 Send a custom name for this config:',
        'ask_label_skip': '➡️ Skip (use default name)',
        'invoice_title': '🧾 <b>Purchase Invoice</b>',
        'invoice_type': '📦 Service type: <b>{ctype_label}</b>',
        'invoice_volume': '📶 Volume: <b>{gb}</b> GB',
        'invoice_name': '🏷 Name: <b>{label}</b>',
        'invoice_duration': '⏳ Duration: <b>{days}</b> day(s)',
        'invoice_discount_line': '🎟 Discount code: <b>{code}</b> ({percent}%)',
        'invoice_base_price': '💵 Invoice amount: <s>{base_price:,}</s> Toman',
        'invoice_final_price': '💰 Final amount: <b>{price:,}</b> Toman',
        'invoice_price': '💵 Amount payable: <b>{price:,}</b> Toman',
        'invoice_footer': 'Tap "✅ Confirm" to pay, or apply a discount code first if you have one.',
        'btn_confirm_purchase': '✅ Confirm',
        'btn_cancel_purchase': '❌ Cancel Purchase',
        'btn_apply_discount': '🎟 Apply Discount Code',
        'discount_ask_prompt': '🎟 Please send the discount code:',
        'discount_invalid': '❌ Invalid discount code.',
        'discount_inactive': '⛔ This discount code has been deactivated.',
        'discount_capacity': '⚠️ This discount code has reached its usage limit.',
        'building_config': '⏳ Building your config, please wait...',
        'insufficient_balance': (
            '⚠️ <b>Your wallet balance is insufficient.</b>\n{divider}\n'
            '💳 Your current balance: <b>{wallet:,}</b> Toman\n'
            '💰 This purchase amount: <b>{price:,}</b> Toman\n'
            '📉 Shortfall: <b>{shortfall:,}</b> Toman\n\n'
            "If you'd like to get this config, please top up your wallet first:"
        ),
        'purchase_success': (
            '🎉 <b>Your config was created successfully</b>\n{divider}\n'
            '📦 Service type: <b>{ctype_label}</b>\n'
            '📶 Volume: <b>{gb}</b> GB\n'
            '🏷 Name: <b>{label}</b>\n'
            '⏳ Duration: <b>{days}</b> day(s)\n'
            '💵 Price: <b>{price:,}</b> Toman\n{divider}\n'
            '{output_label}\n<code>{sub_url}</code>'
        ),
        'output_label_wireguard': '📄 WireGuard config:',
        'output_label_openvpn': '📄 OpenVPN file:',
        'output_label_default': '🔗 Subscription link:',
        'proto_unavailable': (
            '⛔ Sales for "{ctype_label}" are currently closed by the panel.\n'
            'Please choose a different service type or try again later.\n'
            '(No amount was deducted from your wallet.)'
        ),
        'dns_unavailable': (
            '⛔ The "{ctype_label}" service is currently off on the platform or your servers.\n'
            'Please choose a different service type or try again later.\n'
            '(No amount was deducted from your wallet.)'
        ),
        'server_error': '❌ Error connecting to the panel server. Please try again.',
        'config_not_found': '⚠️ This config was not found.',
        'myconfigs_header': '🗂 <b>Your Configs</b>',
        'myconfigs_status_active': '🟢 Active',
        'myconfigs_status_paused': '⚪ Paused',
        'myconfigs_status_expired': '🔴 Expired',
        'myconfigs_card': (
            '<b>{idx}. {label}</b> {status}\n'
            '{bar}\n'
            '📶 Remaining out of {gb} GB: <b>{remaining_gb}</b> GB\n'
            '📊 Used: <b>{used_gb}</b> GB\n'
            '⏳ Days remaining: <b>{remaining_days}</b>\n'
            '📦 Service type: {ctype_label}\n'
            '🔗 <code>{sub_url}</code>'
        ),
        'myconfigs_usage_unknown': "📊 This config's usage can't be checked from the panel right now.",
        'btn_manage_config': '⚙️ Manage #{idx} — {label}',
        'manage_title': '⚙️ <b>Manage Config</b>',
        'manage_name': '🏷 Name: <b>{label}</b>',
        'manage_volume': '📶 Volume: <b>{gb}</b> GB',
        'manage_duration': '⏳ Duration: <b>{days}</b> day(s)',
        'manage_status_active': '▶️ Status: <b>Active</b>\n',
        'manage_status_paused': '⏸ Status: <b>Paused</b>\n',
        'manage_footer': 'Choose one of the actions below:',
        'btn_extend': '➕ Extend (GB/days)',
        'btn_rename': '✏️ Rename',
        'btn_qr': '📷 Get QR Code',
        'btn_pause': '⏸ Pause',
        'btn_resume': '▶️ Resume',
        'btn_rotate': '🔄 Rotate Link',
        'btn_close': '❌ Close',
        'ext_ask_gb': '➕ How many GB should be added to this config? (send a number only)',
        'ext_ask_days': '⏳ How many days should be added to the validity period? (send a number only)',
        'ext_number_error': '⚠️ Please enter a number greater than zero.',
        'ext_confirm_title': (
            '🧾 <b>Confirm Config Extension</b>\n{divider}\n'
            '🏷 Name: <b>{label}</b>\n'
            '➕ Extra volume: <b>{extra_gb}</b> GB\n'
            '⏳ Extra duration: <b>{extra_days}</b> day(s)\n'
            '💵 Cost: <b>{price:,}</b> Toman'
        ),
        'btn_confirm_pay': '✅ Confirm & Pay',
        'ext_success': '✅ Config "{label}" was extended: +{extra_gb} GB, +{extra_days} day(s) — <b>{price:,}</b> Toman was deducted.',
        'ext_panel_error': '❌ Error extending the config on the panel. Please try again later.',
        'ext_cancelled': '❌ Extension cancelled.',
        'ext_insufficient': '⚠️ Your wallet balance is insufficient.',
        'rename_ask': '✏️ Please send the new name for the config:',
        'rename_empty_error': '⚠️ The name cannot be empty.',
        'rename_success_new_url': '✅ The config name was changed to "{label}".\n🔗 Updated link:\n<code>{sub_url}</code>\n\n⚠️ Please enter this new link in your app again.',
        'rename_success_no_url': '✅ The config name was changed to "{label}".\nTap "🗂 My Configs" again to see the current link.',
        'rename_panel_error': '❌ Error renaming on the panel. Please try again later.',
        'qr_not_available': '❌ QR Code generation is not enabled on the server.\nThe admin needs to install the required library.',
        'qr_caption': '📷 <b>QR Code for "{label}"</b>\n{divider}\n🔗 <code>{sub_url}</code>',
        'qr_error': '❌ Error generating the QR Code. Please try again.',
        'pause_success': '⏸ Config "{label}" was paused.',
        'pause_error': '❌ Error pausing the config. Please try again later.',
        'resume_success': '▶️ Config "{label}" was resumed.',
        'resume_error': '❌ Error resuming the config. Please try again later.',
        'rotate_success': '🔄 The link for config "{label}" was changed:\n<code>{sub_url}</code>',
        'rotate_success_no_url': '🔄 The link was changed; tap "My Configs" again to see the new link.',
        'rotate_error': '❌ Error changing the link. Please try again later.',
        'myconfigs_empty': "📭 You haven't registered any configs yet.",
        'delete_prompt': '🗑 Send the row number of the config you want to delete:',
        'delete_empty': '📭 There are no configs to delete.',
        'delete_invalid_index': '⚠️ Invalid row number.',
        'delete_confirm_title': (
            '🗑 <b>Confirm Config Deletion</b>\n{divider}\n'
            '🏷 Name: <b>{label}</b>\n'
            '📶 Purchased volume: <b>{gb}</b> GB\n'
            '📊 Used: <b>{used_gb}</b> GB\n'
            '💵 Purchase price: <b>{price:,}</b> Toman\n{divider}\n'
            '💰 Amount refunded to your wallet (half of the remaining value): <b>{refund:,}</b> Toman\n\n'
            '{usage_note}'
            'This action cannot be undone. Are you sure you want to delete this config?'
        ),
        'delete_usage_unknown': "⚠️ This config's usage could not be checked on the panel; no amount will be refunded, to be safe.\n\n",
        'btn_delete_yes': '✅ Yes, delete it',
        'delete_row_number_error': '⚠️ Please enter only the row number.',
        'delete_success': '✅ The config was deleted and <b>{refund:,}</b> Toman was added to your wallet.',
        'delete_success_no_refund': '✅ The config was deleted.',
        'delete_panel_error': '⚠️ Error deleting the config. Please try again.',
        'delete_cancelled': '❌ Deletion cancelled.',
        'trial_used': "⚠️ You've already used your free trial.",
        'trial_used_on_panel': "⚠️ You've already received a free trial before.",
        'trial_building': '⏳ Building your trial config...',
        'trial_ready': (
            '🎁 <b>Your free trial config is ready</b>\n{divider}\n'
            '📶 Volume: <b>{trial_gb}</b> GB\n'
            '⏳ Validity: <b>{trial_days}</b> day(s)\n{divider}\n'
            '🔗 Subscription link:\n<code>{sub_url}</code>'
        ),
        'trial_error': '❌ Error creating the trial config. Please try again later.',
        'topup_prompt': '💠 Enter the amount (in Toman) you want to top up your wallet with.\nMinimum top-up amount: <b>{min_topup}</b> Toman',
        'topup_card_info': (
            '💳 <b>Payment Info</b>\n{divider}\n'
            '💵 Amount: <b>{amount}</b> Toman\n'
            '💳 Card number: <code>{card_number}</code>\n'
            '👤 Card holder: <b>{card_owner}</b>\n\n'
            '📸 After paying, send a photo of the receipt so it can be reviewed by support.'
        ),
        'topup_min_error': '⚠️ The minimum top-up amount is <b>{min_topup:,}</b> Toman.',
        'topup_amount_error': '⚠️ Please enter the amount as a number (Toman) only.',
        'number_only_error': '⚠️ Please enter a number only.',
        'topup_need_photo': '📸 Please send a photo of the deposit receipt.',
        'topup_receipt_ok': '✅ Your receipt was received and sent for review. Your wallet will be topped up once approved.',
        'account_info': (
            '👤 <b>Your Account</b>\n{divider}\n'
            '🆔 ID: <code>{chat_id}</code>\n'
            '💳 Wallet balance: <b>{wallet}</b> Toman\n'
            '📊 Total purchased: <b>{total_gb}</b> GB\n'
            '💵 Total paid: <b>{total_price}</b> Toman'
        ),
        'support_prompt': '🎧 Please send your message for support:',
        'support_ticket_created': '✅ Your message was registered with ticket #{tid} and will be answered soon.',
        'recentorders_header': '🧾 <b>Your 3 Most Recent Orders</b>',
        'recentorders_empty': "📭 You haven't placed any orders yet.",
        'recentorders_item': '<b>{idx}. {label}</b> — {gb} GB — {days} day(s) — {ctype_label}\n💵 Amount paid: <b>{price:,}</b> Toman',
        'btn_reorder': '🔁 Reorder #{idx}',
        'reorder_not_found': '⚠️ This order was not found.',
        'lang_prompt': '🌐 Please choose your preferred language:',
        'lang_btn_fa': '🇮🇷 فارسی',
        'lang_btn_en': '🇬🇧 English',
        'lang_changed': '✅ The bot language was changed to English.',
        'btn_guide': '📲 Config App',
        'guide_text': (
            '📲 <b>V2Pro connection app</b>\n{divider}\n'
            'Use this app to import and manage your configs, DNS and every service you buy from the bot.\n\n'
            'Choose the version for your device 👇'
        ),
        'guide_fallback_title': '📲 <b>V2Pro download links</b>',
        'plat_android': '🤖 Android',
        'plat_ios': '🍎 iPhone (iOS)',
        'plat_windows': '🪟 Windows',
        'plat_mac': '💻 macOS',
        'plat_linux': '🐧 Linux',
        'support_reply_received': '📩 Support reply for ticket #{tid}:\n\n{reply_text}',
    },
}


# متن‌های تازه‌ای که قبلاً مستقیم تو کد بودن (پیام‌های ادمین، تایید/رد شارژ،
# خطوط جدول قیمت فروشندگی، پیام «قابلیت غیرفعاله» و ...). حالا همه از پنل
# قابل‌ویرایشن.
UI_TEXT['fa'].update({
    'disabled_feature': '⛔ این قابلیت در حال حاضر توسط مدیریت غیرفعال شده است.',
    'price_unit_suffix': ' تومان/گیگ',
    'price_range': '{low} تا {high}',
    'tier_line_first': '• تا {limit} گیگ: <b>{rate}</b> تومان',
    'tier_line_range': '• {prev} تا {limit} گیگ: <b>{rate}</b> تومان',
    'tier_line_last': '• {prev} گیگ به بالا: <b>{rate}</b> تومان',
    'reseller_status_active': 'فعال ✅',
    'reseller_status_blocked': 'مسدود ⛔️',
    'btn_reseller': '🧑‍💼 فروشنده شو',
    'topup_approved_mult': '✅ کیف پول شما به مبلغ <b>{credited}</b> تومان شارژ شد (واریزی {amount} تومان × ضریب {multiplier}).',
    'topup_approved': '✅ کیف پول شما به مبلغ <b>{credited}</b> تومان شارژ شد.',
    'topup_rejected': '❌ رسید واریز شما رد شد. لطفاً با پشتیبانی در ارتباط باشید.',
    'no_username': 'بدون یوزرنیم',
    'config_note': 'تاریخ ساخت: {jalali_date} | ساعت: {time} | آیدی عددی: {chat_id} | یوزرنیم: {username} | مبلغ پرداختی: {price} تومان',
    'admin_ticket_new': '🎫 <b>تیکت جدید #{tid}</b>\n{divider}\n👤 کاربر: <code>{user_id}</code>\n\n{message}',
    'admin_btn_reply': '✍️ پاسخ',
    'admin_btn_close': '🔒 بستن',
    'admin_reply_prompt': '✍️ پاسخ تیکت #{tid} را ارسال کنید:',
    'admin_ticket_closed': '🔒 تیکت #{tid} بسته شد.',
    'admin_ticket_replied': '✅ پاسخ برای کاربر ارسال شد.',
    'admin_ticket_not_found': '⚠️ تیکت یافت نشد.',
    'admin_topup_request': '💳 <b>درخواست شارژ کیف پول</b>\n{divider}\n👤 کاربر: <code>{user_id}</code>\n💵 مبلغ: <b>{amount}</b> تومان\n🎫 شناسه درخواست: <b>{req_id}</b>',
    'admin_btn_accept': '✅ تایید',
    'admin_btn_reject': '❌ رد کردن',
    'admin_topup_approved': '✅ درخواست شارژ #{req_id} تایید شد — {credited} تومان به کیف پول کاربر اضافه شد.',
    'admin_topup_rejected': '❌ درخواست #{req_id} رد شد.',
    'admin_already_reviewed': '⚠️ این درخواست قبلاً بررسی شده یا وجود ندارد.',
})
UI_TEXT['fa'].update({
    'topup_choose_method': '💠 مبلغ شارژ: <b>{amount}</b> تومان\nروش پرداخت رو انتخاب کنید:',
    'btn_topup_card': '💳 کارت به کارت',
    'btn_topup_crypto': '🪙 پرداخت با رمزارز',
    'topup_choose_coin': '🪙 با کدوم رمزارز پرداخت می‌کنید؟',
    'topup_choose_method_first': '💠 شارژ کیف پول\nروش پرداخت رو انتخاب کنید:',
    'topup_crypto_info': (
        '🪙 <b>پرداخت با رمزارز</b>\n{divider}\n'
        '💵 مبلغ شارژ: <b>{amount}</b> تومان\n'
        '📈 قیمت لحظه‌ای {coin}: <b>{price}</b> تومان\n'
        '🔢 مقدار قابل واریز: <code>{coin_amount}</code> <b>{coin}</b>\n\n'
        '{network_line}👛 آدرس ولت:\n<code>{wallet}</code>\n{memo_line}\n'
        '⚠️ دقیقاً همین مقدار رو واریز کنید. قیمت لحظه‌ایه و ممکنه عوض بشه؛ پس زودتر واریز کنید.\n\n'
        '🔎 بعد از واریز، فقط «هش تراکنش (Hash)» رو به‌صورت متن بفرستید (نیازی به عکس نیست). بات خودش واریز رو تو نوبیتکس پیدا و بررسی می‌کنه.'
    ),
    'topup_crypto_need_proof': '🔎 لطفاً فقط هش تراکنش (Hash) رو به‌صورت متن بفرستید (عکس لازم نیست). هش باید یه متن پیوسته و بدون فاصله باشه.',
    'btn_send_hash': '🔎 ارسال هش تراکنش',
    'topup_receipt_ok_crypto_hint': '\n\n⏳ اگه واریزتون خودکار تأیید نشد، هر زمان خواستید می‌تونید هش رو دوباره (یا اصلاح‌شده) بفرستید تا دوباره بررسی بشه.',
    'topup_hash_prompt': '🔎 هش تراکنش (Hash) واریزتون رو بفرستید (یه متن پیوسته و بدون فاصله).',
    'topup_hash_received': '✅ هش دریافت شد و در حال بررسیه. اگه با واریز خودتون بخونه خودکار تأیید می‌شه، وگرنه ادمین دستی بررسی می‌کنه.',
    'topup_hash_no_pending': '⚠️ درخواست شارژ رمزارزیِ در انتظاری ندارید.',
    'topup_crypto_price_error': '❌ الان نتونستم قیمت لحظه‌ای رو بگیرم. چند لحظه دیگه دوباره امتحان کنید یا کارت به کارت بزنید.',
    'btn_exchange': '💱 صرافی',
    'exchange_prompt': '💱 <b>صرافی</b>\n{divider}\nمبلغ مورد نظرت رو به <b>تومان</b> بنویس (مثلاً <code>100000</code>) تا بگم با اون مبلغ از هر ارز چقدر می‌شه خرید.',
    'exchange_bad_amount': '⚠️ مبلغ رو فقط با عدد و به تومان بنویس؛ مثلاً <code>100000</code>',
    'exchange_result': '💱 <b>با {amount} تومان می‌تونی بخری:</b>\n{divider}\n{lines}\n{divider}\n📈 بر اساس قیمت لحظه‌ای نوبیتکس؛ مقدارها تقریبی‌ان و ممکنه با قیمت لحظه‌ی خرید کمی فرق کنه.',
    'exchange_line': '🪙 <b>{coin}</b>: <code>{qty}</code>\n      (قیمت هر واحد: {price} تومان)',
    'exchange_line_err': '🪙 <b>{coin}</b>: ⚠️ الان قیمت در دسترس نیست',
    'exchange_no_price': '❌ الان نتونستم قیمت‌ها رو از نوبیتکس بگیرم. چند لحظه دیگه دوباره امتحان کن.',
    'btn_exchange_again': '🔄 مبلغ دیگه',
    'topup_crypto_info2': (
        '🪙 <b>پرداخت با رمزارز</b>\n{divider}\n'
        '{network_line}👛 آدرس ولت ({coin}):\n<code>{wallet}</code>\n{memo_line}\n'
        '💵 حداقل شارژ: <b>{min_topup}</b> تومان\n\n'
        '✅ هر مقداری که می‌خوای شارژ کنی رو واریز کن (لازم نیست مبلغ خاصی باشه).\n\n'
        '🔢 بعد از واریز، «مقداری که فرستادی» رو دقیقاً همین‌جا برای بات بنویس؛ مثلاً:\n<code>0.2 {symbol}</code>\n\n'
        'بات معادل تقریبی تومانی رو نشون می‌ده و واریز رو تو نوبیتکس چک می‌کنه.'
    ),
    'topup_crypto_bad_amount': '⚠️ مقدار رو درست نفهمیدم. فقط عدد (و در صورت دلخواه اسم ارز) بنویسید؛ مثلاً: <code>0.2 {symbol}</code>',
    'topup_crypto_coin_mismatch': '⚠️ شما ارز <b>{coin}</b> رو انتخاب کردید ولی تو پیامتون ارز دیگه‌ای نوشتید. فقط مقدار {coin} رو بفرستید؛ مثلاً: <code>0.2 {symbol}</code>',
    'topup_crypto_below_min': '⚠️ این مقدار معادل حدود <b>{amount}</b> تومانه که کمتر از حداقل شارژ (<b>{min_topup}</b> تومان) هست و شارژ نمی‌شه. اگه قبلاً واریز کردید با پشتیبانی تماس بگیرید.',
    'topup_crypto_declared': '✅ دریافت شد: <code>{coin_amount}</code> {coin}\n💵 معادل تقریبی: حدود <b>{amount}</b> تومان\n📈 (قیمت لحظه‌ای {price} تومان)\n\n🔎 در حال بررسی واریز تو نوبیتکس...',
    'topup_crypto_ask_hash': '⏳ هنوز این واریز تو نوبیتکس پیدا نشد (ممکنه تأییدیه شبکه کامل نشده باشه).\n\n🔎 لطفاً «هش تراکنش (Hash)» رو همین‌جا به‌صورت متن بفرستید تا با هش چک کنم. تا چند ساعت هم خودکار دوباره چک می‌شه.',
    'topup_crypto_unconfirmed': '⏳ واریزتون تو نوبیتکس پیدا شد ولی هنوز تأیید نهایی شبکه رو نگرفته. به محض تأیید، کیف پولتون خودکار شارژ می‌شه.',
    'topup_crypto_found_wait_admin': '✅ واریزتون تو نوبیتکس پیدا شد. منتظر تأیید ادمین باشید؛ بعد از تأیید کیف پولتون شارژ می‌شه.',
    'topup_crypto_not_found_admin': '❌ با این هش هم واریزی پیدا نشد.\n\n🕐 منتظر تأیید دستی ادمین باشید. اگه واریز کردید، بعد از بررسی شارژ می‌شه. (تا چند ساعت هم خودکار دوباره چک می‌شه.)',
    'admin_topup_request_crypto': '🪙 <b>درخواست شارژ با رمزارز</b>\n{divider}\n👤 کاربر: <code>{user_id}</code>\n💵 مبلغ: <b>{amount}</b> تومان\n🔢 باید واریز شده باشه: <b>{coin_amount} {coin}</b>\n📈 قیمت زمان درخواست: {price} تومان\n🎫 شناسه درخواست: <b>{req_id}</b>',
})
UI_TEXT['en'].update({
    'topup_choose_method': '💠 Top-up amount: <b>{amount}</b> Toman\nChoose a payment method:',
    'btn_topup_card': '💳 Card to card',
    'btn_topup_crypto': '🪙 Pay with crypto',
    'topup_choose_coin': '🪙 Which cryptocurrency do you want to pay with?',
    'topup_choose_method_first': '💠 Wallet top-up\nChoose a payment method:',
    'topup_crypto_info': (
        '🪙 <b>Pay with crypto</b>\n{divider}\n'
        '💵 Top-up amount: <b>{amount}</b> Toman\n'
        '📈 Live {coin} price: <b>{price}</b> Toman\n'
        '🔢 Amount to send: <code>{coin_amount}</code> <b>{coin}</b>\n\n'
        '{network_line}👛 Wallet address:\n<code>{wallet}</code>\n{memo_line}\n'
        '⚠️ Send exactly this amount. The price is live and may change, so please send soon.\n\n'
        '🔎 After sending, just send the transaction hash as text (no screenshot needed). The bot will find and verify the deposit automatically.'
    ),
    'topup_crypto_need_proof': '🔎 Please send only the transaction hash as text (no photo needed). The hash must be a single continuous text with no spaces.',
    'btn_send_hash': '🔎 Send transaction hash',
    'topup_receipt_ok_crypto_hint': '\n\n⏳ If your deposit is not confirmed automatically, you can send the transaction hash at any time and it will be checked again.',
    'topup_hash_prompt': '🔎 Send the transaction hash of your deposit (a single continuous text with no spaces).',
    'topup_hash_received': '✅ Hash received and being checked. If it matches your deposit it will be confirmed automatically; otherwise the admin will review it manually.',
    'topup_hash_no_pending': "⚠️ You don't have a pending crypto top-up request.",
    'topup_crypto_price_error': '❌ Could not fetch the live price right now. Try again in a moment or use card to card.',
    'btn_exchange': '💱 Exchange',
    'exchange_prompt': '💱 <b>Exchange</b>\n{divider}\nType the amount in <b>Toman</b> (e.g. <code>100000</code>) and I will show how much of each coin it can buy.',
    'exchange_bad_amount': '⚠️ Send the amount as a number in Toman, e.g. <code>100000</code>',
    'exchange_result': '💱 <b>With {amount} Toman you can buy:</b>\n{divider}\n{lines}\n{divider}\n📈 Based on the live Nobitex price; amounts are approximate and may differ slightly at purchase time.',
    'exchange_line': '🪙 <b>{coin}</b>: <code>{qty}</code>\n      (price per unit: {price} Toman)',
    'exchange_line_err': '🪙 <b>{coin}</b>: ⚠️ price unavailable right now',
    'exchange_no_price': '❌ Could not fetch prices from Nobitex right now. Please try again in a moment.',
    'btn_exchange_again': '🔄 Another amount',
    'topup_crypto_info2': (
        '🪙 <b>Pay with crypto</b>\n{divider}\n'
        '{network_line}👛 Wallet address ({coin}):\n<code>{wallet}</code>\n{memo_line}\n'
        '💵 Minimum top-up: <b>{min_topup}</b> Toman\n\n'
        '✅ Send any amount you like (it does not have to be a specific number).\n\n'
        '🔢 After sending, write the exact amount you sent here, for example:\n<code>0.2 {symbol}</code>\n\n'
        'The bot shows the approximate Toman value and checks the deposit on Nobitex.'
    ),
    'topup_crypto_bad_amount': '⚠️ I could not read that amount. Send just a number (optionally with the coin name), e.g. <code>0.2 {symbol}</code>',
    'topup_crypto_coin_mismatch': '⚠️ You selected <b>{coin}</b> but wrote a different coin. Send only the {coin} amount, e.g. <code>0.2 {symbol}</code>',
    'topup_crypto_below_min': '⚠️ This amount is about <b>{amount}</b> Toman, below the minimum top-up (<b>{min_topup}</b> Toman), so it cannot be credited. If you already sent it, please contact support.',
    'topup_crypto_declared': '✅ Received: <code>{coin_amount}</code> {coin}\n💵 Approximate value: about <b>{amount}</b> Toman\n📈 (live price {price} Toman)\n\n🔎 Checking the deposit on Nobitex...',
    'topup_crypto_ask_hash': '⏳ This deposit has not shown up on Nobitex yet (network confirmations may still be pending).\n\n🔎 Please send the transaction hash here as text so I can check it by hash. It will also be re-checked automatically for a few hours.',
    'topup_crypto_unconfirmed': '⏳ Your deposit was found on Nobitex but is not finally confirmed by the network yet. Your wallet will be topped up automatically once it is.',
    'topup_crypto_found_wait_admin': '✅ Your deposit was found on Nobitex. Please wait for admin approval; your wallet will be topped up afterwards.',
    'topup_crypto_not_found_admin': '❌ No deposit was found with this hash either.\n\n🕐 Please wait for manual admin approval. If you sent the funds, your wallet will be topped up after review. (It is also re-checked automatically for a few hours.)',
})
UI_TEXT['en'].update({
    'disabled_feature': '⛔ This feature is currently disabled by the administrator.',
    'price_unit_suffix': ' Toman/GB',
    'price_range': '{low} to {high}',
    'tier_line_first': '• Up to {limit} GB: <b>{rate}</b> Toman',
    'tier_line_range': '• {prev} to {limit} GB: <b>{rate}</b> Toman',
    'tier_line_last': '• {prev} GB and above: <b>{rate}</b> Toman',
    'reseller_status_active': 'Active ✅',
    'reseller_status_blocked': 'Blocked ⛔️',
    'btn_reseller': '🧑‍💼 Become a Reseller',
    'topup_approved_mult': '✅ Your wallet was topped up by <b>{credited}</b> Toman (deposit {amount} Toman × multiplier {multiplier}).',
    'topup_approved': '✅ Your wallet was topped up by <b>{credited}</b> Toman.',
    'topup_rejected': '❌ Your deposit receipt was rejected. Please contact support.',
})

# متن‌های عضویت اجباری در کانال
UI_TEXT['fa'].update({
    'join_required': (
        '📢 <b>عضویت در کانال</b>\n{divider}\n'
        'برای استفاده از ربات، اول باید عضو کانال(های) زیر بشید.\n\n'
        'بعد از عضویت، به ربات برگردید و دکمه‌ی «✅ عضو شدم» رو بزنید.'
    ),
    'btn_join_channel': '📢 عضویت در کانال',
    'btn_joined': '✅ عضو شدم',
    'join_not_yet': '⚠️ هنوز عضو همه‌ی کانال‌ها نشدید. کانال‌های زیر رو عضو بشید، بعد دکمه‌ی «✅ عضو شدم» رو بزنید.',
    'join_check_error': '⚠️ الان نمی‌تونم عضویت شما رو بررسی کنم. چند لحظه دیگه دوباره «✅ عضو شدم» رو بزنید.',
    'join_ok': '✅ عضویت شما تأیید شد. خوش اومدید!',
})
UI_TEXT['fa'].update({
    'btn_referral': '🎁 دعوت دوستان',
    'referral_intro': (
        '🎁 <b>دعوت دوستان</b>\n{divider}\n'
        '{reward_line}\n\n'
        '🔗 لینک دعوت اختصاصی شما:\n<code>{link}</code>\n\n'
        '👥 دعوت‌شده‌ها: <b>{invited}</b>\n'
        '✅ پاداش‌گرفته‌ها: <b>{rewarded}</b>\n'
        '💰 مجموع پاداش شما: <b>{earned}</b> تومان'
    ),
    'referral_reward_line_purchase': '💰 هر دوستی که با لینک شما وارد ربات بشه و اولین خریدش رو انجام بده، <b>{amount}</b> تومان به کیف پول شما اضافه می‌شه.',
    'referral_reward_line_join': '💰 به‌ازای هر دوستی که با لینک شما وارد ربات بشه، <b>{amount}</b> تومان به کیف پول شما اضافه می‌شه.',
    'referral_invitee_bonus_line': '🎉 دوست شما هم <b>{bonus}</b> تومان هدیه می‌گیره.',
    'referral_link_unavailable': '⚠️ الان نمی‌تونم لینک دعوت رو بسازم. چند لحظه دیگه دوباره امتحان کنید.',
    'referral_reward_inviter': '🎉 یکی از دوستانتون که با لینک شما وارد شده بود اولین خریدش رو انجام داد!\n💰 <b>{amount}</b> تومان به کیف پول شما اضافه شد.',
    'referral_reward_inviter_join': '🎉 یه نفر با لینک شما وارد ربات شد!\n💰 <b>{amount}</b> تومان به کیف پول شما اضافه شد.',
    'referral_bonus_invitee': '🎁 به‌خاطر ورود با لینک دعوت، <b>{amount}</b> تومان هدیه به کیف پول شما اضافه شد.',
})
UI_TEXT['en'].update({
    'btn_referral': '🎁 Invite Friends',
    'referral_intro': (
        '🎁 <b>Invite friends</b>\n{divider}\n'
        '{reward_line}\n\n'
        '🔗 Your personal invite link:\n<code>{link}</code>\n\n'
        '👥 Invited: <b>{invited}</b>\n'
        '✅ Rewarded: <b>{rewarded}</b>\n'
        '💰 Total earned: <b>{earned}</b> Toman'
    ),
    'referral_reward_line_purchase': '💰 For every friend who joins with your link and makes their first purchase, <b>{amount}</b> Toman is added to your wallet.',
    'referral_reward_line_join': '💰 For every friend who joins with your link, <b>{amount}</b> Toman is added to your wallet.',
    'referral_invitee_bonus_line': '🎉 Your friend also gets <b>{bonus}</b> Toman as a gift.',
    'referral_link_unavailable': '⚠️ Could not build the invite link right now. Please try again in a moment.',
    'referral_reward_inviter': '🎉 A friend who joined with your link just made their first purchase!\n💰 <b>{amount}</b> Toman was added to your wallet.',
    'referral_reward_inviter_join': '🎉 Someone joined the bot with your link!\n💰 <b>{amount}</b> Toman was added to your wallet.',
    'referral_bonus_invitee': '🎁 You received <b>{amount}</b> Toman as a gift for joining with an invite link.',
})
UI_TEXT['en'].update({
    'join_required': (
        '📢 <b>Channel membership</b>\n{divider}\n'
        'To use this bot you must first join the channel(s) below.\n\n'
        'After joining, come back to the bot and tap "✅ I\'ve joined".'
    ),
    'btn_join_channel': '📢 Join the channel',
    'btn_joined': "✅ I've joined",
    'join_not_yet': "⚠️ You haven't joined all the channels yet. Join the ones below, then tap \"✅ I've joined\".",
    'join_check_error': "⚠️ I can't verify your membership right now. Please tap \"✅ I've joined\" again in a moment.",
    'join_ok': '✅ Your membership is confirmed. Welcome!',
})




# ---------------------------------------------------------------------------
# متن‌ها/دکمه‌هایی که قبلاً مستقیم تو کد بودن و از پنل قابل تغییر نبودن؛ حالا همه
# تو همین جدول‌ان و از صفحه‌ی «متن‌های ربات» پنل قابل ویرایش‌ان.
# ---------------------------------------------------------------------------
UI_TEXT['fa'].update({
    'btn_qty_minus': '➖',
    'btn_qty_plus': '➕',
    'kb_removed_note': '⌨️',
    'crypto_memo_line': '📝 Memo / Comment:\n<code>{memo}</code>\n\n⚠️ حتماً Memo رو هم دقیقاً بنویسید، وگرنه واریزی شناسایی نمی‌شه.',
    'crypto_network_line': '🌐 شبکه: <b>{network}</b>\n(حتماً از همین شبکه واریز کنید)',
    'reseller_creds_line': '👤 نام کاربری پنل: <code>{username}</code>',
    # --- پیام‌های ادمین ---
    'admin_btn_add_channel': '➕ اضافه کردن کانال',
    'admin_btn_send_number': '📱 ارسال شماره من',
    'admin_btn_channel_add': '➕ افزودن کانال جدید',
    'admin_btn_channel_del': '🗑 حذف {i}{name}',
    'admin_hash_sent': '🔗 کاربر <code>{user_id}</code> برای درخواست #{req_id} هش تراکنش فرستاد:\n<code>{tx_hash}</code>',
    'admin_topup_hash_line': '🔗 هش تراکنش (Hash):\n<code>{tx_hash}</code>',
    'admin_timing_title': '⏱ <b>زمان‌بندی</b>',
    'admin_timing_requested': '🕐 درخواست مبلغ واریزی: <code>{time}</code>',
    'admin_timing_requested_unknown': '🕐 درخواست مبلغ واریزی: نامشخص',
    'admin_timing_paid': '🕑 ارسال رسید/هش: <code>{time}</code>',
    'admin_timing_elapsed': '⌛️ مدت از درخواست تا واریز: <b>{duration}</b>',
    'admin_dur_hour': '{n} ساعت',
    'admin_dur_minute': '{n} دقیقه',
    'admin_dur_second': '{n} ثانیه',
    'admin_dur_and': 'و',
    'admin_auto_approved_hash': '🤖 تأیید خودکار: هش تراکنش با واریز نوبیتکس خورد',
    'admin_auto_approved_amount': '🤖 تأیید خودکار: مقدار و زمان واریز با واریز نوبیتکس خورد (بدون هش)',
    'admin_ce_head': '🔎 <b>بررسی نوبیتکس</b> — درخواست #{req_id}',
    'admin_ce_error': '⚠️ بررسی انجام نشد: {note}\nدستی بررسی کنید.',
    'admin_ce_not_found': '⏳ هنوز واریز مطابقی پیدا نشد (ممکنه تأییدیه شبکه کامل نشده باشه). تا چند ساعت خودکار دوباره چک می‌شه.',
    'admin_ce_hash_mismatch_nodep': '⚠️ {note}\nدستی بررسی کنید.',
    'admin_ce_diff': '({pct}٪ نسبت به مقدار مورد انتظار)',
    'admin_ce_coin_suffix': '— کوین: {coin}',
    'admin_ce_hash_ok': '✅ هش تراکنش با یه واریز تو نوبیتکس خورد.',
    'admin_ce_matched': '✅ واریز هم‌مقدار پیدا شد (کاربر هش نفرستاده؛ تأیید با خودته).',
    'admin_ce_mismatch': '⚠️ واریزی پیدا شد ولی کوین/مقدار/زمانش با درخواست نمی‌خونه؛ دستی تصمیم بگیرید.',
    'admin_ce_hash_mismatch': '⚠️ {note}.',
    'admin_ce_ambiguous': '⚠️ {note}؛ دستی تأیید کنید.',
    'admin_ce_unconfirmed': '⏳ واریز پیدا شد ولی هنوز تأیید نهایی شبکه رو نگرفته.',
    'admin_ce_amount_line': '💰 مقدار واریز: <code>{amount}</code> {coin}{diff}\n🎯 مقدار مورد انتظار: <code>{expected}</code>',
    'admin_ce_hash_line': '🔗 هش: <code>{tx}</code>',
    'admin_ce_time_line': '🕐 زمان واریز: <code>{time}</code>',
    'admin_ce_note_no_coin': 'اطلاعات کوین این درخواست ثبت نشده',
    'admin_ce_note_hash_no_match': 'هش وارد‌شده با هیچ واریزی تو نوبیتکس نخورد',
    'admin_ce_note_hash_nearest': 'هش وارد‌شده با واریزی نخورد، نزدیک‌ترین واریز نشون داده شد',
    'admin_ce_note_competing': 'چند کاربر مقدار هم‌اندازه اعلام کردن؛ با هش یا دستی مشخص بشه',
    'admin_ce_note_multi': '{n} واریز هم‌مقدار پیدا شد',
})
UI_TEXT['en'].update({
    'btn_qty_minus': '➖',
    'btn_qty_plus': '➕',
    'kb_removed_note': '⌨️',
    'crypto_memo_line': '📝 Memo / Comment:\n<code>{memo}</code>\n\n⚠️ You must include this memo, otherwise the deposit cannot be identified.',
    'crypto_network_line': '🌐 Network: <b>{network}</b>\n(send only on this network)',
    'reseller_creds_line': '👤 Panel username: <code>{username}</code>',
})


# بعضی متن‌های فارسی از قبل تو پنل زیر کلیدهای قدیمی (text_*, ctype_label_*)
# ذخیره می‌شدن؛ برای اینکه سفارشی‌سازی‌های قبلی ادمین از بین نره، همون کلیدها
# رو نگه می‌داریم. بقیه‌ی متن‌ها: ui_<زبان>_<کلید>.
LEGACY_FA_SETTING = {
    'welcome_intro': 'text_welcome_intro',
    'main_menu_text': 'text_main_menu',
    'buy_menu_text': 'text_buy_menu',
    'account_info': 'text_account_info',
    'myconfigs_header': 'text_myconfigs_header',
    'myconfigs_empty': 'text_myconfigs_empty',
    'delete_prompt': 'text_delete_prompt',
    'delete_empty': 'text_delete_empty',
    'trial_used': 'text_trial_used',
    'trial_building': 'text_trial_building',
    'trial_ready': 'text_trial_ready',
    'trial_error': 'text_trial_error',
    'topup_prompt': 'text_topup_prompt',
    'topup_card_info': 'text_topup_card_info',
    'topup_need_photo': 'text_topup_need_photo',
    'topup_receipt_ok': 'text_topup_receipt_ok',
    'support_prompt': 'text_support_prompt',
    'support_ticket_created': 'text_support_ticket_created',
}


def ui_setting_key(lang, key):
    if lang == 'fa':
        return LEGACY_FA_SETTING.get(key, 'ui_fa_' + key)
    return 'ui_' + lang + '_' + key


def u(chat_id_or_lang, key, **kwargs):
    """متن ترجمه‌شده رو برمی‌گردونه؛ اولین آرگومان یا خودِ chat_id است یا مستقیم
    'fa'/'en'. اول override ذخیره‌شده از پنل ادمین (جدول settings) چک می‌شه؛
    اگه نبود یا قالبش خراب بود (placeholder اشتباه)، متن پیش‌فرض کد استفاده
    می‌شه. اگه کلید تو زبان فعلی نبود از فارسی و در نهایت از خودِ کلید."""
    lang = chat_id_or_lang if chat_id_or_lang in ('fa', 'en') else get_user_lang(chat_id_or_lang)
    table = UI_TEXT.get(lang, UI_TEXT['fa'])
    s = table.get(key)
    if s is None:
        s = UI_TEXT['fa'].get(key, key)
    override = get_setting(ui_setting_key(lang, key), None)
    if override:
        if not kwargs:
            return override
        try:
            return override.format(**kwargs)
        except Exception:
            pass
    if kwargs:
        try:
            return s.format(**kwargs)
        except Exception:
            return s
    return s


def admin_add_channel_label():
    return u('fa', 'admin_btn_add_channel')


def cancel_kb(chat_id):
    return {'inline_keyboard': [[{'text': u(chat_id, 'btn_cancel'), 'callback_data': 'menu'}]]}


def get_ctype_label(chat_id, ctype):
    """لیبل نوع سرویس: برای فارسی همون لیبل قابل‌تغییر از پنل ادمین، برای
    انگلیسی یه ترجمه‌ی ثابت (چون پنل ادمین فقط فارسی رو مدیریت می‌کنه)."""
    if get_user_lang(chat_id) == 'en':
        return u(chat_id, 'svc_' + ctype) if ('svc_' + ctype) in UI_TEXT['en'] else ctype
    return get_config_types().get(ctype, get_config_types()['both'])['label']

# ---------------------------------------------------------------------------
# HTTP session (keep-alive)
# ---------------------------------------------------------------------------
# قبلاً هر درخواست (requests.get/post) یه اتصال TCP+TLS تازه باز می‌کرد.
# وقتی سرور splus.ir یا شبکه بین راه‌وی و اون کند/پرلتنسی باشه (که با توجه به
# فیلترینگ/VPN طبیعیه)، این هندشیک تکراری روی هر پیام چند ثانیه اضافه می‌کنه.
# با یه Session مشترک، اتصال‌ها نگه‌داشته (keep-alive) و دوباره استفاده می‌شن.
SESSION = requests.Session()
_adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=40, max_retries=0)
SESSION.mount('https://', _adapter)
SESSION.mount('http://', _adapter)

# آپدیت‌های تلگرام (پیام/callback) به‌جای اجرای یکی‌یکی و پشت‌سرهم، تو این
# استخر ترد پردازش می‌شن. مهم‌ترین اثرش رو زمانی نشون می‌ده که یه کاربر یه کار
# کند (مثلاً ساخت/تمدید کانفیگ روی پنل که وابسته به شبکه‌ست) در حال انجامه:
# قبلاً تا اون تموم نمی‌شد، بات به هیچ پیام دیگه‌ای (حتی «/start» یه نفر دیگه)
# جواب نمی‌داد. max_workers=8 یعنی هم‌زمان حداکثر ۸ آپدیت می‌تونن پردازش بشن؛
# برای یه بات فروش با حجم معمولی کاربر، عدد امن و کافی‌ایه.
UPDATE_EXECUTOR = ThreadPoolExecutor(max_workers=16)

# کارهای فرعیِ «فایر-اند-فورگت» (مثل answerCallbackQuery یا رفرش کش تنظیمات) که
# نباید جواب اصلی به کاربر رو معطل کنن، تو یه استخر جدا اجرا می‌شن.
BG_EXECUTOR = ThreadPoolExecutor(max_workers=4)

# قفل جدا برای هر chat_id: دو آپدیت از یه کاربر واحد (مثلاً دوبار زدن سریع
# دکمه‌ی «تایید خرید») صف می‌شن و یکی‌یکی اجرا می‌شن؛ کاربرهای مختلف همچنان
# کاملاً موازی پردازش می‌شن.
_chat_locks = {}
_chat_locks_guard = threading.Lock()


def get_chat_lock(chat_id):
    with _chat_locks_guard:
        lock = _chat_locks.get(chat_id)
        if lock is None:
            lock = threading.Lock()
            _chat_locks[chat_id] = lock
        return lock

user_steps = {}


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

# هر ترد اتصال مخصوص خودش رو داره. قبلاً یه اتصال واحد بین ۸ ترد UPDATE_EXECUTOR
# مشترک بود؛ روی اتصال HTTP/stream مثل Turso، اگه دو ترد هم‌زمان روی یه اتصال
# execute/fetch بزنن، نتیجه‌ها می‌تونن قاطی یا خالی برگردن (مثلاً «سفارشی ثبت
# نکرده‌اید» با اینکه سفارش تو دیتابیس هست).
_db_local = threading.local()


def get_conn():
    conn = getattr(_db_local, 'conn', None)
    if conn is None:
        conn = turso_serverless.connect(TURSO_DATABASE_URL, auth_token=TURSO_AUTH_TOKEN)
        conn.close = lambda: None  # close() فراخوانی‌های قدیمی رو بی‌اثر می‌کنیم
        _db_local.conn = conn
    return conn


def reset_conn():
    _db_local.conn = None


def with_db_retry(func):
    """اگه stream اتصال Turso به‌خاطر بی‌کاری منقضی شده باشه (خطای 404 'stream not
    found')، اتصال رو ریست می‌کنه و همون عملیات رو یک بار دیگه اجرا می‌کنه؛ برای
    هر خطای دیگه، خطا رو دوباره پرتاب می‌کنه تا رفتار قبلی حفظ بشه."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            msg = str(e).lower()
            if 'stream not found' in msg or 'stream_expired' in msg or ('404' in msg and 'stream' in msg):
                print('♻️ اتصال دیتابیس (stream) منقضی شده بود؛ اتصال تازه ساخته و درخواست دوباره اجرا شد.')
                reset_conn()
                return func(*args, **kwargs)
            raise
    return wrapper


@with_db_retry
def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, wallet INTEGER DEFAULT 0)')
    c.execute('''CREATE TABLE IF NOT EXISTS user_configs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        sub_url TEXT,
        config_id TEXT,
        gb REAL,
        label TEXT,
        days INTEGER,
        price INTEGER,
        type TEXT,
        status TEXT DEFAULT 'active',
        created_at TEXT,
        expires_at TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message TEXT,
        status TEXT DEFAULT "open",
        admin_reply TEXT,
        created_at TEXT
    )''')
    # تاریخچه‌ی سفارش‌ها: جدا از user_configs است تا با حذف کانفیگ پاک نشود.
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        label TEXT,
        gb REAL,
        days INTEGER,
        price INTEGER,
        type TEXT,
        config_id TEXT,
        created_at TEXT
    )''')
    try:
        c.execute('CREATE INDEX IF NOT EXISTS idx_orders_user ON orders (user_id, id)')
    except Exception:
        pass
    # فروشندگی: هر فروشنده یه استخر گیگ داره (gb_balance) که با قیمت تخفیف‌دار
    # (get_reseller_price_per_gb()) پر می‌شه؛ سرویس API جدا (reseller_api.py) از همین
    # جدول‌ها می‌خونه/می‌نویسه، پس ساختشون اینجاست تا هر دو سرویس هم‌نظر باشن.
    c.execute("""CREATE TABLE IF NOT EXISTS resellers (
        user_id INTEGER PRIMARY KEY,
        api_key TEXT UNIQUE,
        secret_hash TEXT,
        gb_balance REAL DEFAULT 0,
        price_per_gb INTEGER DEFAULT 2000,
        status TEXT DEFAULT 'active',
        created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS reseller_pool_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        gb REAL,
        price INTEGER,
        created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS reseller_api_configs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reseller_id INTEGER,
        config_id TEXT,
        sub_url TEXT,
        gb REAL,
        days INTEGER,
        label TEXT,
        type TEXT,
        active INTEGER DEFAULT 1,
        created_at TEXT
    )""")
    try:
        c.execute('CREATE INDEX IF NOT EXISTS idx_reseller_cfg ON reseller_api_configs (reseller_id, id)')
    except Exception:
        pass
    c.execute('CREATE TABLE IF NOT EXISTS free_trials (user_id INTEGER PRIMARY KEY)')
    # سیستم دعوت (رفرال): هر کاربر دعوت‌شده فقط یک‌بار پاداش می‌ده (invitee_id کلید اصلیه)
    c.execute('''CREATE TABLE IF NOT EXISTS referral_rewards (
        invitee_id INTEGER PRIMARY KEY, inviter_id INTEGER, inviter_amount INTEGER DEFAULT 0,
        invitee_amount INTEGER DEFAULT 0, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS topup_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        status TEXT DEFAULT "pending",
        created_at TEXT
    )''')
    for _col in ("method TEXT DEFAULT 'card'", "crypto_amount TEXT", "crypto_price TEXT",
                 "coin_symbol TEXT", "coin_qty TEXT", "tx_hash TEXT", "matched_tx TEXT", "req_ts REAL"):
        try:
            c.execute('ALTER TABLE topup_requests ADD COLUMN ' + _col)
        except Exception:
            pass  # ستون از قبل هست
    c.execute('CREATE TABLE IF NOT EXISTS crypto_deposits_used (tx TEXT PRIMARY KEY, req_id INTEGER, created_at TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
    c.execute('''CREATE TABLE IF NOT EXISTS discount_codes (
        code TEXT PRIMARY KEY,
        percent INTEGER,
        max_uses INTEGER,
        used_count INTEGER DEFAULT 0,
        active INTEGER DEFAULT 1,
        created_at TEXT
    )''')
    for statement in (
        'ALTER TABLE users ADD COLUMN username TEXT',
        'ALTER TABLE users ADD COLUMN first_name TEXT',
        'ALTER TABLE users ADD COLUMN joined_at TEXT',
        'ALTER TABLE users ADD COLUMN last_active TEXT',
        'ALTER TABLE users ADD COLUMN last_action TEXT',
        'ALTER TABLE user_configs ADD COLUMN type TEXT',
        "ALTER TABLE user_configs ADD COLUMN status TEXT DEFAULT 'active'",
        'ALTER TABLE users ADD COLUMN kb_style TEXT',
        'ALTER TABLE users ADD COLUMN lang TEXT',
        'ALTER TABLE users ADD COLUMN referred_by INTEGER',
        "ALTER TABLE reseller_api_configs ADD COLUMN source TEXT DEFAULT 'api'",
        'ALTER TABLE resellers ADD COLUMN username TEXT',
        'ALTER TABLE resellers ADD COLUMN password_hash TEXT',
        'ALTER TABLE resellers ADD COLUMN password_plain TEXT',
    ):
        try:
            c.execute(statement)
        except Exception:
            pass
    try:
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_reseller_username ON resellers (username)')
    except Exception:
        pass
    # یک‌بار بک‌فیل: خریدهای قدیمیِ موجود تو user_configs (به‌جز تست رایگان) به
    # جدول orders کپی می‌شن تا سفارش‌های قبلی هم تو «سفارشات اخیر» بیان.
    try:
        c.execute('''INSERT INTO orders (user_id, label, gb, days, price, type, config_id, created_at)
            SELECT uc.user_id, uc.label, uc.gb, uc.days, uc.price, COALESCE(uc.type, 'both'), uc.config_id, uc.created_at
            FROM user_configs uc
            WHERE uc.price > 0 AND uc.config_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.config_id = uc.config_id AND o.user_id = uc.user_id)''')
    except Exception as e:
        print('⚠️ بک‌فیل جدول orders انجام نشد:', e)
    conn.commit()
    conn.close()


@with_db_retry
def get_wallet_db(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT wallet FROM users WHERE user_id=?', (user_id,))
    res = c.fetchone()
    conn.close()
    return res[0] if res else 0


_user_kb_cache = {}


def get_user_kb_style(user_id):
    """استایل کیبورد ذخیره‌شده‌ی کاربر؛ بعد از اولین خوندن تو حافظه کش می‌شه تا
    هر بار نمایش منوی اصلی یه کوئری اضافه به دیتابیس نزنه."""
    if user_id in _user_kb_cache:
        return _user_kb_cache[user_id]
    val = _get_user_kb_style_db(user_id)
    _user_kb_cache[user_id] = val
    return val


def set_user_kb_style(user_id, style):
    _set_user_kb_style_db(user_id, style)
    _user_kb_cache[user_id] = style


@with_db_retry
def _get_user_kb_style_db(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT kb_style FROM users WHERE user_id=?', (user_id,))
    res = c.fetchone()
    conn.close()
    return res[0] if res and res[0] else None


@with_db_retry
def _set_user_kb_style_db(user_id, style):
    conn = get_conn()
    c = conn.cursor()
    c.execute('UPDATE users SET kb_style=? WHERE user_id=?', (style, user_id))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# زبان کاربر (فارسی/انگلیسی) — هر کاربر یه زبان مستقل از بقیه انتخاب می‌کنه.
# چون این مقدار تقریباً روی هر پیامی خونده می‌شه (برای انتخاب متن/دکمه‌ها)،
# مثل تنظیمات، تو یه کش حافظه‌ای هم نگه داشته می‌شه تا هر پیام یه رفت‌وبرگشت
# اضافه به دیتابیس نزنه.
# ---------------------------------------------------------------------------
_user_lang_cache = {}


@with_db_retry
def _get_user_lang_db(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT lang FROM users WHERE user_id=?', (user_id,))
    res = c.fetchone()
    conn.close()
    return res[0] if res and res[0] else None


@with_db_retry
def _set_user_lang_db(user_id, lang):
    conn = get_conn()
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO users (user_id, wallet) VALUES (?, 0)', (user_id,))
    c.execute('UPDATE users SET lang=? WHERE user_id=?', (lang, user_id))
    conn.commit()
    conn.close()


def get_user_lang(user_id):
    """زبان فعلی کاربر رو برمی‌گردونه ('fa' یا 'en')؛ پیش‌فرض 'fa' است."""
    key = str(user_id)
    if key in _user_lang_cache:
        return _user_lang_cache[key]
    try:
        lang = _get_user_lang_db(user_id) or 'fa'
    except Exception:
        lang = 'fa'
    if lang not in ('fa', 'en'):
        lang = 'fa'
    _user_lang_cache[key] = lang
    return lang


def set_user_lang(user_id, lang):
    if lang not in ('fa', 'en'):
        return
    _set_user_lang_db(user_id, lang)
    _user_lang_cache[str(user_id)] = lang


@with_db_retry
def add_user(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO users (user_id, wallet, joined_at) VALUES (?, ?, ?)',
               (user_id, 0, datetime.now().isoformat()))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# سیستم دعوت (رفرال)
# لینک دعوت: https://splus.ir/<یوزرنیم بات>?start=ref_<آیدی عددی دعوت‌کننده>
# تنظیمات از پنل ادمین (بخش «دعوت دوستان»): referral_enabled, referral_reward_inviter,
# referral_reward_invitee, referral_on_join
# ---------------------------------------------------------------------------
def referral_enabled():
    return get_setting('referral_enabled', '0') == '1'


def _referral_int(key, default):
    try:
        return max(0, int(float(str(get_setting(key, str(default))).replace(',', ''))))
    except Exception:
        return default


def get_referral_reward_inviter():
    return _referral_int('referral_reward_inviter', 10000)


def get_referral_reward_invitee():
    return _referral_int('referral_reward_invitee', 0)


def referral_on_join():
    """0 = پاداش بعد از اولین خرید کاربر دعوت‌شده (پیش‌فرض)، 1 = همین که وارد ربات شد."""
    return get_setting('referral_on_join', '0') == '1'


def get_bot_username():
    """یوزرنیم بات برای ساخت لینک دعوت."""
    # یوزرنیم ثابت بات (می‌شه با متغیر محیطی BOT_USERNAME هم عوضش کرد)
    return (os.getenv('BOT_USERNAME', '') or 'SKYTUNNELbot').strip().lstrip('@')


def build_referral_link(user_id):
    name = get_bot_username()
    if not name:
        return None
    return f'https://splus.ir/{name}?start=ref_{user_id}'


@with_db_retry
def referral_user_exists(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT 1 FROM users WHERE user_id=?', (user_id,))
    row = c.fetchone()
    conn.close()
    return bool(row)


@with_db_retry
def register_referred_user(invitee_id, inviter_id):
    """هر کاربر (تازه یا قدیمی) فقط یک‌بار می‌تونه دعوت‌شده‌ی کسی بشه: اگه تو دیتابیس نباشه ردیفش با
    referred_by ساخته می‌شه، و اگه از قبل بوده ولی هنوز دعوت‌کننده‌ای نداره، همون‌جا ثبت می‌شه.
    کسی که قبلاً با لینک دعوت ثبت شده، با لینک بعدی عوض نمی‌شه."""
    conn = get_conn()
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO users (user_id, wallet, joined_at, referred_by) VALUES (?, 0, ?, ?)',
              (invitee_id, datetime.now().isoformat(), inviter_id))
    c.execute('UPDATE users SET referred_by=? WHERE user_id=? AND referred_by IS NULL', (inviter_id, invitee_id))
    conn.commit()
    conn.close()


@with_db_retry
def get_referrer(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT referred_by FROM users WHERE user_id=?', (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] else None


@with_db_retry
def referral_reward_given(invitee_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT 1 FROM referral_rewards WHERE invitee_id=?', (invitee_id,))
    row = c.fetchone()
    conn.close()
    return bool(row)


@with_db_retry
def save_referral_reward(invitee_id, inviter_id, inviter_amount, invitee_amount):
    conn = get_conn()
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO referral_rewards (invitee_id, inviter_id, inviter_amount, invitee_amount, created_at) '
              'VALUES (?, ?, ?, ?, ?)', (invitee_id, inviter_id, inviter_amount, invitee_amount, datetime.now().isoformat()))
    conn.commit()
    conn.close()


@with_db_retry
def get_referral_stats(inviter_id):
    """(تعداد دعوت‌شده‌ها, تعداد پاداش‌گرفته‌ها, مجموع پاداش به تومان)"""
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users WHERE referred_by=?', (inviter_id,))
    invited = (c.fetchone() or [0])[0] or 0
    c.execute('SELECT COUNT(*), COALESCE(SUM(inviter_amount), 0) FROM referral_rewards WHERE inviter_id=?', (inviter_id,))
    row = c.fetchone() or (0, 0)
    conn.close()
    return invited, row[0] or 0, row[1] or 0


def capture_referral(update):
    """قبل از هر چیز (حتی قبل از گیت عضویت اجباری) صدا زده می‌شه: اگه کاربر تازه با /start ref_<id>
    وارد شده باشه، دعوت‌کننده‌اش ثبت می‌شه."""
    try:
        msg = update.get('message') or {}
        text = (msg.get('text') or '').strip()
        if not text.startswith('/start ') or not referral_enabled():
            return
        payload = text.split(None, 1)[1].strip()
        if not payload.startswith('ref_') or not payload[4:].isdigit():
            return
        inviter = int(payload[4:])
        invitee = (msg.get('chat') or {}).get('id')
        if not invitee or inviter == invitee or not referral_user_exists(inviter):
            return
        if get_referrer(inviter) == invitee:   # دعوت دوطرفه (A→B و B→A) حساب نمی‌شه
            return
        register_referred_user(invitee, inviter)
    except Exception as e:
        print('⚠️ ثبت رفرال ناموفق بود:', e)


def process_referral_reward(invitee_id, event):
    """event: 'join' یا 'purchase'. فقط یک‌بار برای هر کاربر دعوت‌شده پاداش می‌ده."""
    try:
        if not referral_enabled():
            return
        if (event == 'join') != referral_on_join():
            return
        inviter = get_referrer(invitee_id)
        if not inviter or referral_reward_given(invitee_id):
            return
        a_inviter, a_invitee = get_referral_reward_inviter(), get_referral_reward_invitee()
        save_referral_reward(invitee_id, inviter, a_inviter, a_invitee)   # اول ثبت، تا دوبار پاداش نره
        if a_inviter > 0:
            update_wallet_db(inviter, a_inviter)
            send_message(inviter, u(inviter, 'referral_reward_inviter_join' if event == 'join' else 'referral_reward_inviter',
                                    amount=f'{a_inviter:,}'))
        if a_invitee > 0:
            update_wallet_db(invitee_id, a_invitee)
            send_message(invitee_id, u(invitee_id, 'referral_bonus_invitee', amount=f'{a_invitee:,}'))
    except Exception as e:
        print('⚠️ پاداش رفرال داده نشد:', e)


# ---------------------------------------------------------------------------
# بررسی خودکار واریز رمزارزی از روی حساب نوبیتکس (API Key فقط‌خواندنی)
# احراز هویت طبق مستندات نوبیتکس: هدرهای Nobitex-Key / Nobitex-Signature / Nobitex-Timestamp
# امضا = Ed25519 روی «timestamp + METHOD + full_path + raw_body» (URL-safe Base64)
# مقادیر از Environment (NOBITEX_API_KEY / NOBITEX_API_SECRET) خونده می‌شن؛ اگه نبودن همین مقادیر داخل کد استفاده می‌شه.
# ---------------------------------------------------------------------------
NOBITEX_API_KEY = (os.getenv('NOBITEX_API_KEY') or 'L6NkONpb_eLVYgPCME2ZK0uF0etCda0F7vJttsUw8ms=').strip()
NOBITEX_API_SECRET = (os.getenv('NOBITEX_API_SECRET') or '2dVf_2Xl9flVS_ZCtHMuQgC4wB_NVW8YNBySBtPLLZM=').strip()


# ---- Ed25519 (RFC 8032) خالص پایتون؛ فقط وقتی استفاده می‌شه که cryptography/pynacl نصب نباشه ----
_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _inv(x):
    return pow(x, _P - 2, _P)


def _xrecover(y):
    xx = (y * y - 1) * _inv(_D * y * y + 1)
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = (x * _I) % _P
    if x % 2 != 0:
        x = _P - x
    return x


_BY = (4 * _inv(5)) % _P
_B = (_xrecover(_BY), _BY)


def _add(a, b):
    (x1, y1), (x2, y2) = a, b
    t = _D * x1 * x2 * y1 * y2
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + t)
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - t)
    return (x3 % _P, y3 % _P)


def _mul(p, e):
    q = (0, 1)
    while e:
        if e & 1:
            q = _add(q, p)
        p = _add(p, p)
        e >>= 1
    return q


def _enc_int(y):
    return y.to_bytes(32, 'little')


def _enc_point(p):
    x, y = p
    return _enc_int(y | ((x & 1) << 255))


def _h(m):
    return hashlib.sha512(m).digest()


def _clamp(h):
    a = int.from_bytes(h[:32], 'little')
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a


def ed25519_public_key(seed):
    return _enc_point(_mul(_B, _clamp(_h(seed))))


def ed25519_sign(seed, msg):
    h = _h(seed)
    a = _clamp(h)
    pub = _enc_point(_mul(_B, a))
    r = int.from_bytes(_h(h[32:] + msg), 'little') % _L
    R = _enc_point(_mul(_B, r))
    k = int.from_bytes(_h(R + pub + msg), 'little') % _L
    s = (r + k * a) % _L
    return R + s.to_bytes(32, 'little')


def _ed_sign(seed, msg):
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519 as _ed
        return _ed.Ed25519PrivateKey.from_private_bytes(seed).sign(msg)
    except ImportError:
        return ed25519_sign(seed, msg)      # بدون نیاز به نصب کتابخونه (کندتر، ولی برای چند درخواست کافیه)


def _b64u_decode(sv):
    import base64
    return base64.urlsafe_b64decode(sv + '=' * (-len(sv) % 4))


def nobitex_keys_configured():
    return bool(NOBITEX_API_KEY and NOBITEX_API_SECRET)


def nobitex_signed_request(method, path, params=None, json_body=None, timeout=10):
    """درخواست امضاشده به نوبیتکس. اول apiv2 بعد آدرس قدیمی؛ اگه امضا با padding قبول نشد بدون padding امتحان می‌شه."""
    import base64
    if not nobitex_keys_configured():
        raise RuntimeError('کلید API نوبیتکس تنظیم نشده')
    seed = _b64u_decode(NOBITEX_API_SECRET)[:32]
    raw = json.dumps(json_body, separators=(',', ':')) if json_body is not None else ''
    last_err = None
    for base_url in NOBITEX_API_BASES:
        for with_pad in (True, False):
            prep = requests.Request(method, base_url + path, params=params, data=(raw or None),
                                    headers=({'Content-Type': 'application/json'} if raw else {})).prepare()
            ts = str(int(time.time()))
            sig = base64.urlsafe_b64encode(_ed_sign(seed, (ts + method + prep.path_url + raw).encode('utf-8'))).decode()
            if not with_pad:
                sig = sig.rstrip('=')
            prep.headers.update({'Nobitex-Key': NOBITEX_API_KEY, 'Nobitex-Signature': sig, 'Nobitex-Timestamp': ts})
            try:
                env = SESSION.merge_environment_settings(prep.url, {}, None, None, None)
                r = SESSION.send(prep, timeout=timeout, **env)
            except requests.exceptions.RequestException as ce:
                last_err = ce
                print(f'⚠️ اتصال به {base_url} ممکن نشد:', ce)
                break                      # آدرس بعدی
            if r.status_code in (401, 403) and with_pad:
                continue                   # یه‌بار هم بدون padding
            return r
    raise last_err or RuntimeError('اتصال به نوبیتکس ممکن نشد')


def _parse_ts(v):
    if v is None or v == '':
        return None
    if isinstance(v, (int, float)):
        return float(v) / 1000.0 if v > 1e12 else float(v)
    t = str(v).strip().replace('Z', '+00:00')
    t = re.sub(r'(\.\d+)', lambda m: ('.' + m.group(1)[1:].ljust(6, '0')[:6]), t, count=1)
    try:
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def _normalize_deposit(d):
    tr = d.get('transaction') if isinstance(d.get('transaction'), dict) else {}
    wl = d.get('wallet') if isinstance(d.get('wallet'), dict) else {}

    def pick(*keys):
        for k in keys:
            for src in (d, tr):
                if src.get(k) not in (None, ''):
                    return src.get(k)
        return None
    try:
        amount = float(str(pick('amount', 'value')).replace(',', ''))
    except Exception:
        return None
    cur = pick('currency', 'coin') or wl.get('currency')
    conf = pick('confirmed', 'is_confirmed')
    if conf is None:
        st = str(pick('status') or '').lower()
        conf = (st in ('confirmed', 'done', 'success', 'completed', 'ok')) if st else True
    return {
        'tx': str(pick('txHash', 'tx_hash', 'txid', 'hash') or ''),
        'currency': str(cur or '').lower(),
        'amount': amount,
        'ts': _parse_ts(pick('created_at', 'createdAt', 'date', 'timestamp')),
        'confirmed': bool(conf),
        'raw_keys': sorted(list(d.keys())) + ['transaction.' + k for k in sorted(tr.keys())],
    }


_nb_cache = {'t': 0.0, 'v': None}
_nb_logged = {'done': False}


def nobitex_fetch_deposits(force=False):
    if not force and _nb_cache['v'] is not None and time.time() - _nb_cache['t'] < 20:
        return _nb_cache['v']
    r = nobitex_signed_request('GET', '/users/wallets/deposits/list')
    if r.status_code == 405:
        r = nobitex_signed_request('POST', '/users/wallets/deposits/list', json_body={})
    if r.status_code != 200:
        raise RuntimeError(f'HTTP {r.status_code}: {r.text[:200]}')
    data = r.json()
    if isinstance(data, dict) and data.get('status') not in (None, 'ok'):
        raise RuntimeError(f'نوبیتکس خطا داد: {str(data)[:200]}')
    items = None
    if isinstance(data, dict):
        for k in ('deposits', 'result', 'results', 'data', 'transactions'):
            if isinstance(data.get(k), list):
                items = data[k]
                break
        if items is None:
            lists = [v for v in data.values() if isinstance(v, list)]
            items = lists[0] if lists else []
    elif isinstance(data, list):
        items = data
    deps = [x for x in (_normalize_deposit(i) for i in (items or []) if isinstance(i, dict)) if x]
    if not _nb_logged['done'] and deps:
        _nb_logged['done'] = True
        print('[nobitex] فیلدهای یک واریز:', deps[0]['raw_keys'])
    _nb_cache['t'], _nb_cache['v'] = time.time(), deps
    return deps


def crypto_auto_confirm_enabled():
    return get_setting('crypto_auto_confirm', '0') == '1'


def crypto_match_tolerance():
    try:
        return min(max(float(str(get_setting('crypto_match_tolerance_percent', '1')).replace(',', '.')), 0.0), 50.0) / 100.0
    except Exception:
        return 0.01


@with_db_retry
def get_crypto_request_row(req_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT id, user_id, amount, status, created_at, coin_symbol, coin_qty, tx_hash, req_ts, matched_tx, crypto_price '
              'FROM topup_requests WHERE id=?', (req_id,))
    row = c.fetchone()
    conn.close()
    return row


@with_db_retry
def list_pending_crypto_requests(hours=12):
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id FROM topup_requests WHERE status='pending' AND method='crypto' AND coin_symbol IS NOT NULL "
              "AND created_at >= ? ORDER BY id", (cutoff,))
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows


@with_db_retry
def is_deposit_used(tx):
    if not tx:
        return False
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT 1 FROM crypto_deposits_used WHERE tx=?', (tx,))
    row = c.fetchone()
    conn.close()
    return bool(row)


@with_db_retry
def mark_deposit_used(tx, req_id):
    if not tx:
        return
    conn = get_conn()
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO crypto_deposits_used (tx, req_id, created_at) VALUES (?, ?, ?)',
              (tx, req_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()


@with_db_retry
def set_request_matched_tx(req_id, tx):
    conn = get_conn()
    c = conn.cursor()
    c.execute('UPDATE topup_requests SET matched_tx=? WHERE id=?', (tx, req_id))
    conn.commit()
    conn.close()


@with_db_retry
def get_latest_pending_crypto_request(user_id):
    """آخرین درخواست شارژ رمزارزیِ در انتظارِ این کاربر (یا None)."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id FROM topup_requests WHERE user_id=? AND status='pending' AND method='crypto' "
              "AND coin_symbol IS NOT NULL ORDER BY id DESC LIMIT 1", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


@with_db_retry
def set_request_tx_hash(req_id, tx_hash):
    conn = get_conn()
    c = conn.cursor()
    c.execute('UPDATE topup_requests SET tx_hash=? WHERE id=?', (tx_hash, req_id))
    conn.commit()
    conn.close()


def attach_hash_to_pending_request(chat_id, req_id, tx_hash):
    """هش رو به درخواست معلق وصل می‌کنه، به ادمین خبر می‌ده و فوراً با نوبیتکس تطبیق می‌ده
    (اگه هنوز نخوره، watcher هم تا ۴۸ ساعت دوباره چک می‌کنه)."""
    prev = get_crypto_request_row(req_id)
    same = bool(prev and (prev[7] or '').strip() == tx_hash.strip())
    set_request_tx_hash(req_id, tx_hash)
    send_message(chat_id, u(chat_id, 'topup_hash_received'))
    if not same:
        send_message(ADMIN_ID, u('fa', 'admin_hash_sent', user_id=str(chat_id), req_id=str(req_id),
                                 tx_hash=_html.escape(tx_hash)))
    _crypto_notified.difference_update({k for k in _crypto_notified if k[0] == req_id})   # نتیجه‌ی جدید دوباره به ادمین برسه
    check_crypto_for_user_async(chat_id, req_id, 'hash')


def crypto_shortfall_toman():
    """حداکثر کسریِ مجاز (تومان) نسبت به مقدار مورد انتظار؛ از پنل با کلید crypto_max_shortfall_toman (پیش‌فرض ۶۰۰۰)."""
    try:
        return max(0.0, float(str(get_setting('crypto_max_shortfall_toman', '6000')).replace(',', '')))
    except Exception:
        return 6000.0


def crypto_amount_ok(amount, expected, price):
    """مقدار واریزی بیشتر یا مساوی مقدار مورد انتظار باشه، یا حداکثر چند هزار تومان (بر اساس قیمت لحظه‌ی درخواست) کمتر."""
    if amount >= expected - 1e-9:
        return True
    try:
        price = float(price)
    except Exception:
        return False
    if price <= 0:
        return False
    return (expected - amount) * price <= crypto_shortfall_toman()


@with_db_retry
def count_competing_crypto_requests(req_id, user_id, symbol, qty, tol, hours=48):
    """تعداد درخواست‌های معلقِ «کاربران دیگه» با همون کوین و مقدار تقریباً برابر.
    اگه باشه، تطبیق بدون هش خودکار تأیید نمی‌شه (معلوم نیست واریز مال کدوم کاربره؛ هش یا ادمین تصمیم می‌گیره)."""
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT coin_qty FROM topup_requests WHERE status='pending' AND method='crypto' AND coin_symbol=? "
              "AND id<>? AND user_id<>? AND created_at>=?", (symbol, req_id, user_id, cutoff))
    rows = c.fetchall()
    conn.close()
    n = 0
    for (q,) in rows:
        try:
            if abs(float(q) - qty) <= max(qty * tol * 2, 1e-9):
                n += 1
        except Exception:
            pass
    return n


def evaluate_crypto_request(req_id):
    """نتیجه‌ی تطبیق یه درخواست رمزارزی با واریزهای نوبیتکس: دیکشنری {state, deposit, note}.
    state: matched | mismatch | hash_mismatch | ambiguous | unconfirmed | not_found | error"""
    row = get_crypto_request_row(req_id)
    if not row or not row[5] or not row[6]:
        return {'state': 'error', 'note': u('fa', 'admin_ce_note_no_coin')}
    symbol, expected = str(row[5]).lower(), float(row[6])
    user_hash = (row[7] or '').strip().lower()
    req_ts = row[8]
    if not req_ts:
        try:
            req_ts = datetime.fromisoformat(row[4]).timestamp()
        except Exception:
            req_ts = time.time() - 6 * 3600
    price = row[10] if len(row) > 10 else None
    tol = crypto_match_tolerance()
    try:
        deps = nobitex_fetch_deposits()
    except Exception as e:
        return {'state': 'error', 'note': str(e)[:200]}

    unused = [d for d in deps if not is_deposit_used(d['tx'])]
    # تطبیق با هش: فقط خودِ هش مهمه (طول حداقل ۱۶ تا هش‌های کوتاه اتفاقی نخورن)
    hash_hits = [d for d in unused if user_hash and len(d['tx']) >= 16 and d['tx'].lower() in user_hash]
    if hash_hits:
        d = hash_hits[0]
        # هش خوردن به‌تنهایی کافی نیست (هش هر تراکنش روی بلاک‌چین عمومیه): کوین و مقدار هم باید بخونه
        fresh = d['ts'] is None or d['ts'] >= req_ts - 600     # واریز باید بعد از درخواست باشه، نه یه واریز قدیمی
        if d['currency'] == symbol and fresh and crypto_amount_ok(d['amount'], expected, price):
            if d['confirmed']:
                return {'state': 'hash_ok', 'deposit': d, 'expected': expected}
            return {'state': 'unconfirmed', 'deposit': d, 'expected': expected, 'by_hash': True}
        return {'state': 'mismatch', 'deposit': d, 'expected': expected, 'by_hash': True}
    pool = [d for d in unused if d['currency'] == symbol]
    by_hash = []
    by_time = [d for d in pool if d['ts'] is not None and d['ts'] >= req_ts - 600]
    if user_hash and not by_hash:
        base = by_time
        hash_note = True
    else:
        base = by_hash or by_time
        hash_note = False
    if not base:
        return {'state': 'hash_mismatch' if hash_note else 'not_found',
                'note': u('fa', 'admin_ce_note_hash_no_match') if hash_note else ''}
    if hash_note:
        # هش داده شده ولی با هیچ واریزی نخورده: هیچ‌وقت خودکار تأیید نمی‌شه (ممکنه واریز یه نفر دیگه باشه)؛
        # فقط نزدیک‌ترین واریز به ادمین نشون داده می‌شه. اگه واریز بعداً تو نوبیتکس بیاد، watcher با هش دوباره چک می‌کنه.
        best = min(base, key=lambda d: abs(d['amount'] - expected))
        return {'state': 'hash_mismatch', 'deposit': best, 'expected': expected,
                'note': u('fa', 'admin_ce_note_hash_nearest')}
    # مسیر بدون هش (درخواست‌های قدیمی): سقف بالا هم داره تا واریز بزرگ یه نفر دیگه اشتباهاً مچ نشه
    within = [d for d in base if crypto_amount_ok(d['amount'], expected, price)
              and d['amount'] <= expected * (1 + tol)]
    ok = [d for d in within if d['confirmed']]
    if len(ok) == 1:
        if count_competing_crypto_requests(req_id, row[1], symbol, expected, tol) > 0:
            return {'state': 'ambiguous', 'deposit': ok[0], 'expected': expected,
                    'note': u('fa', 'admin_ce_note_competing')}
        return {'state': 'matched', 'deposit': ok[0], 'expected': expected}
    if len(ok) > 1:
        return {'state': 'ambiguous', 'deposit': ok[0], 'expected': expected, 'note': u('fa', 'admin_ce_note_multi', n=len(ok))}
    if within:
        return {'state': 'unconfirmed', 'deposit': within[0], 'expected': expected}
    best = min(base, key=lambda d: abs(d['amount'] - expected))
    return {'state': 'mismatch', 'deposit': best, 'expected': expected}


def format_crypto_eval(req_id, res, coin_label=''):
    st = res.get('state')
    dep, exp = res.get('deposit'), res.get('expected')
    head = u('fa', 'admin_ce_head', req_id=str(req_id)) + '\n'
    note = _html.escape(str(res.get('note', '')))
    if st == 'error':
        return head + u('fa', 'admin_ce_error', note=note)
    if st == 'not_found':
        return head + u('fa', 'admin_ce_not_found')
    if st == 'hash_mismatch' and not dep:
        return head + u('fa', 'admin_ce_hash_mismatch_nodep', note=note)
    diff = ''
    if dep and exp:
        diff = ' ' + u('fa', 'admin_ce_diff', pct=f'{(dep["amount"] - exp) / exp * 100:+.2f}')
        if st == 'hash_ok':
            diff += ' ' + u('fa', 'admin_ce_coin_suffix', coin=_html.escape(str(dep.get('currency', '')).upper()))
    state_keys = {
        'hash_ok': 'admin_ce_hash_ok', 'matched': 'admin_ce_matched', 'mismatch': 'admin_ce_mismatch',
        'hash_mismatch': 'admin_ce_hash_mismatch', 'ambiguous': 'admin_ce_ambiguous',
        'unconfirmed': 'admin_ce_unconfirmed',
    }
    line = u('fa', state_keys[st], note=note) if st in state_keys else ''
    msg = head + line + '\n'
    if dep:
        dep_coin = str(dep.get('currency') or '').upper() or coin_label
        msg += u('fa', 'admin_ce_amount_line', amount=fmt_coin_amount(dep['amount']), coin=_html.escape(dep_coin),
                 diff=diff, expected=fmt_coin_amount(exp)) + '\n'
        if dep.get('tx'):
            msg += u('fa', 'admin_ce_hash_line', tx=_html.escape(dep['tx'])) + '\n'
        if dep.get('ts'):
            msg += u('fa', 'admin_ce_time_line', time=fmt_iran_datetime(dep['ts']))
    return msg


_topup_approve_lock = threading.Lock()


def approve_topup_request(req_id, auto=False, reason='hash_ok'):
    """تأیید یه درخواست شارژ (دستی با دکمه‌ی ادمین یا خودکار). True اگه همین الان تأیید شد."""
    with _topup_approve_lock:
        req = get_topup_request(req_id)
        if not (req and req[3] == 'pending'):
            return False
        if auto:
            try:
                _r = get_crypto_request_row(req_id)
                if _r and _r[9] and is_deposit_used(_r[9]):
                    return False       # همین واریز همین الان برای درخواست دیگه‌ای استفاده شده
            except Exception as e:
                print('⚠️ چک واریز مصرف‌شده ناموفق بود:', e)
                return False
        # شارژ رمزارزی دقیقاً همون مبلغی‌ه که کاربر وارد کرده (ضریب واریزی فقط برای کارت‌به‌کارت)
        multiplier = 1.0 if get_topup_method(req_id) == 'crypto' else get_topup_multiplier()
        credited = int(round(req[2] * multiplier))
        update_topup_status(req_id, 'approved')
        update_wallet_db(req[1], credited)
        try:
            _st = user_steps.get(str(req[1])) or {}
            if _st.get('step') == 'crypto_send_hash' and _st.get('req_id') == req_id:
                user_steps[str(req[1])] = {}
        except Exception:
            pass
        try:
            row = get_crypto_request_row(req_id)
            if row and row[9]:
                mark_deposit_used(row[9], req_id)     # این واریز دیگه به درخواست دیگه‌ای نخوره
        except Exception as e:
            print('⚠️ ثبت واریز استفاده‌شده ناموفق بود:', e)
    if multiplier != 1:
        send_message(req[1], u(req[1], 'topup_approved_mult', credited=f'{credited:,}', amount=f'{req[2]:,}',
                               multiplier=('%g' % multiplier)))
    else:
        send_message(req[1], u(req[1], 'topup_approved', credited=f'{credited:,}'))
    note = u('fa', 'admin_topup_approved', req_id=str(req_id), credited=f'{credited:,}')
    auto_note = '\n' + u('fa', 'admin_auto_approved_hash' if reason == 'hash_ok' else 'admin_auto_approved_amount')
    send_message(ADMIN_ID, note + (auto_note if auto else ''))
    return True


_crypto_notified = set()


def handle_crypto_eval(req_id, res, force_notify=False):
    """نتیجه‌ی تطبیق رو اعمال می‌کنه: تأیید خودکار (اگه روشن باشه) یا پیام اطلاعاتی به ادمین (هر حالت فقط یک‌بار)."""
    st = res.get('state')
    row = get_crypto_request_row(req_id)
    if not row or row[3] != 'pending':
        return          # قبلاً با یکی از راه‌ها (خودکار / هش کاربر / تأیید دستی ادمین) بسته شده؛ دوباره شارژ نمی‌شه
    label = str(row[5]).upper() if row and row[5] else ''
    if res.get('by_hash') and res.get('deposit'):
        try:
            set_request_matched_tx(req_id, res['deposit'].get('tx') or None)   # اگه ادمین دستی تأیید کنه، همین واریز دیگه مصرف‌شده حساب می‌شه
        except Exception as e:
            print('⚠️ ثبت matched_tx ناموفق:', e)
    if st in ('hash_ok', 'matched'):
        try:
            set_request_matched_tx(req_id, res['deposit'].get('tx') or None)
        except Exception as e:
            print('⚠️ ثبت matched_tx ناموفق:', e)
        if crypto_auto_confirm_enabled():
            # هش‌خورده (hash_ok) یا مقدار+کوین+زمان خورده بدون هش (matched): هر دو خودکار تأیید می‌شن
            # قبل از تأیید، گزارش واریز (مقدار واقعی) برای ادمین می‌ره تا همیشه ببینی چی تأیید شده
            send_message(ADMIN_ID, format_crypto_eval(req_id, res, label))
            if approve_topup_request(req_id, auto=True, reason=st):
                return
    key = (req_id, st)
    if key in _crypto_notified or (st == 'not_found' and not force_notify):
        return
    _crypto_notified.add(key)
    kb = {'inline_keyboard': [[      # ادمین همیشه می‌تونه دستی تأیید/رد کنه (حتی وقتی واریز پیدا نشده)
        {'text': u('fa', 'admin_btn_accept'), 'callback_data': 'topup_acc_' + str(req_id)},
        {'text': u('fa', 'admin_btn_reject'), 'callback_data': 'topup_rej_' + str(req_id)}]]}
    send_message(ADMIN_ID, format_crypto_eval(req_id, res, label), reply_markup=kb)


def check_crypto_request_async(req_id):
    def _run():
        try:
            if nobitex_keys_configured():
                handle_crypto_eval(req_id, evaluate_crypto_request(req_id), force_notify=True)
        except Exception as e:
            print('⚠️ بررسی نوبیتکس ناموفق بود:', e)
    threading.Thread(target=_run, daemon=True).start()


def crypto_deposit_watcher():
    """هر ~۴۵ ثانیه درخواست‌های رمزارزیِ معلق رو با واریزهای نوبیتکس تطبیق می‌ده (فقط اگه درخواست معلقی باشه)."""
    time.sleep(25)
    while True:
        try:
            if nobitex_keys_configured():
                for rid in list_pending_crypto_requests(hours=48):
                    handle_crypto_eval(rid, evaluate_crypto_request(rid))
        except Exception as e:
            print('⚠️ crypto_deposit_watcher:', e)
        time.sleep(45)


def nobitex_check_report():
    """گزارش تست اتصال برای دستور ادمین /nobitexcheck."""
    if not nobitex_keys_configured():
        return '⚠️ کلید API نوبیتکس تنظیم نشده.'
    try:
        deps = nobitex_fetch_deposits(force=True)
    except Exception as e:
        return '❌ اتصال/دسترسی به نوبیتکس ناموفق بود:\n' + _html.escape(str(e)[:300])
    lines = [f'✅ اتصال به نوبیتکس برقراره. {len(deps)} واریز خونده شد.']
    for d in deps[:3]:
        lines.append(f'• {d["currency"].upper()} {fmt_coin_amount(d["amount"])} — '
                     + (fmt_iran_datetime(d['ts']) if d['ts'] else 'زمان نامشخص')
                     + ('' if d['confirmed'] else ' (تأیید نشده)'))
    lines.append(f'تأیید خودکار: {"روشن" if crypto_auto_confirm_enabled() else "خاموش"}')
    return '\n'.join(lines)


@with_db_retry
def get_latest_config_row(user_id):
    """آخرین کانفیگ ساخته‌شده‌ی یه کاربر (برای اضافه‌کردن حجم جایزه‌ی رفرال بهش)."""
    conn = get_conn()
    c = conn.cursor()
    c.execute('''SELECT id, sub_url, config_id, gb, label, days, price, created_at, expires_at, type, status
        FROM user_configs WHERE user_id=? ORDER BY created_at DESC LIMIT 1''', (user_id,))
    res = c.fetchone()
    conn.close()
    return res


_user_info_cache = {}


def upsert_user_info(user_id, username, first_name):
    """قبلاً روی هر پیام یه نوشتن تو دیتابیس (رفت‌وبرگشت شبکه به Turso) انجام
    می‌شد. حالا فقط وقتی اجرا می‌شه که کاربر تازه باشه یا یوزرنیم/اسمش عوض شده."""
    key = (username, first_name)
    if _user_info_cache.get(user_id) == key:
        return
    _upsert_user_info_db(user_id, username, first_name)
    _user_info_cache[user_id] = key


@with_db_retry
def _upsert_user_info_db(user_id, username, first_name):
    conn = get_conn()
    c = conn.cursor()
    c.execute('''INSERT INTO users (user_id, wallet, joined_at, username, first_name)
        VALUES (?, 0, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name''',
        (user_id, datetime.now().isoformat(), username, first_name))
    conn.commit()
    conn.close()


_activity_cache = {}      # user_id -> (action, زمان آخرین نوشتن)
ACTIVITY_THROTTLE_SEC = 20


@with_db_retry
def _touch_user_db(user_id, action, ts):
    conn = get_conn()
    c = conn.cursor()
    c.execute('''INSERT INTO users (user_id, wallet, joined_at, last_active, last_action)
        VALUES (?, 0, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET last_active=excluded.last_active,
                                           last_action=excluded.last_action''',
        (user_id, datetime.now().isoformat(), ts, action))
    conn.commit()
    conn.close()


def _describe_update(update, step_name):
    """آپدیت رو به مقدار خامی تبدیل می‌کنه که پنل (action_label) می‌فهمه:
    cmd:/x ، btn:<key> ، cb:<data> ، photo ، step:<name> ، text"""
    if 'callback_query' in update:
        return 'cb:' + str((update['callback_query'].get('data') or ''))[:60]
    message = update.get('message') or {}
    text = message.get('text') or ''
    if text.startswith('/'):
        return 'cmd:' + text.split()[0][:40]
    if text:
        key = get_label_to_action_key().get(text)
        if key:
            return 'btn:' + key
    if message.get('photo'):
        return 'photo'
    if step_name:
        return 'step:' + str(step_name)
    return 'text'


def _record_activity(user_id, update, step_name):
    try:
        action = _describe_update(update, step_name)
        now = time.time()
        prev = _activity_cache.get(user_id)
        if prev and prev[0] == action and now - prev[1] < ACTIVITY_THROTTLE_SEC:
            return
        _activity_cache[user_id] = (action, now)
        ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
        _touch_user_db(user_id, action, ts)
    except Exception as e:
        print('⚠️ ثبت آخرین فعالیت ناموفق بود:', e)


def track_activity(update):
    """آخرین فعالیت کاربر رو تو پس‌زمینه ثبت می‌کنه (جواب کاربر معطل نمی‌شه)."""
    if 'callback_query' in update:
        chat_id = (update['callback_query'].get('message') or {}).get('chat', {}).get('id')
    elif 'message' in update:
        chat_id = (update['message'].get('chat') or {}).get('id')
    else:
        return
    if chat_id is None:
        return
    step_name = (user_steps.get(str(chat_id)) or {}).get('step')   # قبل از اینکه هندلر step رو عوض کنه
    BG_EXECUTOR.submit(_record_activity, chat_id, update, step_name)


@with_db_retry
def get_username_db(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT username FROM users WHERE user_id=?', (user_id,))
    res = c.fetchone()
    conn.close()
    return res[0] if res else None


@with_db_retry
def update_wallet_db(user_id, amount):
    conn = get_conn()
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO users (user_id, wallet) VALUES (?, ?)', (user_id, 0))
    c.execute('UPDATE users SET wallet = wallet + ? WHERE user_id=?', (amount, user_id))
    conn.commit()
    conn.close()


@with_db_retry
def save_user_config(user_id, sub_url, config_id, gb, label, days, price, ctype='both'):
    conn = get_conn()
    c = conn.cursor()
    expires_at = (datetime.now() + timedelta(days=days)).isoformat()
    c.execute('''INSERT INTO user_configs
        (user_id, sub_url, config_id, gb, label, days, price, type, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (user_id, sub_url, config_id, gb, label, days, price, ctype, datetime.now().isoformat(), expires_at))
    conn.commit()
    conn.close()


@with_db_retry
def get_user_configs(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('''SELECT id, sub_url, config_id, gb, label, days, price, created_at, expires_at, type, status
        FROM user_configs WHERE user_id=? ORDER BY created_at DESC''', (user_id,))
    res = c.fetchall()
    conn.close()
    return res


@with_db_retry
def save_order(user_id, label, gb, days, price, ctype, config_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('''INSERT INTO orders (user_id, label, gb, days, price, type, config_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (user_id, label, gb, days, price, ctype, config_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()


@with_db_retry
def get_recent_orders(user_id, limit=3):
    """(id, label, gb, days, price, type, created_at) — جدیدترین اول."""
    conn = get_conn()
    c = conn.cursor()
    c.execute('''SELECT id, label, gb, days, price, type, created_at
        FROM orders WHERE user_id=? ORDER BY id DESC LIMIT ?''', (user_id, limit))
    res = c.fetchall()
    conn.close()
    return res


@with_db_retry
def get_reseller(user_id):
    """(user_id, api_key, secret_hash, gb_balance, price_per_gb, status, created_at) یا None."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, api_key, secret_hash, gb_balance, price_per_gb, status, created_at "
              "FROM resellers WHERE user_id=?", (user_id,))
    res = c.fetchone()
    conn.close()
    return res


@with_db_retry
def create_reseller(user_id, api_key, secret_hash, gb):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""INSERT INTO resellers (user_id, api_key, secret_hash, gb_balance, price_per_gb, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'active', ?)
        ON CONFLICT(user_id) DO UPDATE SET
            gb_balance=resellers.gb_balance + excluded.gb_balance""",
        (user_id, api_key, secret_hash, gb, get_reseller_price_per_gb(), datetime.now().isoformat()))
    conn.commit()
    conn.close()


RESELLER_USERNAME_RE = re.compile(r'^[A-Za-z0-9_.]{3,20}$')
RESELLER_PASSWORD_MIN = 6
RESELLER_PASSWORD_MAX = 64
_PBKDF2_ITERS = 200_000


def hash_reseller_password(password):
    """pbkdf2_sha256$تکرار$salt$hash — پنل با همین فرمت چک می‌کنه (رمز خام هیچ‌جا ذخیره نمی‌شه)."""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), _PBKDF2_ITERS)
    return f'pbkdf2_sha256${_PBKDF2_ITERS}${salt}${dk.hex()}'


@with_db_retry
def get_reseller_username(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT username FROM resellers WHERE user_id=?", (user_id,))
    r = c.fetchone()
    conn.close()
    return (r[0] if r and r[0] else None)


@with_db_retry
def reseller_username_taken(username, except_user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT 1 FROM resellers WHERE username=? AND user_id<>?", (username, except_user_id))
    r = c.fetchone()
    conn.close()
    return bool(r)


@with_db_retry
def set_reseller_username_db(user_id, username):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE resellers SET username=? WHERE user_id=?", (username, user_id))
    conn.commit()
    conn.close()


@with_db_retry
def set_reseller_password_db(user_id, password_hash, password_plain=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE resellers SET password_hash=?, password_plain=? WHERE user_id=?", (password_hash, password_plain, user_id))
    conn.commit()
    conn.close()


@with_db_retry
def set_reseller_credentials_db(user_id, username, password_hash, password_plain=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE resellers SET username=?, password_hash=?, password_plain=? WHERE user_id=?",
              (username, password_hash, password_plain, user_id))
    conn.commit()
    conn.close()


@with_db_retry
def add_reseller_gb_db(user_id, gb, price):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE resellers SET gb_balance = gb_balance + ? WHERE user_id=?", (gb, user_id))
    c.execute("INSERT INTO reseller_pool_log (user_id, gb, price, created_at) VALUES (?, ?, ?, ?)",
               (user_id, gb, price, datetime.now().isoformat()))
    conn.commit()
    conn.close()


@with_db_retry
def deduct_reseller_gb_atomic(user_id, gb):
    """فقط اگه واقعاً استخر کافی باشه کم می‌کنه (شرط تو خودِ WHERE)، تا اگه
    فروشنده هم‌زمان هم تو بات و هم از طریق API بسازه، استخر منفی نشه."""
    conn = get_conn()
    c = conn.cursor()
    c.execute('UPDATE resellers SET gb_balance = gb_balance - ? WHERE user_id=? AND gb_balance >= ?',
              (gb, user_id, gb))
    conn.commit()
    ok = c.rowcount > 0
    conn.close()
    return ok


@with_db_retry
def refund_reseller_gb_db(user_id, gb):
    conn = get_conn()
    c = conn.cursor()
    c.execute('UPDATE resellers SET gb_balance = gb_balance + ? WHERE user_id=?', (gb, user_id))
    conn.commit()
    conn.close()


@with_db_retry
def save_reseller_config_db(reseller_id, config_id, sub_url, gb, days, label, ctype, source='bot'):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        'INSERT INTO reseller_api_configs '
        '(reseller_id, config_id, sub_url, gb, days, label, type, active, created_at, source) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)',
        (reseller_id, config_id, sub_url, gb, days, label, ctype, datetime.now().isoformat(), source)
    )
    conn.commit()
    conn.close()


@with_db_retry
def get_order_row(user_id, order_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('''SELECT id, label, gb, days, price, type, created_at
        FROM orders WHERE user_id=? AND id=?''', (user_id, order_id))
    res = c.fetchone()
    conn.close()
    return res


@with_db_retry
def get_config_row(user_id, row_id):
    """یک کانفیگ مشخص از یک کاربر مشخص رو برمی‌گردونه (برای دکمه‌های مدیریت)."""
    conn = get_conn()
    c = conn.cursor()
    c.execute('''SELECT id, sub_url, config_id, gb, label, days, price, created_at, expires_at, type, status
        FROM user_configs WHERE user_id=? AND id=?''', (user_id, row_id))
    res = c.fetchone()
    conn.close()
    return res


@with_db_retry
def update_config_label_db(row_id, label):
    conn = get_conn()
    c = conn.cursor()
    c.execute('UPDATE user_configs SET label=? WHERE id=?', (label, row_id))
    conn.commit()
    conn.close()


@with_db_retry
def update_config_status_db(row_id, status):
    conn = get_conn()
    c = conn.cursor()
    c.execute('UPDATE user_configs SET status=? WHERE id=?', (status, row_id))
    conn.commit()
    conn.close()


@with_db_retry
def update_config_suburl_db(row_id, sub_url):
    conn = get_conn()
    c = conn.cursor()
    c.execute('UPDATE user_configs SET sub_url=? WHERE id=?', (sub_url, row_id))
    conn.commit()
    conn.close()


@with_db_retry
def extend_config_db(row_id, extra_gb, extra_days):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT gb, days, expires_at FROM user_configs WHERE id=?', (row_id,))
    row = c.fetchone()
    if row:
        gb, days, expires_at = row
        new_gb = (gb or 0) + extra_gb
        new_days = (days or 0) + extra_days
        try:
            base = datetime.fromisoformat(expires_at) if expires_at else datetime.now()
        except Exception:
            base = datetime.now()
        new_expires = (base + timedelta(days=extra_days)).isoformat()
        c.execute('UPDATE user_configs SET gb=?, days=?, expires_at=? WHERE id=?',
                   (new_gb, new_days, new_expires, row_id))
        conn.commit()
    conn.close()


def clean_label(text):
    """اسم کانفیگ تایپ‌شده توسط کاربر: کاراکترهای < > & حذف می‌شن تا تو پیام‌های HTML
    (فاکتور، تایید خرید، تغییر نام) مشکل پارس ایجاد نکنن. بقیه‌ی متن دست‌نخورده می‌مونه."""
    return re.sub(r'[<>&]', '', (text or '')).strip()


def delete_config_from_panel(config_id):
    if not config_id:
        return True
    try:
        res = SESSION.delete(
            CONFIG_API + '/' + str(config_id),
            headers={'Authorization': 'Bearer ' + CONFIG_KEY},
            timeout=15
        )
        return res.status_code in (200, 201, 204)
    except Exception:
        return False


def _panel_action(method, path_suffix, config_id, json_body=None):
    """کمکی مشترک برای عملیات مدیریتی پنل (تمدید/تغییر نام/توقف/ازسرگیری/تغییر لینک)."""
    try:
        res = SESSION.request(
            method,
            CONFIG_API + '/' + str(config_id) + path_suffix,
            headers={'Authorization': 'Bearer ' + CONFIG_KEY},
            json=json_body,
            timeout=20
        )
        if res.status_code in (200, 201):
            try:
                return {'success': True, 'data': res.json()}
            except Exception:
                return {'success': True, 'data': {}}
        return {'success': False, 'error': res.text[:300]}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def extend_config_on_panel(config_id, gb, days):
    return _panel_action('POST', '/extend', config_id, {'gb': gb, 'days': days})


def rename_config_on_panel(config_id, label):
    return _panel_action('PUT', '/label', config_id, {'label': label})


def pause_config_on_panel(config_id):
    return _panel_action('POST', '/pause', config_id)


def resume_config_on_panel(config_id):
    return _panel_action('POST', '/resume', config_id)


def rotate_link_config_on_panel(config_id):
    return _panel_action('POST', '/rotate-link', config_id)


def get_config_usage_gb(config_id):
    """
    مقدار مصرف (گیگابایت) یک کانفیگ رو از پنل می‌گیره.
    طبق مستندات پنل (GET /configs/:id)، پاسخ مستقیماً شامل فیلد usedGb
    (بر حسب گیگابایت، نه بایت) هست. برای اطمینان، هم حالت پاسخ مستقیم
    (آبجکت تکی) و هم حالت لیست‌شده (داخل configs[0]) رو پشتیبانی می‌کنه.
    در صورت هر نوع خطا یا نامشخص بودن فیلد، None برمی‌گردونه.
    """
    if not config_id:
        return None
    try:
        res = SESSION.get(
            CONFIG_API + '/' + str(config_id),
            headers={'Authorization': 'Bearer ' + CONFIG_KEY},
            timeout=15
        )
        if res.status_code not in (200, 201):
            print('⚠️ خطای دریافت اطلاعات کانفیگ (وضعیت ' + str(res.status_code) + '):', res.text[:500])
            return None

        data = res.json()

        # اگه پاسخ به شکل {"configs": [ {...} ]} بود، آیتم اول رو بردار
        if isinstance(data, dict) and isinstance(data.get('configs'), list) and data['configs']:
            data = data['configs'][0]

        used_gb = data.get('usedGb')
        if used_gb is not None:
            return float(used_gb)

        # فالبک برای احتمال نام‌گذاری‌های دیگه یا واحد بایت
        used_bytes = (
            data.get('usedTraffic')
            or data.get('used_traffic')
            or data.get('trafficUsed')
            or data.get('usage')
            or data.get('dataUsage')
        )
        if used_bytes is None:
            up = data.get('uploadBytes') or data.get('upload') or 0
            down = data.get('downloadBytes') or data.get('download') or 0
            if up or down:
                used_bytes = up + down

        if used_bytes is None:
            print('⚠️ فیلد مصرف در پاسخ پنل پیدا نشد. پاسخ خام:', json.dumps(data, ensure_ascii=False)[:800])
            return None

        return used_bytes / (1024 ** 3)

    except Exception as e:
        print('⚠️ استثنا در دریافت مصرف کانفیگ:', e)
        return None


@with_db_retry
def delete_config_from_db_by_index(user_id, index):
    configs = get_user_configs(user_id)
    if 0 <= index < len(configs):
        cfg = configs[index]
        delete_config_from_panel(cfg[2])
        conn = get_conn()
        c = conn.cursor()
        c.execute('DELETE FROM user_configs WHERE id=?', (cfg[0],))
        conn.commit()
        conn.close()
        return True
    return False


@with_db_retry
def get_total_purchases(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT SUM(gb), SUM(price) FROM user_configs WHERE user_id=?', (user_id,))
    res = c.fetchone()
    conn.close()
    return (res[0] if res and res[0] else 0, res[1] if res and res[1] else 0)


@with_db_retry
def check_free_trial(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM free_trials WHERE user_id=?', (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count


@with_db_retry
def set_free_trial(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO free_trials (user_id) VALUES (?)', (user_id,))
    conn.commit()
    conn.close()


@with_db_retry
def create_topup_request(user_id, amount, method='card', crypto_amount=None, crypto_price=None,
                         coin_symbol=None, coin_qty=None, tx_hash=None, req_ts=None):
    conn = get_conn()
    c = conn.cursor()
    if method == 'card':
        c.execute('INSERT INTO topup_requests (user_id, amount, created_at) VALUES (?, ?, ?)',
                   (user_id, amount, datetime.now().isoformat()))
    else:
        c.execute('INSERT INTO topup_requests (user_id, amount, created_at, method, crypto_amount, crypto_price, '
                  'coin_symbol, coin_qty, tx_hash, req_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                  (user_id, amount, datetime.now().isoformat(), method, str(crypto_amount), str(crypto_price),
                   coin_symbol, None if coin_qty is None else repr(float(coin_qty)), tx_hash, req_ts))
    conn.commit()
    req_id = c.lastrowid
    conn.close()
    return req_id


@with_db_retry
def get_topup_request(req_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT id, user_id, amount, status FROM topup_requests WHERE id=?', (req_id,))
    res = c.fetchone()
    conn.close()
    return res


def get_topup_method(req_id):
    """'card' یا 'crypto' (اگه ستون نبود/خطا شد، card)."""
    try:
        conn = get_conn()
        c = conn.cursor()
        c.execute('SELECT method FROM topup_requests WHERE id=?', (req_id,))
        row = c.fetchone()
        conn.close()
        return (row[0] if row and row[0] else 'card')
    except Exception:
        return 'card'


@with_db_retry
def update_topup_status(req_id, status):
    conn = get_conn()
    c = conn.cursor()
    c.execute('UPDATE topup_requests SET status=? WHERE id=?', (status, req_id))
    conn.commit()
    conn.close()


@with_db_retry
def create_ticket(user_id, message):
    conn = get_conn()
    c = conn.cursor()
    c.execute('INSERT INTO tickets (user_id, message, created_at) VALUES (?, ?, ?)',
               (user_id, message, datetime.now().isoformat()))
    conn.commit()
    tid = c.lastrowid
    conn.close()
    return tid


@with_db_retry
def get_ticket(ticket_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT id, user_id, message, status, admin_reply, created_at FROM tickets WHERE id=?', (ticket_id,))
    res = c.fetchone()
    conn.close()
    return res


@with_db_retry
def update_ticket_status(ticket_id, status, admin_reply=None):
    conn = get_conn()
    c = conn.cursor()
    if admin_reply:
        c.execute('UPDATE tickets SET status=?, admin_reply=? WHERE id=?', (status, admin_reply, ticket_id))
    else:
        c.execute('UPDATE tickets SET status=? WHERE id=?', (status, ticket_id))
    conn.commit()
    conn.close()


@with_db_retry
def get_discount_code(code):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT code, percent, max_uses, used_count, active FROM discount_codes WHERE code=?',
              (code.strip().upper(),))
    res = c.fetchone()
    conn.close()
    return res


@with_db_retry
def increment_discount_usage(code):
    conn = get_conn()
    c = conn.cursor()
    c.execute('UPDATE discount_codes SET used_count = used_count + 1 WHERE code=?', (code.strip().upper(),))
    conn.commit()
    conn.close()


def validate_discount_code(code):
    """برمی‌گرداند: (ok: bool, percent یا کلید ترجمه‌ی پیام خطا). کلید خطا با
    u(chat_id, key) به متن فارسی/انگلیسی مناسب تبدیل می‌شه."""
    row = get_discount_code(code)
    if not row:
        return False, 'discount_invalid'
    _, percent, max_uses, used_count, active = row
    if active != 1:
        return False, 'discount_inactive'
    if used_count >= max_uses:
        return False, 'discount_capacity'
    return True, percent


_settings_cache = {}
_settings_cache_ts = 0.0
_SETTINGS_CACHE_TTL = 20  # ثانیه


@with_db_retry
def _fetch_all_settings():
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT key, value FROM settings')
    rows = c.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}


def get_setting(key, default='1'):
    """قبلاً هر get_setting یه رفت‌وبرگشت شبکه‌ی جدا به دیتابیس (Turso) می‌زد.
    چون فقط ساخت منوی اصلی (یه /start ساده) ده‌ها تا get_setting صدا می‌زنه
    (قیمت هر ۴ نوع سرویس، متن‌ها، لیبل دکمه‌ها، وضعیت روشن/خاموش قابلیت‌ها)،
    همین تنها باعث چند ثانیه تاخیر تو جواب ربات می‌شد — مخصوصاً روی شبکه‌ای
    که به دیتابیس فاصله/لتنسی داره. حالا کل جدول settings یک‌جا خونده و حداکثر
    هر _SETTINGS_CACHE_TTL ثانیه یک‌بار تازه‌سازی می‌شه؛ در نتیجه یه پیام معمولی
    به‌جای ۱۰-۱۵ کوئری، معمولاً صفر یا یک کوئری به دیتابیس تنظیمات می‌زنه.
    یعنی تغییرات پنل هم حداکثر با همون چند ثانیه تاخیر (نه بلافاصله) روی ربات
    اعمال می‌شه؛ اگه لازمه فوری باشه، TTL رو کمتر کنید."""
    now = time.time()
    if now - _settings_cache_ts > _SETTINGS_CACHE_TTL:
        if _settings_cache_ts == 0.0:
            # اولین بار (کش خالیه): باید همون لحظه خونده بشه
            _refresh_settings_cache()
        else:
            # کش کهنه شده ولی مقدار قبلی هست: همون رو فوراً برگردون و رفرش رو
            # تو پس‌زمینه انجام بده تا کاربرِ بدشانس هر ۲۰ ثانیه معطل نشه
            _schedule_settings_refresh()
    return _settings_cache.get(key, default)


_settings_refresh_lock = threading.Lock()
_settings_refreshing = False


def _refresh_settings_cache():
    global _settings_cache, _settings_cache_ts
    try:
        _settings_cache = _fetch_all_settings()
        _settings_cache_ts = time.time()
    except Exception as e:
        print('⚠️ خطا در رفرش کش تنظیمات (با آخرین مقادیر کش‌شده ادامه داده می‌شه):', e)


def _schedule_settings_refresh():
    global _settings_refreshing
    with _settings_refresh_lock:
        if _settings_refreshing:
            return
        _settings_refreshing = True

    def _job():
        global _settings_refreshing
        try:
            _refresh_settings_cache()
        finally:
            _settings_refreshing = False

    try:
        BG_EXECUTOR.submit(_job)
    except Exception:
        _settings_refreshing = False


_label_counter_lock = threading.Lock()


@with_db_retry
def get_next_user_label():
    """هر بار که کاربر «رد شدن» از اسم کانفیگ رو می‌زنه، یه اسم پیش‌فرض یکتا و
    ترتیبی (USER-1، USER-2، ...) می‌سازه. قبلاً از خودِ chat_id به‌عنوان اسم
    پیش‌فرض استفاده می‌شد، که چون پنل هر اسم رو فقط یک‌بار قبول می‌کنه، خرید
    دومِ همون کاربر (با همون chat_id) با خطای «این اسم قبلاً استفاده شده» رد
    می‌شد. شمارنده مستقیم تو دیتابیس (نه از طریق کش get_setting) خونده و
    نوشته می‌شه، و با قفل هم محافظت می‌شه، تا حتی اگه دو نفر هم‌زمان بزنن
    «رد شدن»، هیچ‌وقت یه شماره‌ی تکراری بهشون داده نشه."""
    with _label_counter_lock:
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key='user_label_counter'")
        res = c.fetchone()
        current = int(res[0]) if res and res[0] else 0
        next_val = current + 1
        c.execute(
            "INSERT INTO settings (key, value) VALUES ('user_label_counter', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(next_val),)
        )
        conn.commit()
        conn.close()
        return 'USER-' + str(next_val)


def get_ordered_keys(setting_key, default_keys):
    """ترتیب فعلی یه گروه دکمه (که از پنل «متن‌ها و ظاهر ربات» قابل تغییره) رو
    برمی‌گردونه. هر کلید نامعتبر/تکراری حذف می‌شه و هر کلیدی که تو ترتیب
    ذخیره‌شده نیست (مثلاً بعداً به کد اضافه شده) ته لیست چسبونده می‌شه."""
    raw = get_setting(setting_key, ','.join(default_keys))
    order = [k.strip() for k in raw.split(',') if k.strip()]
    order = [k for k in order if k in default_keys]
    for k in default_keys:
        if k not in order:
            order.append(k)
    return order


def is_feature_enabled(key):
    return get_setting(key, '1') == '1'


DISABLED_TEXT = '⛔ این قابلیت در حال حاضر توسط مدیریت غیرفعال شده است.'


# ---------------------------------------------------------------------------
# Telegram / panel API helpers
# ---------------------------------------------------------------------------

def delete_webhook():
    try:
        res = SESSION.post(BASE_URL + '/deleteWebhook', json={'drop_pending_updates': False}, timeout=10)
        print('🧹 حذف Webhook قبلی:', res.json())
    except Exception as e:
        print('⚠️ خطا در حذف Webhook:', e)




# فهرست دستورهایی که با زدن دکمه «/» توی صفحه کیبورد کاربر نمایش داده می‌شه
BOT_COMMANDS = [
    {'command': 'start', 'description': '🏠 شروع و منوی اصلی'},
    {'command': 'buy', 'description': '🛍 خرید کانفیگ'},
    {'command': 'test', 'description': '🧪 تست رایگان'},
    {'command': 'wallet', 'description': '💠 شارژ کیف پول'},
    {'command': 'myconfigs', 'description': '🗂 کانفیگ‌های من'},
    {'command': 'delconfig', 'description': '🗑 حذف کانفیگ'},
    {'command': 'account', 'description': '👤 حساب من'},
    {'command': 'support', 'description': '🎧 پشتیبانی'},
    {'command': 'guide', 'description': '📲 اپ مخصوص کانفیگ‌ها'},
    {'command': 'invite', 'description': '🎁 دعوت دوستان'},
]

# دستورهای اسلش معادل دکمه‌های منو، به COMMAND_TO_ACTION_KEY (پایین‌تر، کنار
# main_menu) نگاشت می‌شن.


def build_bot_commands():
    return [
        {'command': c['command'], 'description': get_setting('cmd_' + c['command'], c['description']) or c['description']}
        for c in BOT_COMMANDS
    ]


def set_bot_commands():
    try:
        res = SESSION.post(BASE_URL + '/setMyCommands', json={'commands': build_bot_commands()}, timeout=10)
        print('📋 تنظیم منوی دستورات:', res.json())
    except Exception as e:
        print('⚠️ خطا در تنظیم منوی دستورات:', e)


def get_updates(offset=None):
    url = BASE_URL + '/getUpdates'
    # timeout=25: تلگرام تا ۲۵ ثانیه کانکشن رو باز نگه می‌داره تا پیام جدید بیاد
    # (long polling)؛ به محض رسیدن پیام جدید فوراً جواب می‌ده، پس این عدد روی
    # سرعت جواب‌دادن به پیام واقعی تاثیری نداره، فقط تعداد رفت‌وبرگشت‌های
    # الکی به تلگرام رو (وقتی پیامی نیست) کم می‌کنه.
    params = {'timeout': 25}
    if offset:
        params['offset'] = offset
    try:
        res = SESSION.get(url, params=params, timeout=35)
        data = res.json()
        if not data.get('ok'):
            print('⚠️ خطای getUpdates (بات فروش):', data)
        return data
    except Exception as e:
        print('⚠️ استثنا در getUpdates (بات فروش):', e)
        return {'ok': False, 'result': []}


def send_message(chat_id, text, parse_mode='HTML', reply_markup=None):
    url = BASE_URL + '/sendMessage'
    payload = {'chat_id': chat_id, 'text': text}
    if parse_mode:
        payload['parse_mode'] = parse_mode
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    try:
        res = SESSION.post(url, json=payload, timeout=15)
        return res.json()
    except Exception:
        return {'ok': False}


def delete_message(chat_id, message_id):
    """حذف پیام (مثلاً پیامی که کاربر توش رمز نوشته)؛ اگه سرور پشتیبانی نکرد بی‌صدا رد می‌شه."""
    try:
        SESSION.post(BASE_URL + '/deleteMessage', json={'chat_id': chat_id, 'message_id': message_id}, timeout=8)
    except Exception:
        pass


def edit_message(chat_id, message_id, text, parse_mode='HTML', reply_markup=None):
    """متن/دکمه‌های یه پیام از قبل فرستاده‌شده رو آپدیت می‌کنه (به‌جای فرستادن
    پیام تازه) — برای صفحه‌ی انتخاب حجم/روز که با هر بار زدن +/- همون یه پیام
    باید جاش عوض بشه، نه این‌که هر بار یه پیام جدید اضافه بشه."""
    url = BASE_URL + '/editMessageText'
    payload = {'chat_id': chat_id, 'message_id': message_id, 'text': text}
    if parse_mode:
        payload['parse_mode'] = parse_mode
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    try:
        res = SESSION.post(url, json=payload, timeout=15)
        return res.json()
    except Exception:
        return {'ok': False}


def send_photo(chat_id, photo_id, caption=None, parse_mode='HTML', reply_markup=None):
    url = BASE_URL + '/sendPhoto'
    payload = {'chat_id': chat_id, 'photo': photo_id}
    if caption:
        payload['caption'] = caption
    if parse_mode:
        payload['parse_mode'] = parse_mode
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    try:
        res = SESSION.post(url, json=payload, timeout=20)
        return res.json()
    except Exception:
        return {'ok': False}


def generate_qr_png_bytes(data):
    """از روی یه رشته (لینک کانفیگ) یه عکس QR Code به‌صورت PNG (در حافظه) می‌سازه."""
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


def send_photo_bytes(chat_id, image_bytes, filename='qr.png', caption=None, parse_mode='HTML', reply_markup=None):
    """برخلاف send_photo (که فقط file_id یا URL می‌گیره)، این تابع خودِ بایت‌های
    عکس (مثلاً همون چیزی که generate_qr_png_bytes می‌سازه) رو به‌صورت
    multipart/form-data آپلود می‌کنه — برای عکس‌هایی که از قبل روی تلگرام
    وجود ندارن، مثل QR Code تازه‌ساخته‌شده."""
    url = BASE_URL + '/sendPhoto'
    data = {'chat_id': chat_id}
    if caption:
        data['caption'] = caption
    if parse_mode:
        data['parse_mode'] = parse_mode
    if reply_markup:
        data['reply_markup'] = json.dumps(reply_markup)
    files = {'photo': (filename, image_bytes, 'image/png')}
    try:
        res = SESSION.post(url, data=data, files=files, timeout=25)
        return res.json()
    except Exception:
        return {'ok': False}


def _answer_callback_sync(callback_query_id):
    try:
        SESSION.post(BASE_URL + '/answerCallbackQuery', json={'callback_query_id': callback_query_id}, timeout=5)
    except Exception:
        pass


def answer_callback(callback_query_id):
    """جواب‌دادن به callback فقط برای برداشتن «ساعت شنی» دکمه‌ست؛ لازم نیست
    پردازش اصلی منتظرش بمونه، پس تو پس‌زمینه ارسال می‌شه."""
    try:
        BG_EXECUTOR.submit(_answer_callback_sync, callback_query_id)
    except Exception:
        _answer_callback_sync(callback_query_id)


def make_config(gb, label, days, proto='both'):
    try:
        res = SESSION.post(
            CONFIG_API,
            headers={'Authorization': 'Bearer ' + CONFIG_KEY},
            json={'gb': gb, 'label': label, 'expiryDays': days, 'proto': proto},
            timeout=20
        )
        if res.status_code in (200, 201):
            data = res.json()
            return {
                'success': True,
                'sub_url': data.get('subUrl'),
                'config_id': data.get('id') or data.get('uuid') or data.get('username'),
                'data': data
            }
        # اگه پنل با proto_unavailable رد کنه (مثلاً فروش OpenVPN موقتاً بسته
        # باشه)، این خطا رو جدا تشخیص می‌دیم تا پیام مناسب به کاربر نشون بدیم.
        err_code = None
        body_text = None
        try:
            body = res.json()
            err_code = body.get('error') or body.get('message') or body.get('code')
            body_text = body
        except Exception:
            body_text = res.text[:500] if res.text else None
        # این پرینت رو عمداً برای هر خطای ساخت کانفیگ (نه فقط DNS) گذاشتیم؛ چون
        # قبلاً وقتی پنل یه چیزی غیر از 200/201 برمی‌گردوند، هیچ جزئیاتی تو
        # لاگ رایلوی ثبت نمی‌شد و تشخیص علت واقعی (مثلاً proto نامعتبر بودن)
        # غیرممکن بود.
        print('⚠️ خطای ساخت کانفیگ (proto=' + str(proto) + '، کد ' + str(res.status_code) + '):', body_text)
        return {'success': False, 'error': str(res.status_code), 'error_code': err_code}
    except Exception as e:
        print('⚠️ استثنا در ساخت کانفیگ (proto=' + str(proto) + '):', e)
        return {'success': False, 'error': str(e), 'error_code': None}


def gregorian_to_jalali(gy, gm, gd):
    """تبدیل تاریخ میلادی به شمسی (الگوریتم استاندارد، بدون نیاز به هیچ
    پکیج جانبی مثل jdatetime — چون معلوم نیست روی سرور شما نصب باشه)."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gm > 2 and ((gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)):
        gy2 = gy + 1
    else:
        gy2 = gy
    days = (355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) +
            ((gy2 + 399) // 400) + gd + g_d_m[gm - 1])
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + (days % 31)
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def now_iran():
    """ساعت فعلی به وقت ایران (UTC+۳:۳۰). ایران از سال ۱۴۰۱ دیگه ساعت
    تابستانی/زمستانی نداره، پس آفست ثابت +۳:۳۰ همیشه درسته — نیازی به
    pytz/zoneinfo و تنظیمات تایم‌زون سرور نیست."""
    return datetime.utcnow() + timedelta(hours=3, minutes=30)


def fmt_iran_datetime(ts):
    """timestamp → «تاریخ شمسی  ساعت:دقیقه:ثانیه» به وقت ایران."""
    dt = datetime.utcfromtimestamp(ts) + timedelta(hours=3, minutes=30)
    jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
    return f'{jy:04d}/{jm:02d}/{jd:02d}  {dt.strftime("%H:%M:%S")}'


def fmt_duration_fa(seconds):
    """مدت زمان با ثانیه؛ مثلا «۲ ساعت و ۳ دقیقه و ۱۵ ثانیه» (قالب هر واحد از پنل قابل تغییره)."""
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, sec = divmod(rem, 60)
    parts = []
    if h:
        parts.append(u('fa', 'admin_dur_hour', n=h))
    if m:
        parts.append(u('fa', 'admin_dur_minute', n=m))
    if sec or not parts:
        parts.append(u('fa', 'admin_dur_second', n=sec))
    return (' ' + u('fa', 'admin_dur_and') + ' ').join(parts)


def build_topup_timing_text(requested_at, paid_at):
    """بلوک زمان‌بندی برای پیام ادمین (هم رسید ریالی هم رمزارز): زمان درخواست مبلغ، زمان ارسال رسید/هش و فاصله‌ی بینشون."""
    lines = ['\n' + u('fa', 'admin_timing_title')]
    if requested_at:
        lines.append(u('fa', 'admin_timing_requested', time=fmt_iran_datetime(requested_at)))
    else:
        lines.append(u('fa', 'admin_timing_requested_unknown'))
    lines.append(u('fa', 'admin_timing_paid', time=fmt_iran_datetime(paid_at)))
    if requested_at:
        lines.append(u('fa', 'admin_timing_elapsed', duration=fmt_duration_fa(paid_at - requested_at)))
    return '\n'.join(lines)


def build_config_note(chat_id, username, price):
    """متن یادداشتی که رو هر کانفیگ (تو پنل su.randomatic.ir) ثبت می‌شه:
    تاریخ شمسی و ساعت دقیق (با ثانیه) ساخت به وقت ایران، آیدی عددی و
    یوزرنیم خریدار، و مبلغی که برای این کانفیگ پرداخت کرده."""
    dt = now_iran()
    jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
    jalali_date = f'{jy:04d}/{jm:02d}/{jd:02d}'
    time_str = dt.strftime('%H:%M:%S')
    uname = ('@' + username) if username else u('fa', 'no_username')
    return u('fa', 'config_note', jalali_date=jalali_date, time=time_str, chat_id=chat_id,
             username=uname, price=f'{price:,}')


def set_config_note(config_id, note):
    """یادداشت ساخته‌شده توسط build_config_note رو با متد PUT .../note رو
    همون کانفیگ تو پنل سرور ثبت می‌کنه. اگه این درخواست به هر دلیلی (قطعی
    شبکه، تایم‌اوت و ...) شکست بخوره، فقط لاگ می‌شه و در ساخت/تحویل کانفیگ
    به کاربر هیچ خللی ایجاد نمی‌کنه — یعنی خریدار همیشه کانفیگش رو می‌گیره،
    حتی اگه ثبت یادداشت ناموفق باشه."""
    if not config_id:
        return
    try:
        SESSION.put(
            f'{CONFIG_API}/{config_id}/note',
            headers={'Authorization': 'Bearer ' + CONFIG_KEY, 'Content-Type': 'application/json'},
            json={'note': note},
            timeout=10
        )
    except Exception as e:
        print('⚠️ خطا در ثبت یادداشت کانفیگ:', e)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# متن‌ها و دکمه‌های قابل‌تغییر از پنل
# ---------------------------------------------------------------------------
# BUTTON_ACTIONS: تعریف هر آیتم منوی اصلی. کلید (اولین عضو) هیچ‌وقت عوض نمی‌شه
# و همیشه تو callback_data (برای حالت اینلاین) استفاده می‌شه؛ چیزی که از پنل
# قابل‌تغییره فقط «متن» دکمه‌ست (get_button_label) نه این کلید داخلی.
def get_bot_text(key, default):
    return get_setting('text_' + key, default)


def get_bot_text_fmt(key, default, **kwargs):
    """مثل get_bot_text ولی خروجی رو با placeholder های {...} پر می‌کنه.
    اگه مقدار ذخیره‌شده تو پنل placeholder غلط/ناقص داشته باشه (مثلاً ادمین
    اشتباهی یه {چیزی} تایپ کرده)، به‌جای کرش کردن ربات، از متن پیش‌فرض
    استفاده می‌کنیم تا ارسال پیام هیچ‌وقت متوقف نشه."""
    template = get_bot_text(key, default)
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return default.format(**kwargs)


def get_button_label(key, default):
    return get_setting('btn_' + key, default)


def get_button_label_for(chat_id, key, default):
    """مثل get_button_label ولی اگه کاربر زبانش انگلیسی باشه، لیبل ثابت
    انگلیسی رو برمی‌گردونه (چون سفارشی‌سازی از پنل ادمین فقط فارسیه)."""
    if get_user_lang(chat_id) == 'en':
        return get_setting('ui_en_btn_' + key, None) or UI_TEXT['en'].get('btn_' + key, default)
    return get_setting('btn_' + key, default)


def get_keyboard_style():
    v = get_setting('keyboard_style', 'reply')
    return v if v in ('reply', 'inline') else 'reply'


# ---------------------------------------------------------------------------
# متن‌های پیش‌فرض صفحات اصلی ربات (قابل‌تغییر کامل از پنل، صفحه‌ی «متن‌ها و
# ظاهر ربات»). هر متن با placeholder های {...} نوشته شده؛ ادمین می‌تونه کل
# جمله، امـوجی‌ها، ترتیب خط‌ها و حتی حذف/جابه‌جایی مقادیر رو از پنل عوض کنه —
# فقط کافیه اسم placeholder ها دست نخوره.
DEFAULT_WELCOME_INTRO = 'به ربات فروش خوش آمدید'

DEFAULT_MAIN_MENU_TEXT = (
    '✨ <b>{welcome_intro}</b>\n{divider}\n'
    '🔒 فقط وایرگارد: <b>{wireguard_price}</b> تومان/گیگ\n'
    '⚙️ فقط کانفیگ: <b>{config_price}</b> تومان/گیگ\n'
    '🔀 هر دو: <b>{both_price}</b> تومان/گیگ\n'
    '📱 فقط OpenVPN: <b>{openvpn_price}</b> تومان/گیگ\n'
    '🎮 فقط DNS بازی: <b>{dns_price}</b> تومان/گیگ\n'
    '💳 موجودی کیف پول: <b>{wallet}</b> تومان'
)

DEFAULT_BUY_MENU_TEXT = (
    '🛍 نوع سرویس مورد نظر را انتخاب کنید:\n{divider}\n'
    '🔒 فقط وایرگارد: <b>{wireguard_price}</b> تومان/گیگ\n'
    '⚙️ فقط کانفیگ: <b>{config_price}</b> تومان/گیگ\n'
    '🔀 هر دو: <b>{both_price}</b> تومان/گیگ\n'
    '📱 فقط OpenVPN: <b>{openvpn_price}</b> تومان/گیگ\n'
    '🎮 فقط DNS بازی: <b>{dns_price}</b> تومان/گیگ\n\n'
    '💳 موجودی فعلی: <b>{wallet}</b> تومان'
)

DEFAULT_BUY_INSUFFICIENT = '⚠️ موجودی کافی نیست.\n💳 موجودی فعلی: <b>{wallet}</b> تومان'

DEFAULT_ACCOUNT_TEXT = (
    '👤 <b>حساب کاربری شما</b>\n{divider}\n'
    '🆔 شناسه: <code>{chat_id}</code>\n'
    '💳 موجودی کیف پول: <b>{wallet}</b> تومان\n'
    '📊 مجموع خرید: <b>{total_gb}</b> گیگابایت\n'
    '💵 مجموع پرداختی: <b>{total_price}</b> تومان'
)

DEFAULT_MYCONFIGS_HEADER = '🗂 <b>لیست کانفیگ‌های شما</b>'
DEFAULT_MYCONFIGS_EMPTY = '📭 هنوز هیچ کانفیگی ثبت نکرده‌اید.'

DEFAULT_DELETE_PROMPT = '🗑 شماره ردیف کانفیگ مورد نظر برای حذف را ارسال کنید:'
DEFAULT_DELETE_EMPTY = '📭 کانفیگی برای حذف وجود ندارد.'

DEFAULT_TRIAL_USED = '⚠️ شما پیش‌تر از تست رایگان استفاده کرده‌اید.'
DEFAULT_TRIAL_BUILDING = '⏳ در حال ساخت کانفیگ تست...'
DEFAULT_TRIAL_READY = (
    '🎁 <b>کانفیگ تست رایگان شما آماده شد</b>\n{divider}\n'
    '📶 حجم: <b>{trial_gb}</b> گیگابایت\n'
    '⏳ مدت اعتبار: <b>{trial_days}</b> روز\n{divider}\n'
    '🔗 لینک سابسکریپشن:\n<code>{sub_url}</code>'
)
DEFAULT_TRIAL_ERROR = '❌ خطا در ساخت کانفیگ تست. لطفاً بعداً دوباره تلاش کنید.'

DEFAULT_TOPUP_PROMPT = (
    '💠 مبلغ مورد نظر برای شارژ کیف پول را به تومان وارد کنید.\n'
    'حداقل مبلغ شارژ: <b>{min_topup}</b> تومان'
)
DEFAULT_TOPUP_CARD_INFO = (
    '💳 <b>اطلاعات پرداخت</b>\n{divider}\n'
    '💵 مبلغ: <b>{amount}</b> تومان\n'
    '💳 شماره کارت: <code>{card_number}</code>\n'
    '👤 به نام: <b>{card_owner}</b>\n\n'
    '📸 پس از واریز، تصویر رسید را ارسال کنید تا برای بررسی به پشتیبانی ارجاع داده شود.'
)
DEFAULT_TOPUP_NEED_PHOTO = '📸 لطفاً تصویر رسید واریزی را ارسال کنید.'
DEFAULT_TOPUP_RECEIPT_OK = '✅ رسید شما دریافت شد و برای بررسی ارسال گردید. پس از تایید، کیف پول شما شارژ خواهد شد.'

DEFAULT_SUPPORT_PROMPT = '🎧 پیام خود را برای پشتیبانی ارسال کنید:'
DEFAULT_SUPPORT_TICKET_CREATED = '✅ پیام شما با شناسه تیکت #{tid} برای پشتیبانی ثبت شد و به‌زودی پاسخ داده می‌شود.'


def build_quantity_screen(chat_id, step_data):
    """صفحه‌ی انتخاب حجم/روز با دکمه‌های +/- می‌سازه. مقدار وسط (که خودِ عدد
    فعلی رو نشون می‌ده) قابل کلیک نیست، فقط برای نمایشه."""
    ctype = step_data.get('type', 'both')
    cfg_type = get_config_types().get(ctype, get_config_types()['both'])
    ctype_label = get_ctype_label(chat_id, ctype)
    gb = step_data['gb']
    days = step_data['days']
    price = gb * cfg_type['price_per_gb']
    wallet = get_wallet_db(chat_id)

    text = u(
        chat_id, 'qty_screen',
        ctype_label=ctype_label,
        price_per_gb=f"{cfg_type['price_per_gb']:,}",
        wallet=f'{wallet:,}',
        price=f'{price:,}',
    )
    kb = {
        'inline_keyboard': [
            [
                {'text': u(chat_id, 'btn_qty_minus'), 'callback_data': 'qty_gb_dec'},
                {'text': '📶 ' + str(gb) + ' ' + u(chat_id, 'unit_gb'), 'callback_data': 'qty_noop'},
                {'text': u(chat_id, 'btn_qty_plus'), 'callback_data': 'qty_gb_inc'},
            ],
            [
                {'text': u(chat_id, 'btn_qty_minus'), 'callback_data': 'qty_days_dec'},
                {'text': '⏳ ' + str(days) + ' ' + u(chat_id, 'unit_day'), 'callback_data': 'qty_noop'},
                {'text': u(chat_id, 'btn_qty_plus'), 'callback_data': 'qty_days_inc'},
            ],
            [{'text': u(chat_id, 'qty_continue'), 'callback_data': 'qty_confirm'}],
            [{'text': u(chat_id, 'btn_cancel'), 'callback_data': 'menu'}],
        ]
    }
    return text, kb


def send_ask_label_prompt(chat_id):
    send_message(
        chat_id,
        u(chat_id, 'ask_label_prompt'),
        reply_markup={
            'inline_keyboard': [
                [{'text': u(chat_id, 'ask_label_skip'), 'callback_data': 'skip_label'}],
                [{'text': u(chat_id, 'btn_cancel'), 'callback_data': 'menu'}],
            ]
        }
    )


def build_purchase_invoice(chat_id, step_data):
    """یه صفحه‌ی فاکتور واحد می‌سازه (شبیه فاکتور خرید تلگرام): همه‌ی اطلاعات
    سفارش رو یه‌جا نشون می‌ده، و اگه کد تخفیف اعمال شده باشه قیمت قبل/بعد از
    تخفیف رو هم اضافه می‌کنه."""
    ctype = step_data.get('type', 'both')
    ctype_label = get_ctype_label(chat_id, ctype)
    gb = step_data['gb']
    days = step_data['days']
    label = step_data['label']
    base_price = step_data.get('base_price', step_data['price'])
    price = step_data['price']
    discount_code = step_data.get('discount_code')
    discount_percent = step_data.get('discount_percent')

    lines = [
        u(chat_id, 'invoice_title'),
        DIVIDER,
        u(chat_id, 'invoice_type', ctype_label=ctype_label),
        u(chat_id, 'invoice_volume', gb=gb),
        u(chat_id, 'invoice_name', label=label),
        u(chat_id, 'invoice_duration', days=days),
        DIVIDER,
    ]
    if discount_code:
        lines.append(u(chat_id, 'invoice_discount_line', code=discount_code, percent=discount_percent))
        lines.append(u(chat_id, 'invoice_base_price', base_price=base_price))
        lines.append(u(chat_id, 'invoice_final_price', price=price))
    else:
        lines.append(u(chat_id, 'invoice_price', price=price))
    lines.append('')
    lines.append(u(chat_id, 'invoice_footer'))
    return '\n'.join(lines)


def build_purchase_kb(chat_id):
    return {
        'inline_keyboard': [
            [
                {'text': u(chat_id, 'btn_confirm_purchase'), 'callback_data': 'confirm_purchase'},
                {'text': u(chat_id, 'btn_cancel_purchase'), 'callback_data': 'cancel_purchase'},
            ],
            [
                {'text': u(chat_id, 'btn_apply_discount'), 'callback_data': 'ask_discount_code'},
            ],
        ]
    }


def action_buy_menu(chat_id):
    if not is_feature_enabled('buy'):
        send_message(chat_id, u(chat_id, 'disabled_feature'))
        return
    wallet = get_wallet_db(chat_id)
    ct = get_config_types()
    user_steps[str(chat_id)] = {}
    order = get_ordered_keys('menu_order_buytypes', ['wireguard', 'config', 'both', 'openvpn', 'dns'])
    # قیمت هر نوع سرویس رو مستقیم رو خودِ دکمه می‌ذاریم (نه فقط تو متن پیام)،
    # چون هر بار که این کیبورد ساخته می‌شه ct از get_config_types() (یعنی از
    # جدول settings) خونده شده، پس با تغییر قیمت از پنل، متن دکمه هم بدون نیاز
    # به ری‌استارت به‌روز می‌شه. دکمه‌ها اینلاین‌ان و HTML رو نشون نمی‌دن، پس
    # اینجا قیمت رو بدون تگ <b> می‌چسبونیم.
    unit_suffix = u(chat_id, 'price_unit_suffix')
    type_kb = {
        'inline_keyboard': [
            [{
                'text': f"{get_ctype_label(chat_id, k)}: {ct[k]['price_per_gb']:,}{unit_suffix}",
                'callback_data': 'buytype_' + k,
            }]
            for k in order
        ]
    }
    if get_user_lang(chat_id) == 'en':
        text = u(
            chat_id, 'buy_menu_text',
            wireguard_price=f"{ct['wireguard']['price_per_gb']:,}",
            config_price=f"{ct['config']['price_per_gb']:,}",
            both_price=f"{ct['both']['price_per_gb']:,}",
            openvpn_price=f"{ct['openvpn']['price_per_gb']:,}",
            dns_price=f"{ct['dns']['price_per_gb']:,}",
            wallet=f'{wallet:,}',
            divider=DIVIDER,
        )
    else:
        text = get_bot_text_fmt(
            'buy_menu', DEFAULT_BUY_MENU_TEXT,
            wireguard_price=f"{ct['wireguard']['price_per_gb']:,}",
            config_price=f"{ct['config']['price_per_gb']:,}",
            both_price=f"{ct['both']['price_per_gb']:,}",
            openvpn_price=f"{ct['openvpn']['price_per_gb']:,}",
            dns_price=f"{ct['dns']['price_per_gb']:,}",
            wallet=f'{wallet:,}',
            divider=DIVIDER,
        )
    send_message(chat_id, text, reply_markup=type_kb)


# ---------------------------------------------------------------------------
# شارژ با رمزارز (دستی) — لیست کوین‌ها از پنل، قیمت لحظه‌ای از نوبیتکس
# ---------------------------------------------------------------------------
def get_crypto_coins():
    """رمزارزهای فعال و قابل‌استفاده از پنل: [{'id','label','symbol','wallet'}].
    کوینی که آدرس ولت نداشته باشه نشون داده نمی‌شه."""
    raw = get_setting('crypto_coins', None)
    if raw is None:
        data = []
    else:
        try:
            data = json.loads(raw)
        except Exception:
            data = []
    coins = []
    for c in data if isinstance(data, list) else []:
        if not isinstance(c, dict) or not c.get('enabled', True):
            continue
        symbol = str(c.get('symbol') or '').strip().lower()
        wallet = str(c.get('wallet') or '').strip()
        if symbol and wallet:
            coins.append({'id': str(c.get('id') or symbol), 'label': str(c.get('label') or symbol),
                          'symbol': symbol, 'wallet': wallet,
                          'memo': str(c.get('memo') or '').strip(),
                          'network': str(c.get('network') or '').strip()})
    return coins


def crypto_enabled():
    return get_setting('crypto_enabled', '1') == '1' and bool(get_crypto_coins())


def card_topup_enabled():
    """شارژ کارت‌به‌کارت (ریالی) — از پنل ادمین، صفحه‌ی «رمزارزها» روشن/خاموش می‌شه (کلید card_topup_enabled)."""
    return get_setting('card_topup_enabled', '1') == '1'


_crypto_price_cache = {}
_CRYPTO_PRICE_TTL = 5   # ثانیه: کش خیلی کوتاه، تا قیمت قدیمی به کاربر داده نشه

# --- حفاظت از ضرر ---
# قیمتی که به کاربر نشون داده می‌شه «محافظه‌کارانه» حساب می‌شه:
#  ۱) از بین «آخرین معامله» و «بهترین قیمت خرید» (قیمتی که واقعاً می‌تونی کوین رو باهاش بفروشی) کمترش انتخاب می‌شه
#  ۲) یه درصد حاشیه‌ی اطمینان از قیمت کم می‌شه (پیش‌فرض ۱٪) تا اگه قیمت تا لحظه‌ی واریز افت کرد، ضرر نکنی
# هرچی قیمت کمتر باشه، مقدار کوین قابل واریز بیشتره. درصد حاشیه از جدول settings
# با کلید crypto_margin_percent قابل تغییره (مثلا 0 = بدون حاشیه، 2 = دو درصد).
# اگه نوبیتکس جواب نده، عمداً از قیمت قدیمی استفاده نمی‌شه و به کاربر خطا نشون داده می‌شه.
_CRYPTO_DEFAULT_MARGIN_PERCENT = 1.0


def get_crypto_margin_percent():
    try:
        v = float(str(get_setting('crypto_margin_percent', str(_CRYPTO_DEFAULT_MARGIN_PERCENT))).replace(',', '.'))
    except Exception:
        v = _CRYPTO_DEFAULT_MARGIN_PERCENT
    return min(max(v, 0.0), 20.0)


def get_crypto_price_toman(symbol, raw=False):
    """قیمت محافظه‌کارانه‌ی هر واحد کوین به تومان (جفت‌ارز symbol-rls تو نوبیتکس) یا None.
    مینیمم «آخرین معامله» و «بهترین قیمت خرید» منهای حاشیه‌ی اطمینان. ۵ ثانیه کش می‌شه."""
    symbol = str(symbol or '').strip().lower()
    if not symbol:
        return None
    now = time.time()
    cache_key = symbol + ('|raw' if raw else '')
    hit = _crypto_price_cache.get(cache_key)
    if hit and now - hit[0] < _CRYPTO_PRICE_TTL:
        return hit[1]
    try:
        # طبق مستندات نوبیتکس این endpoint متد POST با بدنه‌ی JSON هست
        r = None
        last_err = None
        for base in NOBITEX_API_BASES:
            try:
                r = SESSION.post(base + '/market/stats',
                                 json={'srcCurrency': symbol, 'dstCurrency': 'rls'}, timeout=12)
                break
            except requests.exceptions.RequestException as ce:   # DNS/اتصال: آدرس بعدی
                last_err = ce
                print(f'⚠️ اتصال به {base} ممکن نشد:', ce)
        if r is None:
            raise last_err or RuntimeError('no Nobitex base URL configured')
        if r.status_code != 200:
            raise RuntimeError(f'HTTP {r.status_code}: {r.text[:200]}')
        data = r.json()
        if data.get('status') != 'ok':
            raise RuntimeError(f'status={data.get("status")} {str(data)[:200]}')
        st = (data.get('stats') or {}).get(f'{symbol}-rls') or {}
        latest = float(st.get('latest') or 0)
        best_buy = float(st.get('bestBuy') or 0)
        if raw and (latest > 0 or best_buy > 0):
            # قیمت خام بازار (بدون حاشیه‌ی اطمینان) فقط برای نمایش تقریبی تو «صرافی»
            val = (latest if latest > 0 else best_buy) / 10.0
            _crypto_price_cache[cache_key] = (now, val)
            return val
        candidates = [x for x in (latest, best_buy) if x > 0]
        if candidates:
            base_rial = min(candidates)
            margin = get_crypto_margin_percent()
            val = base_rial / 10.0 * (1.0 - margin / 100.0)      # ریال → تومان، منهای حاشیه
            if val > 0:
                _crypto_price_cache[cache_key] = (now, val)
                return val
        print(f'⚠️ قیمت {symbol} تو پاسخ نوبیتکس نبود:', str(st)[:200])
    except Exception as e:
        print(f'⚠️ قیمت {symbol} از نوبیتکس گرفته نشد:', e)
    return None


def send_card_topup_info(chat_id, amount):
    user_steps[str(chat_id)] = {'step': 'waiting_receipt', 'amount': amount, 'requested_at': time.time()}
    if get_user_lang(chat_id) == 'en':
        card_text = u(
            chat_id, 'topup_card_info', amount=f'{amount:,}',
            card_number=get_card_number(), card_owner=get_card_owner(), divider=DIVIDER,
        )
    else:
        card_text = get_bot_text_fmt(
            'topup_card_info', DEFAULT_TOPUP_CARD_INFO,
            amount=f'{amount:,}',
            card_number=get_card_number(),
            card_owner=get_card_owner(),
            divider=DIVIDER,
        )
    send_message(chat_id, card_text)


def _looks_like_tx_hash(text):
    """هش تراکنش / لینک اکسپلورر: یه متن پیوسته (بدون فاصله) بین ۱۶ تا ۳۰۰ کاراکتر."""
    t = (text or '').strip()
    return (not t.startswith('/')) and bool(re.fullmatch(r'\S{16,300}', t))


def fmt_coin_amount(x):
    """مقدار کوین با حداقل ۲ رقم اعشار (مثلا 0.30)؛ صفرهای اضافه‌ی آخر حذف می‌شه."""
    t = ('%.8f' % float(x)).rstrip('0')
    ip, _, fp = t.partition('.')
    return (ip or '0') + '.' + fp.ljust(2, '0')


def round_coin_amount(amount, price):
    """مقدار کوین قابل واریز = amount ÷ price که همیشه «به بالا» و با حداکثر ۲ رقم اعشار گرد می‌شه
    (مثلا 0.2965 → 0.30). اگه گرد کردن به ۲ رقم باعث بشه کاربر بیشتر از «حداکثر اضافه‌پرداخت» (پیش‌فرض ۵٪،
    کلید crypto_round_max_over_percent تو settings) بده — مثل کوین‌های گرون مثل بیت‌کوین — خودکار
    اعشار بیشتری (تا ۸ رقم) استفاده می‌شه تا کاربر چند برابر مبلغ رو نده."""
    try:
        max_over = float(str(get_setting('crypto_round_max_over_percent', '5')).replace(',', '.'))
    except Exception:
        max_over = 5.0
    max_over = min(max(max_over, 0.0), 100.0)
    exact = amount / price
    limit = amount * (1.0 + max_over / 100.0)
    coin_amount = exact
    for d in range(2, 9):
        factor = 10 ** d
        coin_amount = math.ceil(round(exact * factor, 6)) / factor
        if coin_amount * price <= limit:
            break
    return coin_amount


def send_crypto_topup_info(chat_id, amount, coin):
    price = get_crypto_price_toman(coin['symbol'])
    if not price:
        send_message(chat_id, u(chat_id, 'topup_crypto_price_error'), reply_markup=cancel_kb(chat_id))
        return
    # مقدار کوین = مبلغ شارژ (تومان) ÷ قیمت هر واحد (تومان). مثلا ۱۰۰٬۰۰۰ ÷ ۴۰۰٬۰۰۰ = 0.25
    # به بالا گرد می‌شه تا کاربر کمتر از مبلغ واریز نکنه. تعداد اعشار بسته به قیمت کوین تنظیم می‌شه
    # (حداقل ۴ و حداکثر ۸ رقم) تا برای کوین‌های گرون مثل بیت‌کوین مبلغ واریزی چند برابر نشه.
    coin_amount = round_coin_amount(amount, price)
    # Memo/Comment فقط وقتی تو پنل پر شده باشه نشون داده می‌شه؛ خالی باشه هیچی نمایش داده نمی‌شه
    memo_line, network_line = _crypto_memo_network_lines(chat_id, coin)
    user_steps[str(chat_id)] = {'step': 'waiting_receipt', 'amount': amount, 'method': 'crypto',
                                'requested_at': time.time(), 'coin_label': coin['label'], 'coin_amount': coin_amount, 'price': price,
                                'coin_symbol': coin['symbol']}
    send_message(chat_id, u(chat_id, 'topup_crypto_info', divider=DIVIDER, amount=f'{amount:,}',
                            price=f'{price:,.0f}', coin=_html.escape(coin['label']),
                            coin_amount=fmt_coin_amount(coin_amount), wallet=_html.escape(coin['wallet']),
                            memo_line=memo_line, network_line=network_line))


_PERSIAN_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def parse_coin_amount_text(text):
    """«0.2 ton» / «۰٫۲» / «0,2 TON» → (مقدار, نماد یا None)؛ اگه قابل‌فهم نبود None."""
    t = (text or '').strip().translate(_PERSIAN_DIGITS).replace('٫', '.').replace('٬', '')
    if ',' in t and '.' in t:
        t = t.replace(',', '')
    elif ',' in t:
        t = t.replace(',', '.')
    m = re.fullmatch(r'([0-9]*\.?[0-9]+)\s*([A-Za-z]{2,10})?', t)
    if not m:
        return None
    try:
        qty = float(m.group(1))
    except Exception:
        return None
    if not (0 < qty < 1e9):
        return None
    return qty, ((m.group(2) or '').lower() or None)


def _crypto_memo_network_lines(chat_id, coin):
    memo = str(coin.get('memo') or '').strip()
    memo_line = ('\n' + u(chat_id, 'crypto_memo_line', memo=_html.escape(memo)) + '\n') if memo else ''
    network = str(coin.get('network') or '').strip()
    network_line = (u(chat_id, 'crypto_network_line', network=_html.escape(network)) + '\n\n') if network else ''
    return memo_line, network_line


def send_crypto_deposit_info(chat_id, coin):
    """جریان جدید: آدرس/شبکه/Memo رو نشون می‌ده و منتظر می‌مونه کاربر «مقدار واریزی» رو بنویسه (مثلاً 0.2 TON)."""
    memo_line, network_line = _crypto_memo_network_lines(chat_id, coin)
    user_steps[str(chat_id)] = {'step': 'crypto_declare_amount', 'method': 'crypto', 'requested_at': time.time(),
                                'coin_symbol': coin['symbol'], 'coin_label': coin['label']}
    send_message(chat_id, u(chat_id, 'topup_crypto_info2', divider=DIVIDER, coin=_html.escape(coin['label']),
                            symbol=_html.escape(coin['symbol'].upper()), wallet=_html.escape(coin['wallet']),
                            memo_line=memo_line, network_line=network_line,
                            min_topup=f'{get_min_topup_crypto():,}'),
                 reply_markup=cancel_kb(chat_id))


def start_crypto_topup(chat_id):
    coins = get_crypto_coins() if crypto_enabled() else []
    if not coins:
        user_steps[str(chat_id)] = {}
        send_message(chat_id, u(chat_id, 'disabled_feature'))
    elif len(coins) == 1:
        send_crypto_deposit_info(chat_id, coins[0])
    else:
        user_steps[str(chat_id)] = {'step': 'choose_topup_coin'}
        send_message(chat_id, u(chat_id, 'topup_choose_coin'), reply_markup={'inline_keyboard': (
            [[{'text': c['label'], 'callback_data': 'tpc_' + c['id']}] for c in coins]
            + [[{'text': u(chat_id, 'btn_cancel'), 'callback_data': 'menu'}]])})


def handle_crypto_declared_amount(chat_id, step, text):
    """کاربر نوشته چقدر واریز کرده (مثلاً «0.2 ton»): معادل تومانی رو نشون می‌دیم، درخواست می‌سازیم
    و همون لحظه تو نوبیتکس چک می‌کنیم."""
    coins = get_crypto_coins() if crypto_enabled() else []
    coin = next((c for c in coins if c['symbol'] == step.get('coin_symbol')), None)
    if not coin:
        user_steps[str(chat_id)] = {}
        send_message(chat_id, u(chat_id, 'disabled_feature'))
        return
    symbol_up = _html.escape(coin['symbol'].upper())
    parsed = parse_coin_amount_text(text)
    if not parsed:
        send_message(chat_id, u(chat_id, 'topup_crypto_bad_amount', symbol=symbol_up), reply_markup=cancel_kb(chat_id))
        return
    qty, sym = parsed
    if sym and sym not in (coin['symbol'].lower(), str(coin['label']).strip().lower()):
        send_message(chat_id, u(chat_id, 'topup_crypto_coin_mismatch', coin=_html.escape(coin['label']), symbol=symbol_up),
                     reply_markup=cancel_kb(chat_id))
        return
    price = get_crypto_price_toman(coin['symbol'])
    if not price:
        send_message(chat_id, u(chat_id, 'topup_crypto_price_error'), reply_markup=cancel_kb(chat_id))
        return
    amount = int(qty * price)         # قیمت محافظه‌کارانه (با حاشیه‌ی اطمینان) → مبلغ شارژ تومانی
    if amount < get_min_topup_crypto():
        send_message(chat_id, u(chat_id, 'topup_crypto_below_min', amount=f'{amount:,}',
                                min_topup=f'{get_min_topup_crypto():,}'), reply_markup=cancel_kb(chat_id))
        return
    req_id = None
    prev_id = get_latest_pending_crypto_request(chat_id)      # همون مقدار دوباره فرستاده شد: درخواست تکراری نساز
    if prev_id:
        prev = get_crypto_request_row(prev_id)
        try:
            if prev and str(prev[5]).lower() == coin['symbol'] and abs(float(prev[6]) - qty) < 1e-12:
                req_id = prev_id
        except Exception:
            pass
    if req_id is None:
        req_id = create_topup_request(chat_id, amount, 'crypto', f"{fmt_coin_amount(qty)} {coin['label']}", price,
                                      coin_symbol=coin['symbol'], coin_qty=qty, tx_hash=None,
                                      req_ts=step.get('requested_at') or time.time())
    user_steps[str(chat_id)] = {'step': 'crypto_send_hash', 'req_id': req_id}     # پیام بعدی (هش) مستقیم به همین درخواست وصل می‌شه
    send_message(chat_id, u(chat_id, 'topup_crypto_declared', coin_amount=fmt_coin_amount(qty), coin=symbol_up,
                            amount=f'{amount:,}', price=f'{price:,.0f}'))
    check_crypto_for_user_async(chat_id, req_id, 'declared')


def check_crypto_for_user_async(chat_id, req_id, stage):
    """چک فوری نوبیتکس + اطلاع‌رسانی به کاربر. stage: 'declared' (بعد از اعلام مقدار) یا 'hash' (بعد از ارسال هش).
    تأیید خودکار فقط وقتی انجام می‌شه که crypto_auto_confirm تو پنل روشن باشه."""
    def _run():
        try:
            res = {'state': 'error', 'note': 'کلید API نوبیتکس تنظیم نشده'}
            if nobitex_keys_configured():
                try:
                    nobitex_fetch_deposits(force=True)          # کش رد بشه تا واریز لحظه‌ای هم دیده بشه
                except Exception as e:
                    print('⚠️ نوبیتکس:', e)
                res = evaluate_crypto_request(req_id)
                handle_crypto_eval(req_id, res, force_notify=(stage == 'hash'))
            row = get_crypto_request_row(req_id)
            if not row or row[3] != 'pending':
                return                      # تأیید شد (پیام شارژ از approve_topup_request رفته) یا ادمین بسته
            st = res.get('state')
            if stage == 'declared' and st in ('not_found', 'error'):
                try:
                    price_txt = f"{float(row[10]):,.0f}"
                except Exception:
                    price_txt = str(row[10])
                send_message(ADMIN_ID, u('fa', 'admin_topup_request_crypto', divider=DIVIDER, user_id=str(row[1]),
                                         amount=f'{row[2]:,}', req_id=str(req_id),
                                         coin_amount=fmt_coin_amount(row[6]), coin=_html.escape(str(row[5]).upper()),
                                         price=price_txt),
                             reply_markup={'inline_keyboard': [[
                                 {'text': u('fa', 'admin_btn_accept'), 'callback_data': 'topup_acc_' + str(req_id)},
                                 {'text': u('fa', 'admin_btn_reject'), 'callback_data': 'topup_rej_' + str(req_id)}]]})
            if st in ('hash_ok', 'matched'):
                user_steps[str(chat_id)] = {}
                send_message(chat_id, u(chat_id, 'topup_crypto_found_wait_admin'))
            elif st == 'unconfirmed':
                user_steps[str(chat_id)] = {}
                send_message(chat_id, u(chat_id, 'topup_crypto_unconfirmed'))
            elif stage == 'declared':
                send_message(chat_id, u(chat_id, 'topup_crypto_ask_hash'), reply_markup={'inline_keyboard': [[
                    {'text': u(chat_id, 'btn_send_hash'), 'callback_data': 'sendhash'}]]})
            else:
                send_message(chat_id, u(chat_id, 'topup_crypto_not_found_admin'))
        except Exception as e:
            print('⚠️ check_crypto_for_user_async:', e)
    threading.Thread(target=_run, daemon=True).start()


def show_topup_method_choice(chat_id):
    """مرحله‌ی اول شارژ: انتخاب روش پرداخت (قبل از پرسیدن مبلغ)."""
    user_steps[str(chat_id)] = {'step': 'choose_topup_method'}
    send_message(chat_id, u(chat_id, 'topup_choose_method_first'), reply_markup={
        'inline_keyboard': [
            [{'text': u(chat_id, 'btn_topup_card'), 'callback_data': 'tpm_card'}],
            [{'text': u(chat_id, 'btn_topup_crypto'), 'callback_data': 'tpm_crypto'}],
            [{'text': u(chat_id, 'btn_cancel'), 'callback_data': 'menu'}],
        ]})


def ask_topup_amount_for(chat_id, method):
    """بعد از انتخاب روش، مبلغ رو می‌پرسه (حداقل شارژ هر روش جدا حساب می‌شه)."""
    user_steps[str(chat_id)] = {'step': 'ask_topup_amount', 'method': method}
    min_txt = f'{get_min_topup_for(method):,}'
    text = (u(chat_id, 'topup_prompt', min_topup=min_txt) if get_user_lang(chat_id) == 'en'
            else get_bot_text_fmt('topup_prompt', DEFAULT_TOPUP_PROMPT, min_topup=min_txt))
    send_message(chat_id, text, reply_markup=cancel_kb(chat_id))


def show_coin_choice(chat_id, amount, coins):
    """اگه فقط یه رمزارز فعاله مستقیم اطلاعات واریز، وگرنه لیست انتخاب رمزارز."""
    if len(coins) == 1:
        send_crypto_topup_info(chat_id, amount, coins[0])
        return
    user_steps[str(chat_id)] = {'step': 'choose_topup_coin', 'amount': amount}
    send_message(chat_id, u(chat_id, 'topup_choose_coin'), reply_markup={'inline_keyboard': (
        [[{'text': c['label'], 'callback_data': 'tpc_' + c['id']}] for c in coins]
        + [[{'text': u(chat_id, 'btn_cancel'), 'callback_data': 'menu'}]])})


def proceed_after_topup_amount(chat_id, amount, method):
    """مبلغ وارد شده و معتبره: کارت‌به‌کارت → اطلاعات کارت؛ رمزارز → انتخاب کوین/اطلاعات ولت."""
    if method == 'crypto':
        coins = get_crypto_coins() if crypto_enabled() else []
        if not coins:
            user_steps[str(chat_id)] = {}
            send_message(chat_id, u(chat_id, 'disabled_feature'))
        else:
            show_coin_choice(chat_id, amount, coins)
    else:
        if card_topup_enabled():
            send_card_topup_info(chat_id, amount)
        else:
            user_steps[str(chat_id)] = {}
            send_message(chat_id, u(chat_id, 'disabled_feature'))


def action_topup_menu(chat_id):
    if not is_feature_enabled('topup'):
        send_message(chat_id, u(chat_id, 'disabled_feature'))
        return
    card_on, crypto_on = card_topup_enabled(), crypto_enabled()
    if card_on and crypto_on:
        show_topup_method_choice(chat_id)          # اول روش پرداخت رو می‌پرسه
    elif card_on:
        ask_topup_amount_for(chat_id, 'card')      # فقط یه روش فعاله: مستقیم مبلغ
    elif crypto_on:
        start_crypto_topup(chat_id)
    else:
        send_message(chat_id, u(chat_id, 'disabled_feature'))


# کدهای خطای پنل که یعنی «این کاربر قبلاً تست گرفته». اگه کد واقعی پنل فرق داره اینجا اضافه کن.
TRIAL_USED_PANEL_CODES = ('trial_already_used', 'trial_used', 'already_used', 'already_received', 'free_trial_used')


def action_trial(chat_id):
    if not is_feature_enabled('trial'):
        send_message(chat_id, u(chat_id, 'disabled_feature'))
        return
    lang = get_user_lang(chat_id)
    if check_free_trial(chat_id) > 0:
        send_message(chat_id, u(chat_id, 'trial_used') if lang == 'en' else get_bot_text('trial_used', DEFAULT_TRIAL_USED))
        return
    send_message(chat_id, u(chat_id, 'trial_building') if lang == 'en' else get_bot_text('trial_building', DEFAULT_TRIAL_BUILDING))
    trial_gb, trial_days, trial_label = get_trial_gb(), get_trial_days(), get_trial_label()
    res = make_config(trial_gb, trial_label, trial_days)
    if res['success'] and res['sub_url']:
        set_free_trial(chat_id)
        save_user_config(chat_id, res['sub_url'], res['config_id'], trial_gb, trial_label, trial_days, 0)
        set_config_note(res['config_id'], build_config_note(chat_id, get_username_db(chat_id), 0))
        if lang == 'en':
            trial_text = u(chat_id, 'trial_ready', sub_url=str(res['sub_url']), divider=DIVIDER,
                           trial_gb='%g' % trial_gb, trial_days=str(trial_days))
        else:
            trial_text = get_bot_text_fmt(
                'trial_ready', DEFAULT_TRIAL_READY,
                sub_url=str(res['sub_url']), divider=DIVIDER,
                trial_gb='%g' % trial_gb, trial_days=str(trial_days),
            )
        send_message(chat_id, trial_text)
    else:
        # فقط وقتی پنل صراحتاً بگه «این تست قبلاً گرفته شده» کاربر رو ثبت می‌کنیم.
        # استثناهای شبکه (error_code=None) و خطاهای عمومی نباید کاربر رو برای
        # همیشه «تست‌گرفته» کنن؛ در این حالت فقط پیام خطا نشون داده می‌شه و
        # کاربر می‌تونه دوباره تلاش کنه.
        err_code = str(res.get('error_code') or '').lower()
        if err_code and any(k in err_code for k in TRIAL_USED_PANEL_CODES):
            set_free_trial(chat_id)
            send_message(chat_id, u(chat_id, 'trial_used_on_panel'))
        else:
            print('⚠️ تست رایگان ناموفق برای', chat_id, ':', res)
            send_message(chat_id, u(chat_id, 'trial_error') if lang == 'en' else get_bot_text('trial_error', DEFAULT_TRIAL_ERROR))


# لینک‌های دانلود برنامه‌ی V2Pro (با متغیر محیطی هم قابل تغییرن)
APP_DOWNLOAD_LINKS = [
    ('android', os.getenv('APP_LINK_ANDROID', 'https://play.google.com/store/apps/details?id=com.v2pro.client')),
    ('ios', os.getenv('APP_LINK_IOS', 'https://apps.apple.com/us/app/v2pro/id6801607092')),
    ('windows', os.getenv('APP_LINK_WINDOWS', 'https://su.randomatic.ir/v2pro/1.1.2/V2Pro-Setup-x64.exe')),
    ('mac', os.getenv('APP_LINK_MAC', 'https://su.randomatic.ir/v2pro/1.1.2/v2pro-macos-universal.zip')),
    ('linux', os.getenv('APP_LINK_LINUX', 'https://su.randomatic.ir/v2pro/1.1.2/v2pro-linux-x64.tar.gz')),
]


def _reseller_creds_start(chat_id):
    """مرحله‌ی ۱: گرفتن نام کاربری (بعد از اون رمز). تا کامل نشه، تو منو دکمه‌ی تغییر هست."""
    user_steps[str(chat_id)] = {'step': 'reseller_set_username'}
    send_message(chat_id, u(chat_id, 'reseller_ask_username', min_len=3, max_len=20),
                 reply_markup=cancel_kb(chat_id))


def action_reseller_menu(chat_id):
    if not is_feature_enabled('reseller'):
        send_message(chat_id, u(chat_id, 'disabled_feature'))
        return
    _action_reseller_menu(chat_id)


def _action_reseller_menu(chat_id):
    """صفحه‌ی فروشندگی: اگه هنوز فروشنده نشده، پیشنهاد فعال‌سازی؛ وگرنه
    پنل کوچیکش (موجودی استخر، کلید API، افزایش استخر)."""
    row = get_reseller(chat_id)
    if not row:
        activation_price = round(get_reseller_min_gb() * get_reseller_price_per_gb())
        send_message(
            chat_id,
            u(chat_id, 'reseller_intro', divider=DIVIDER, price_per_gb=f'{get_reseller_price_per_gb():,}',
              min_gb=get_reseller_min_gb(), activation_price=f'{activation_price:,}'),
            reply_markup={'inline_keyboard': [[
                {'text': u(chat_id, 'btn_reseller_activate'), 'callback_data': 'reseller_activate'}
            ]]}
        )
        return
    _, _api_key, _secret_hash, gb_balance, price_per_gb, status, _created = row
    uname = get_reseller_username(chat_id)
    creds_line = (u(chat_id, 'reseller_creds_line', username=uname) if uname else u(chat_id, 'reseller_creds_missing'))
    status_label = u(chat_id, 'reseller_status_active') if status == 'active' else u(chat_id, 'reseller_status_blocked')
    send_message(
        chat_id,
        u(chat_id, 'reseller_dashboard', divider=DIVIDER, gb_balance=('%g' % gb_balance),
          price_per_gb=reseller_price_range_text(chat_id), status=status_label, creds_line=creds_line,
          panel_url=get_reseller_panel_url()),
        reply_markup={'inline_keyboard': [
            [{'text': u(chat_id, 'btn_reseller_topup'), 'callback_data': 'reseller_topup'}],
            [{'text': u(chat_id, 'btn_reseller_regen'), 'callback_data': 'reseller_creds'}],
        ]}
    )


def action_guide(chat_id):
    if not is_feature_enabled('guide'):
        send_message(chat_id, u(chat_id, 'disabled_feature'))
        return
    _action_guide(chat_id)


def _action_guide(chat_id):
    """دکمه‌ی «دانلود برنامه»: برای هر سیستم‌عامل یه دکمه‌ی لینک‌دار می‌فرسته. اگه
    پیام‌رسان دکمه‌ی url رو قبول نکرد، همون لینک‌ها به‌صورت متن ساده فرستاده می‌شن."""
    rows = [[{'text': u(chat_id, 'plat_' + key), 'url': url}] for key, url in get_app_links()]
    res = send_message(chat_id, u(chat_id, 'guide_text', divider=DIVIDER), reply_markup={'inline_keyboard': rows})
    if not (isinstance(res, dict) and res.get('ok')):
        lines = [u(chat_id, 'guide_fallback_title'), DIVIDER]
        for key, url in get_app_links():
            lines.append(u(chat_id, 'plat_' + key) + ':\n' + url)
        send_message(chat_id, '\n'.join(lines))


def action_account(chat_id):
    wallet = get_wallet_db(chat_id)
    tg, tp = get_total_purchases(chat_id)
    if get_user_lang(chat_id) == 'en':
        profile_text = u(
            chat_id, 'account_info', chat_id=str(chat_id), wallet=f'{wallet:,}',
            total_gb=f'{tg:,.1f}', total_price=f'{tp:,.0f}', divider=DIVIDER,
        )
    else:
        profile_text = get_bot_text_fmt(
            'account_info', DEFAULT_ACCOUNT_TEXT,
            chat_id=str(chat_id),
            wallet=f'{wallet:,}',
            total_gb=f'{tg:,.1f}',
            total_price=f'{tp:,.0f}',
            divider=DIVIDER,
        )
    send_message(chat_id, profile_text)


def build_usage_bar(used_gb, total_gb, segments=10):
    """نوار پیشرفتِ متنی مصرف (شبیه اسکرین‌شات‌های اپ‌های VPN): ▰ برای بخش
    مصرف‌شده، ▱ برای باقی‌مانده."""
    try:
        total_gb = float(total_gb or 0)
        used_gb = float(used_gb or 0)
    except (TypeError, ValueError):
        total_gb, used_gb = 0, 0
    pct = 0.0 if total_gb <= 0 else max(0.0, min(1.0, used_gb / total_gb))
    filled = max(0, min(segments, int(round(pct * segments))))
    return '▰' * filled + '▱' * (segments - filled)


def days_remaining(expires_at):
    """چند روز تا انقضا مونده (گرد به بالا)؛ اگه گذشته باشه صفر برمی‌گردونه."""
    if not expires_at:
        return 0
    try:
        exp = datetime.fromisoformat(expires_at)
    except Exception:
        return 0
    diff = (exp - datetime.now()).total_seconds()
    if diff <= 0:
        return 0
    return math.ceil(diff / 86400)


def action_my_configs(chat_id):
    configs = get_user_configs(chat_id)
    if not configs:
        send_message(chat_id, u(chat_id, 'myconfigs_empty') if get_user_lang(chat_id) == 'en'
                      else get_bot_text('myconfigs_empty', DEFAULT_MYCONFIGS_EMPTY))
        return
    if get_user_lang(chat_id) == 'en':
        txt = u(chat_id, 'myconfigs_header') + '\n' + DIVIDER + '\n\n'
    else:
        txt = get_bot_text('myconfigs_header', DEFAULT_MYCONFIGS_HEADER) + '\n' + DIVIDER + '\n\n'
    manage_rows = []
    for i, cfg in enumerate(configs, 1):
        ctype = cfg[9] if len(cfg) > 9 else 'both'
        ctype_label = get_ctype_label(chat_id, ctype)
        status = cfg[10] if len(cfg) > 10 else 'active'
        remaining_days = days_remaining(cfg[8])
        gb_total = cfg[3] or 0

        if status == 'paused':
            status_text = u(chat_id, 'myconfigs_status_paused')
        elif remaining_days <= 0:
            status_text = u(chat_id, 'myconfigs_status_expired')
        else:
            status_text = u(chat_id, 'myconfigs_status_active')

        used_gb = get_config_usage_gb(cfg[2])
        if used_gb is None:
            txt += (
                '<b>' + str(i) + '. ' + str(cfg[4]) + '</b> ' + status_text + '\n' +
                u(chat_id, 'myconfigs_usage_unknown') + '\n\n'
            )
        else:
            used_gb = max(0.0, float(used_gb))
            remaining_gb = max(0.0, gb_total - used_gb)
            bar = build_usage_bar(used_gb, gb_total)
            txt += u(
                chat_id, 'myconfigs_card',
                idx=i, label=str(cfg[4]), status=status_text, bar=bar,
                gb=f'{gb_total:g}', remaining_gb=f'{remaining_gb:.2f}', used_gb=f'{used_gb:.2f}',
                remaining_days=remaining_days, ctype_label=ctype_label, sub_url=str(cfg[1]),
            ) + '\n\n'
        btn_label = str(cfg[4])[:20]
        manage_rows.append([{
            'text': u(chat_id, 'btn_manage_config', idx=i, label=btn_label),
            'callback_data': 'managecfg_' + str(cfg[0])
        }])
    send_message(chat_id, txt, reply_markup={'inline_keyboard': manage_rows})


def send_manage_panel(chat_id, cfg, note=None):
    """پنل «مدیریت کانفیگ» رو می‌سازه و می‌فرسته. دکمه‌ی قطع/وصل فقط یکیه و بر
    اساس وضعیت فعلیِ کانفیگ (active/paused) متن و عملکردش عوض می‌شه، تا به‌جای
    دو دکمه‌ی جدا («توقف» و «از سرگیری» که همیشه هر دو نشون داده می‌شدن)، کاربر
    فقط یک دکمه ببینه که همیشه کار درست (متضاد وضعیت فعلی) رو انجام می‌ده."""
    row_id = cfg[0]
    status = cfg[10] if len(cfg) > 10 else 'active'
    if status == 'paused':
        toggle_btn = {'text': u(chat_id, 'btn_resume'), 'callback_data': 'cfgresume_' + str(row_id)}
        status_line = u(chat_id, 'manage_status_paused')
    else:
        toggle_btn = {'text': u(chat_id, 'btn_pause'), 'callback_data': 'cfgpause_' + str(row_id)}
        status_line = u(chat_id, 'manage_status_active')

    manage_kb = {
        'inline_keyboard': [
            [{'text': u(chat_id, 'btn_extend'), 'callback_data': 'cfgext_' + str(row_id)}],
            [{'text': u(chat_id, 'btn_rename'), 'callback_data': 'cfgrename_' + str(row_id)}],
            [{'text': u(chat_id, 'btn_qr'), 'callback_data': 'cfgqr_' + str(row_id)}],
            [toggle_btn],
            [{'text': u(chat_id, 'btn_rotate'), 'callback_data': 'cfgrotate_' + str(row_id)}],
            [{'text': u(chat_id, 'btn_close'), 'callback_data': 'menu'}],
        ]
    }
    text = (
        u(chat_id, 'manage_title') + '\n' + DIVIDER + '\n' +
        u(chat_id, 'manage_name', label=cfg[4]) + '\n' +
        u(chat_id, 'manage_volume', gb=cfg[3]) + '\n' +
        u(chat_id, 'manage_duration', days=cfg[5]) + '\n' +
        status_line + '\n' +
        u(chat_id, 'manage_footer')
    )
    if note:
        text = note + '\n' + DIVIDER + '\n' + text
    send_message(chat_id, text, reply_markup=manage_kb)


def action_delete_config_start(chat_id):
    if not is_feature_enabled('delete_config'):
        send_message(chat_id, u(chat_id, 'disabled_feature'))
        return
    configs = get_user_configs(chat_id)
    if not configs:
        send_message(chat_id, u(chat_id, 'delete_empty') if get_user_lang(chat_id) == 'en'
                      else get_bot_text('delete_empty', DEFAULT_DELETE_EMPTY))
        return
    txt = (u(chat_id, 'delete_prompt') if get_user_lang(chat_id) == 'en'
           else get_bot_text('delete_prompt', DEFAULT_DELETE_PROMPT)) + '\n\n'
    for i, cfg in enumerate(configs, 1):
        txt += '<b>' + str(i) + '.</b> ' + str(cfg[4]) + ' (' + str(cfg[3]) + 'GB)\n'
    send_message(chat_id, txt, reply_markup=cancel_kb(chat_id))
    user_steps[str(chat_id)] = {'step': 'waiting_delete_id'}


def action_support_start(chat_id):
    if not is_feature_enabled('support'):
        send_message(chat_id, u(chat_id, 'disabled_feature'))
        return
    user_steps[str(chat_id)] = {'step': 'support_message'}
    send_message(chat_id, u(chat_id, 'support_prompt') if get_user_lang(chat_id) == 'en'
                 else get_bot_text('support_prompt', DEFAULT_SUPPORT_PROMPT), reply_markup=cancel_kb(chat_id))


def action_recent_orders(chat_id):
    if not is_feature_enabled('recentorders'):
        send_message(chat_id, u(chat_id, 'disabled_feature'))
        return
    _action_recent_orders(chat_id)


def _action_recent_orders(chat_id):
    """۳ سفارش آخر کاربر رو از جدول orders (تاریخچه‌ی ثابت تو Turso) نشون می‌ده.
    این جدول با حذف کانفیگ پاک نمی‌شه. هر سفارش یه دکمه‌ی «سفارش مجدد» داره که
    کاربر رو به همون صفحه‌ی فاکتور خرید معمولی می‌بره."""
    orders = get_recent_orders(chat_id, 3)
    if not orders:
        send_message(chat_id, u(chat_id, 'recentorders_empty'))
        return
    txt = u(chat_id, 'recentorders_header') + '\n' + DIVIDER + '\n\n'
    rows = []
    for i, o in enumerate(orders, 1):
        oid, label, gb, days, price, ctype, _created = o
        txt += u(
            chat_id, 'recentorders_item',
            idx=i, label=str(label), gb='%g' % (gb or 0), days=str(days),
            ctype_label=get_ctype_label(chat_id, ctype or 'both'), price=price or 0,
        ) + '\n\n'
        rows.append([{'text': u(chat_id, 'btn_reorder', idx=i), 'callback_data': 'reord_' + str(oid)}])
    send_message(chat_id, txt, reply_markup={'inline_keyboard': rows})


def action_language_menu(chat_id):
    kb = {
        'inline_keyboard': [[
            {'text': u(chat_id, 'lang_btn_fa'), 'callback_data': 'setlang_fa'},
            {'text': u(chat_id, 'lang_btn_en'), 'callback_data': 'setlang_en'},
        ]]
    }
    send_message(chat_id, u(chat_id, 'lang_prompt'), reply_markup=kb)


def action_referral(chat_id):
    if not referral_enabled():
        send_message(chat_id, u(chat_id, 'disabled_feature'))
        return
    link = build_referral_link(chat_id)
    if not link:
        send_message(chat_id, u(chat_id, 'referral_link_unavailable'))
        return
    a_inviter, a_invitee = get_referral_reward_inviter(), get_referral_reward_invitee()
    reward_line = u(chat_id, 'referral_reward_line_join' if referral_on_join() else 'referral_reward_line_purchase',
                    amount=f'{a_inviter:,}')
    if a_invitee > 0:
        reward_line += '\n' + u(chat_id, 'referral_invitee_bonus_line', bonus=f'{a_invitee:,}')
    invited, rewarded, earned = get_referral_stats(chat_id)
    send_message(chat_id, u(chat_id, 'referral_intro', divider=DIVIDER, reward_line=reward_line,
                            link=_html.escape(link), invited=f'{invited:,}', rewarded=f'{rewarded:,}',
                            earned=f'{earned:,}'))


def fmt_exchange_qty(qty):
    """مقدار قابل‌خرید: به پایین گرد می‌شه (کاربر بیشتر از واقعیت نشنوه)؛ تعداد اعشار بسته به بزرگی عدد."""
    if qty >= 1000:
        return f'{math.floor(qty):,}'
    d = 4 if qty >= 1 else 6
    f = 10 ** d
    t = ('%.*f' % (d, math.floor(qty * f) / f)).rstrip('0').rstrip('.')
    return t or '0'


def action_exchange_start(chat_id):
    if not is_feature_enabled('exchange'):
        send_message(chat_id, u(chat_id, 'disabled_feature'))
        return
    if not get_crypto_coins():
        send_message(chat_id, u(chat_id, 'disabled_feature'))
        return
    user_steps[str(chat_id)] = {'step': 'exchange_amount'}
    send_message(chat_id, u(chat_id, 'exchange_prompt', divider=DIVIDER), reply_markup=cancel_kb(chat_id))


def handle_exchange_amount(chat_id, text):
    """مبلغ تومانی → مقدار تقریبی هر رمزارز فعال (قیمت لحظه‌ای نوبیتکس)."""
    t = (text or '').strip().translate(_PERSIAN_DIGITS).replace(',', '').replace('٬', '').replace(' ', '')
    if not re.fullmatch(r'\d{1,13}', t) or int(t) <= 0:
        send_message(chat_id, u(chat_id, 'exchange_bad_amount'), reply_markup=cancel_kb(chat_id))
        return
    amount = int(t)
    coins = get_crypto_coins()
    if not coins:
        user_steps[str(chat_id)] = {}
        send_message(chat_id, u(chat_id, 'disabled_feature'))
        return
    lines, ok = [], 0
    for coin in coins:
        price = get_crypto_price_toman(coin['symbol'], raw=True)
        name = _html.escape(coin['label'])
        if price:
            ok += 1
            lines.append(u(chat_id, 'exchange_line', coin=name, qty=fmt_exchange_qty(amount / price),
                           price=f'{price:,.0f}'))
        else:
            lines.append(u(chat_id, 'exchange_line_err', coin=name))
    user_steps[str(chat_id)] = {}
    if not ok:
        send_message(chat_id, u(chat_id, 'exchange_no_price'))
        return
    send_message(chat_id, u(chat_id, 'exchange_result', amount=f'{amount:,}', divider=DIVIDER,
                            lines='\n\n'.join(lines)),
                 reply_markup={'inline_keyboard': [[
                     {'text': u(chat_id, 'btn_exchange_again'), 'callback_data': 'menu_exchange'}]]})


# هر آیتم: (کلید داخلی ثابت, متن پیش‌فرض دکمه, تابع اجراکننده)
BUTTON_ACTIONS = [
    ('buy', '🛍 خرید کانفیگ', action_buy_menu),
    ('trial', '🧪 تست رایگان', action_trial),
    ('topup', '💠 شارژ کیف پول', action_topup_menu),
    ('exchange', '💱 صرافی', action_exchange_start),
    ('account', '👤 حساب من', action_account),
    ('myconfigs', '🗂 کانفیگ‌های من', action_my_configs),
    ('delete', '🗑 حذف کانفیگ', action_delete_config_start),
    ('support', '🎧 پشتیبانی', action_support_start),
    ('guide', '📲 اپ مخصوص کانفیگ‌ها', action_guide),
    ('language', '🌐 تغییر زبان', action_language_menu),
    ('reseller', '🧑‍💼 فروشنده شو', action_reseller_menu),
    ('referral', '🎁 دعوت دوستان', action_referral),
]

# دستورهای اسلش معادل همون آیتم‌های منو (به کلید داخلی نگاشت می‌شن، نه متن دکمه؛
# این‌طوری حتی اگه متن دکمه از پنل عوض بشه، دستورها درست کار می‌کنن)
COMMAND_TO_ACTION_KEY = {
    '/buy': 'buy',
    '/test': 'trial',
    '/wallet': 'topup',
    '/myconfigs': 'myconfigs',
    '/delconfig': 'delete',
    '/reseller': 'reseller',
    '/account': 'account',
    '/support': 'support',
    '/guide': 'guide',
    '/app': 'guide',
    '/language': 'language',
    '/invite': 'referral',
}


def get_action_handlers():
    return {key: fn for key, _label, fn in BUTTON_ACTIONS}


def get_label_to_action_key():
    """متن دکمه -> کلید داخلی. هم لیبل فارسی (پیش‌فرض یا سفارشی‌شده از پنل
    ادمین) و هم لیبل ثابت انگلیسی رو نگاشت می‌کنه، چون بسته به زبانی که هر
    کاربر انتخاب کرده، کیبورد ثابتش (reply keyboard) ممکنه هرکدوم از این دو
    رو نشون بده."""
    mapping = {}
    for key, default_label, _fn in BUTTON_ACTIONS:
        mapping[get_button_label(key, default_label)] = key
        en_label = get_setting('ui_en_btn_' + key, None) or UI_TEXT['en'].get('btn_' + key)
        if en_label:
            mapping[en_label] = key
    return mapping


MAIN_MENU_DEFAULT_ORDER = [key for key, _label, _fn in BUTTON_ACTIONS]

# کلید دکمه‌ی منو -> کلید روشن/خاموش بودنش تو پنل (دکمه‌هایی که اینجا نیستن همیشه نمایش داده می‌شن)
MENU_BUTTON_FEATURE = {'buy': 'buy', 'trial': 'trial', 'topup': 'topup', 'exchange': 'exchange',
                       'delete': 'delete_config', 'support': 'support', 'reseller': 'reseller', 'guide': 'guide'}


def _chunk_pairs(items):
    return [items[i:i + 2] for i in range(0, len(items), 2)]


def main_menu(chat_id, note=None):
    wallet = get_wallet_db(chat_id)
    labels = {key: get_button_label_for(chat_id, key, default_label) for key, default_label, _fn in BUTTON_ACTIONS}
    order = get_ordered_keys('menu_order_main', MAIN_MENU_DEFAULT_ORDER)
    if not referral_enabled():
        order = [k for k in order if k != 'referral']   # دکمه‌ی دعوت دوستان تا وقتی از پنل روشن نشده نمایش داده نمی‌شه
    # دکمه‌ای که قابلیتش از پنل خاموش شده کلاً از منو حذف می‌شه؛ با روشن‌کردن دوباره برمی‌گرده
    order = [k for k in order if k not in MENU_BUTTON_FEATURE or is_feature_enabled(MENU_BUTTON_FEATURE[k])]
    style = get_keyboard_style()

    # تلگرام کیبورد ثابت (reply keyboard) رو یه لایه‌ی جدا از دکمه‌های شیشه‌ای
    # (inline) می‌دونه: فرستادن inline_keyboard به‌تنهایی، کیبورد ثابتِ قبلی رو
    # از پایین صفحه‌ی کاربر پاک نمی‌کنه. برای همین وقتی از پنل سبک کیبورد به
    # «اینلاین» تغییر می‌کنه، دفعه‌ی اول که هر کاربر با بات تعامل می‌کنه، اول
    # یه پیام کوتاه با remove_keyboard می‌فرستیم تا کیبورد قدیمی واقعاً جمع
    # بشه، بعد پیام اصلیِ منو با دکمه‌های شیشه‌ای می‌ره. این کار برای هر کاربر
    # فقط یک‌بار (تا وقتی سبک دوباره عوض نشه) انجام می‌شه.
    if get_user_kb_style(chat_id) != style:
        if style == 'inline':
            send_message(chat_id, u(chat_id, 'kb_removed_note'), reply_markup={'remove_keyboard': True})
        set_user_kb_style(chat_id, style)

    if style == 'inline':
        keyboard = {
            'inline_keyboard': [
                [{'text': labels[k], 'callback_data': 'menu_' + k} for k in row]
                for row in _chunk_pairs(order)
            ]
        }
    else:
        keyboard = {
            'keyboard': [[{'text': labels[k]} for k in row] for row in _chunk_pairs(order)],
            'resize_keyboard': True
        }

    # دکمه‌ی مخصوص ادمین (برای بقیه‌ی کاربرها هیچ‌وقت نمایش داده نمی‌شه)
    if chat_id == ADMIN_ID:
        if style == 'inline':
            keyboard['inline_keyboard'].append([{'text': admin_add_channel_label(), 'callback_data': 'admin_channels'}])
        else:
            keyboard['keyboard'].append([{'text': admin_add_channel_label()}])

    ct = get_config_types()
    if get_user_lang(chat_id) == 'en':
        text = u(
            chat_id, 'main_menu_text',
            welcome_intro=u(chat_id, 'welcome_intro'),
            wireguard_price=f"{ct['wireguard']['price_per_gb']:,}",
            config_price=f"{ct['config']['price_per_gb']:,}",
            both_price=f"{ct['both']['price_per_gb']:,}",
            openvpn_price=f"{ct['openvpn']['price_per_gb']:,}",
            dns_price=f"{ct['dns']['price_per_gb']:,}",
            wallet=f'{wallet:,}',
            divider=DIVIDER,
        )
    else:
        text = get_bot_text_fmt(
            'main_menu', DEFAULT_MAIN_MENU_TEXT,
            welcome_intro=get_bot_text('welcome_intro', DEFAULT_WELCOME_INTRO),
            wireguard_price=f"{ct['wireguard']['price_per_gb']:,}",
            config_price=f"{ct['config']['price_per_gb']:,}",
            both_price=f"{ct['both']['price_per_gb']:,}",
            openvpn_price=f"{ct['openvpn']['price_per_gb']:,}",
            dns_price=f"{ct['dns']['price_per_gb']:,}",
            wallet=f'{wallet:,}',
            divider=DIVIDER,
        )
    if note:
        text = note + '\n' + DIVIDER + '\n' + text
    send_message(chat_id, text, reply_markup=keyboard)


def notify_admin_new_ticket(tid, user_id, message):
    kb = {
        'inline_keyboard': [[
            {'text': u('fa', 'admin_btn_reply'), 'callback_data': 'reply_ticket_' + str(tid)},
            {'text': u('fa', 'admin_btn_close'), 'callback_data': 'close_ticket_' + str(tid)}
        ]]
    }
    txt = u('fa', 'admin_ticket_new', tid=str(tid), divider=DIVIDER, user_id=str(user_id), message=_html.escape(str(message), quote=False))
    send_message(ADMIN_ID, txt, reply_markup=kb)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def network_diagnostic():
    for name, url in [('api.splus.ir', 'https://api.splus.ir'), ('api.telegram.org', 'https://api.telegram.org')]:
        try:
            r = SESSION.get(url, timeout=8)
            print(f'🔎 تست اتصال به {name}: موفق (کد {r.status_code})')
        except Exception as e:
            print(f'🔎 تست اتصال به {name}: ناموفق ({e})')


# ---------------------------------------------------------------------------
# رجیستری متن‌ها: بات موقع استارت لیست «همه‌ی متن‌های پیش‌فرض + کلید ذخیره‌ی
# هرکدوم» رو تو جدول bot_registry می‌نویسه تا پنل وب بدون دوباره‌نویسی/کپی
# متن‌ها، همه‌شون رو نشون بده و ویرایش کنه (همیشه با خود بات هم‌نسخه می‌مونه).
# ---------------------------------------------------------------------------
import string as _string

_TEXT_GROUP_RULES = [
    (('menu_btn_', 'ctype_btn_'), '🔘 دکمه‌های منوی اصلی و نوع سرویس'),
    (('reseller_', 'btn_reseller', 'tier_line', 'price_range'), '🧑‍💼 فروشندگی (ریسلر)'),
    (('referral_', 'btn_referral'), '🎁 دعوت دوستان'),
    (('admin_', 'config_note', 'no_username', 'disabled_feature'), '🛠 پیام‌های ادمین و سیستمی'),
    (('qty_', 'btn_qty', 'ask_label', 'invoice_', 'btn_confirm_purchase', 'btn_cancel_purchase', 'btn_apply_discount',
      'discount_', 'building_config', 'insufficient_balance', 'purchase_success', 'output_label',
      'proto_unavailable', 'dns_unavailable', 'server_error', 'buy_menu', 'btn_buy', 'svc_',
      'btn_reorder', 'reorder_', 'recentorders', 'btn_recentorders', 'price_unit_suffix'), '🛍 خرید، فاکتور و سفارشات'),
    (('manage_', 'btn_manage', 'btn_extend', 'btn_rename', 'btn_qr', 'btn_pause', 'btn_resume', 'btn_rotate',
      'btn_close', 'btn_confirm_pay', 'ext_', 'rename_', 'qr_', 'pause_', 'resume_', 'rotate_', 'myconfigs', 'config_not_found',
      'btn_myconfigs'), '🗂 کانفیگ‌های من و مدیریت'),
    (('delete_', 'btn_delete'), '🗑 حذف کانفیگ'),
    (('trial_', 'btn_trial'), '🧪 تست رایگان'),
    (('topup_', 'btn_topup', 'number_only_error', 'crypto_'), '💠 شارژ کیف پول'),
    (('support_', 'btn_support'), '🎧 پشتیبانی'),
    (('account_', 'btn_account'), '👤 حساب من'),
    (('guide_', 'plat_', 'btn_guide'), '📲 اپ و دانلود'),
    (('lang_', 'btn_language'), '🌐 زبان'),
    (('welcome_', 'main_menu', 'kb_'), '🏠 منوی اصلی و خوش‌آمدگویی'),
    (('cur', 'unit_'), '🔢 واحدها'),
]
_GROUP_DISPLAY_ORDER = [
    '🔘 دکمه‌های منوی اصلی و نوع سرویس', '🏠 منوی اصلی و خوش‌آمدگویی', '🛍 خرید، فاکتور و سفارشات', '🗂 کانفیگ‌های من و مدیریت', '🗑 حذف کانفیگ',
    '🧪 تست رایگان', '💠 شارژ کیف پول', '🎧 پشتیبانی', '👤 حساب من', '📲 اپ و دانلود', '🌐 زبان',
    '🧑‍💼 فروشندگی (ریسلر)', '🎁 دعوت دوستان', '🛠 پیام‌های ادمین و سیستمی', '🔢 واحدها', '🔘 دکمه‌ها و سایر',
]


def _text_group(key):
    for prefixes, title in _TEXT_GROUP_RULES:
        if key.startswith(prefixes):
            return title
    return '🔘 دکمه‌ها و سایر'


def _tpl_fields(text):
    try:
        return sorted({f.split('.')[0].split('[')[0] for _, f, _, _ in _string.Formatter().parse(text) if f})
    except Exception:
        return []


def build_text_registry():
    fa_defaults = dict(UI_TEXT['fa'])
    for k, v in (
        ('welcome_intro', DEFAULT_WELCOME_INTRO), ('main_menu_text', DEFAULT_MAIN_MENU_TEXT),
        ('buy_menu_text', DEFAULT_BUY_MENU_TEXT), ('account_info', DEFAULT_ACCOUNT_TEXT),
        ('myconfigs_header', DEFAULT_MYCONFIGS_HEADER), ('myconfigs_empty', DEFAULT_MYCONFIGS_EMPTY),
        ('delete_prompt', DEFAULT_DELETE_PROMPT), ('delete_empty', DEFAULT_DELETE_EMPTY),
        ('trial_used', DEFAULT_TRIAL_USED), ('trial_building', DEFAULT_TRIAL_BUILDING),
        ('trial_ready', DEFAULT_TRIAL_READY), ('trial_error', DEFAULT_TRIAL_ERROR),
        ('topup_prompt', DEFAULT_TOPUP_PROMPT), ('topup_card_info', DEFAULT_TOPUP_CARD_INFO),
        ('topup_need_photo', DEFAULT_TOPUP_NEED_PHOTO), ('topup_receipt_ok', DEFAULT_TOPUP_RECEIPT_OK),
        ('support_prompt', DEFAULT_SUPPORT_PROMPT), ('support_ticket_created', DEFAULT_SUPPORT_TICKET_CREATED),
    ):
        fa_defaults[k] = v

    # دکمه‌های اصلی منو و نام نوع سرویس‌های فارسی تو صفحه‌ی «ظاهر ربات» (با ترتیب) مدیریت می‌شن
    skip_fa = {'btn_recentorders', 'btn_language', 'btn_reseller', 'btn_referral'}
    fa_items = []
    # دکمه‌های منوی اصلی و نوع سرویس‌ها (فارسی) تو settings زیر کلیدهای قدیمی btn_<key> و
    # ctype_label_<key> ذخیره می‌شن (همون چیزی که صفحه‌ی «دکمه‌ها و ظاهر» هم می‌نویسه)؛
    # این‌جا هم می‌آریمشون تا همه‌ی دکمه‌ها یه‌جا و کنار هم قابل ویرایش باشن.
    for key, default_label, _fn in BUTTON_ACTIONS:
        fa_items.append({'k': 'menu_btn_' + key, 's': 'btn_' + key, 'd': default_label, 'p': [],
                         'g': _text_group('menu_btn_' + key)})
    for key, default_label in CONFIG_TYPE_DEFAULT_LABELS.items():
        fa_items.append({'k': 'ctype_btn_' + key, 's': 'ctype_label_' + key, 'd': default_label, 'p': [],
                         'g': _text_group('ctype_btn_' + key)})
    for k, v in fa_defaults.items():
        if k in skip_fa or k.startswith('svc_'):
            continue
        fa_items.append({'k': k, 's': ui_setting_key('fa', k), 'd': v, 'p': _tpl_fields(v), 'g': _text_group(k)})

    en_items = []
    en_keys = list(UI_TEXT['en'].keys()) + [k for k in fa_defaults if k not in UI_TEXT['en']]
    for k in en_keys:
        if k.startswith('admin_') or k in ('config_note', 'no_username'):
            continue
        d = UI_TEXT['en'].get(k, '')
        ref = fa_defaults.get(k, '')
        en_items.append({'k': k, 's': ui_setting_key('en', k), 'd': d, 'ref': ref,
                         'p': _tpl_fields(d or ref), 'g': _text_group(k)})
    return {'version': 1, 'groups': _GROUP_DISPLAY_ORDER, 'fa': fa_items, 'en': en_items}


@with_db_retry
def _save_registry(payload_json):
    conn = get_conn()
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS bot_registry (name TEXT PRIMARY KEY, value TEXT)')
    c.execute("INSERT INTO bot_registry (name, value) VALUES ('texts', ?) "
              "ON CONFLICT(name) DO UPDATE SET value=excluded.value", (payload_json,))
    conn.commit()
    conn.close()


def sync_text_registry():
    try:
        reg = build_text_registry()
        _save_registry(json.dumps(reg, ensure_ascii=False))
        print(f"📝 رجیستری متن‌ها برای پنل ثبت شد ({len(reg['fa'])} متن فارسی، {len(reg['en'])} متن انگلیسی).")
    except Exception as e:
        print('⚠️ ثبت رجیستری متن‌ها برای پنل انجام نشد:', e)


def registry_watcher(interval=600):
    """هر چند دقیقه رجیستری متن‌ها رو دوباره تو دیتابیس می‌نویسه (اگه عوض شده باشه یا
    پاک شده باشه)، تا صفحه‌ی «متن‌های ربات» پنل همیشه کامل باشه و حتماً لازم نباشه بات
    ری‌استارت بشه. اگه ثبت اولیه موقع استارت ناموفق بوده هم همین‌جا جبران می‌شه."""
    last = None
    while True:
        time.sleep(interval)
        try:
            payload = json.dumps(build_text_registry(), ensure_ascii=False, sort_keys=True)
            if payload != last:
                _save_registry(payload)
                last = payload
        except Exception as e:
            print('⚠️ همگام‌سازی دوره‌ای رجیستری متن‌ها ناموفق بود:', e)


def commands_watcher():
    """هر ۶۰ ثانیه چک می‌کنه توضیح دستورات / از پنل عوض شده یا نه و اگه شده، دوباره ثبتش می‌کنه."""
    try:
        last = json.dumps(build_bot_commands(), ensure_ascii=False, sort_keys=True)
    except Exception:
        last = ''
    while True:
        time.sleep(60)
        try:
            cur = json.dumps(build_bot_commands(), ensure_ascii=False, sort_keys=True)
            if cur != last:
                set_bot_commands()
                last = cur
        except Exception as e:
            print('⚠️ خطا در همگام‌سازی دستورات:', e)



init_db()
sync_text_registry()
network_diagnostic()
delete_webhook()
set_bot_commands()
threading.Thread(target=commands_watcher, daemon=True).start()
threading.Thread(target=registry_watcher, daemon=True).start()
threading.Thread(target=crypto_deposit_watcher, daemon=True).start()
print('✅ ربات با موفقیت اجرا شد.')
last_update_id = 0

def process_update(update):
    """یک آپدیت تلگرام (پیام یا callback) رو پردازش می‌کنه. قبلاً این کد مستقیم
    داخل حلقه‌ی اصلی بود؛ یعنی وقتی برای یه کاربر یه کار کند (مثلاً ساخت
    کانفیگ روی پنل که چند ثانیه طول می‌کشه) در حال انجام بود، بات کلاً برای
    همه‌ی کاربرهای دیگه هم عملاً «هنگ» می‌کرد. حالا این تابع برای هر آپدیت
    تو یه ترد جدا (از UPDATE_EXECUTOR) اجرا می‌شه تا کارهای کند یک نفر،
    جواب سریع به بقیه رو معطل نکنه."""
    # ------------------------------------------------------------------
    # Callback queries (inline button presses)
    # ------------------------------------------------------------------
    if 'callback_query' in update:
        query = update['callback_query']
        chat_id = query['message']['chat']['id']
        data = query.get('data', '')
        answer_callback(query['id'])

        if data.startswith('menu_'):
            action_key = data.split('_', 1)[1]
            handler = get_action_handlers().get(action_key)
            if handler:
                handler(chat_id)

        elif data in ('setlang_fa', 'setlang_en'):
            new_lang = 'fa' if data == 'setlang_fa' else 'en'
            set_user_lang(chat_id, new_lang)
            send_message(chat_id, u(new_lang, 'lang_changed'))
            main_menu(chat_id)

        elif data == 'reseller_activate':
            if get_reseller(chat_id):
                action_reseller_menu(chat_id)
            else:
                activation_gb = get_reseller_min_gb()
                activation_price = round(activation_gb * get_reseller_price_per_gb())
                user_steps[str(chat_id)] = {'step': 'reseller_activate_confirm', 'gb': activation_gb,
                                            'price': activation_price}
                send_message(
                    chat_id,
                    u(chat_id, 'reseller_activate_confirm_title', divider=DIVIDER, gb=activation_gb,
                      price_per_gb=f'{get_reseller_price_per_gb():,}', price=f'{activation_price:,}'),
                    reply_markup={'inline_keyboard': [[
                        {'text': u(chat_id, 'btn_confirm_pay'), 'callback_data': 'reseller_activate_confirm'},
                        {'text': u(chat_id, 'btn_cancel'), 'callback_data': 'menu'},
                    ]]}
                )

        elif data == 'reseller_activate_confirm':
            s_ = user_steps.get(str(chat_id), {})
            if get_reseller(chat_id):
                user_steps[str(chat_id)] = {}
                action_reseller_menu(chat_id)
            elif s_.get('step') != 'reseller_activate_confirm':
                main_menu(chat_id)
            else:
                activation_gb, activation_price = s_['gb'], s_['price']
                wallet = get_wallet_db(chat_id)
                if wallet < activation_price:
                    shortfall = activation_price - wallet
                    send_message(
                        chat_id,
                        u(chat_id, 'insufficient_balance', divider=DIVIDER, wallet=wallet,
                          price=activation_price, shortfall=shortfall),
                        reply_markup={'inline_keyboard': [[
                            {'text': u(chat_id, 'btn_topup'), 'callback_data': 'menu_topup'}
                        ]]}
                    )
                else:
                    update_wallet_db(chat_id, -activation_price)
                    create_reseller(chat_id, None, None, activation_gb)
                    try:
                        conn = get_conn(); c = conn.cursor()
                        c.execute('INSERT INTO reseller_pool_log (user_id, gb, price, created_at) VALUES (?, ?, ?, ?)',
                                   (chat_id, activation_gb, activation_price, datetime.now().isoformat()))
                        conn.commit(); conn.close()
                    except Exception as log_err:
                        print('⚠️ ثبت لاگ فعال‌سازی فروشندگی انجام نشد:', log_err)
                    send_message(
                        chat_id,
                        u(chat_id, 'reseller_activated', divider=DIVIDER, gb=activation_gb,
                          panel_url=get_reseller_panel_url())
                    )
                    _reseller_creds_start(chat_id)

        elif data == 'reseller_topup':
            if not get_reseller(chat_id):
                action_reseller_menu(chat_id)
            else:
                user_steps[str(chat_id)] = {'step': 'reseller_topup_gb'}
                send_message(chat_id, u(chat_id, 'reseller_topup_prompt', divider=DIVIDER, tiers=reseller_tiers_text(chat_id),
                                        min_gb=get_reseller_topup_min_gb()), reply_markup=cancel_kb(chat_id))

        elif data == 'reseller_topup_confirm':
            s_ = user_steps.get(str(chat_id), {})
            if s_.get('step') == 'reseller_topup_confirm':
                gb, price = s_['gb'], s_['price']
                wallet = get_wallet_db(chat_id)
                if wallet < price:
                    shortfall = price - wallet
                    send_message(
                        chat_id,
                        u(chat_id, 'insufficient_balance', divider=DIVIDER, wallet=wallet, price=price, shortfall=shortfall),
                        reply_markup={'inline_keyboard': [[
                            {'text': u(chat_id, 'btn_topup'), 'callback_data': 'menu_topup'}
                        ]]}
                    )
                else:
                    update_wallet_db(chat_id, -price)
                    add_reseller_gb_db(chat_id, gb, price)
                    row = get_reseller(chat_id)
                    new_balance = row[3] if row else gb
                    send_message(chat_id, u(chat_id, 'reseller_topup_done', gb=('%g' % gb), gb_balance=('%g' % new_balance)))
                user_steps[str(chat_id)] = {}
            else:
                main_menu(chat_id)

        elif data == 'reseller_creds':
            if not get_reseller(chat_id):
                action_reseller_menu(chat_id)
            else:
                uname = get_reseller_username(chat_id)
                if not uname:                      # هنوز تنظیم نشده → مسیر کامل (نام کاربری + رمز)
                    _reseller_creds_start(chat_id)
                else:
                    send_message(chat_id, u(chat_id, 'reseller_creds_menu', divider=DIVIDER, username=uname),
                                 reply_markup={'inline_keyboard': [
                                     [{'text': u(chat_id, 'btn_change_username'), 'callback_data': 'reseller_cred_user'}],
                                     [{'text': u(chat_id, 'btn_change_password'), 'callback_data': 'reseller_cred_pass'}],
                                 ]})

        elif data == 'reseller_cred_user':
            if get_reseller(chat_id):
                user_steps[str(chat_id)] = {'step': 'reseller_chg_username'}
                send_message(chat_id, u(chat_id, 'reseller_ask_new_username'), reply_markup=cancel_kb(chat_id))

        elif data == 'reseller_cred_pass':
            if get_reseller(chat_id):
                user_steps[str(chat_id)] = {'step': 'reseller_chg_password'}
                send_message(chat_id, u(chat_id, 'reseller_ask_new_password', min_len=RESELLER_PASSWORD_MIN),
                             reply_markup=cancel_kb(chat_id))

        elif data.startswith('reord_'):
            try:
                order_id = int(data.split('_', 1)[1])
            except ValueError:
                order_id = 0
            order = get_order_row(chat_id, order_id)
            if not order:
                send_message(chat_id, u(chat_id, 'reorder_not_found'))
            else:
                types = get_config_types()
                ctype = order[5] if order[5] in types else 'both'
                gb, days = order[2], order[3]
                if gb is not None and float(gb).is_integer():
                    gb = int(gb)
                price = int(round(gb * types[ctype]['price_per_gb']))
                new_label = get_next_user_label()
                user_steps[str(chat_id)] = {
                    'step': 'confirm_buy',
                    'gb': gb,
                    'days': days,
                    'price': price,
                    'base_price': price,
                    'label': new_label,
                    'type': ctype,
                }
                send_message(
                    chat_id,
                    build_purchase_invoice(chat_id, user_steps[str(chat_id)]),
                    reply_markup=build_purchase_kb(chat_id)
                )

        elif data.startswith('reorder_'):
            row_id = int(data.split('_', 1)[1])
            cfg = get_config_row(chat_id, row_id)
            if not cfg:
                send_message(chat_id, u(chat_id, 'reorder_not_found'))
            else:
                ctype = cfg[9] if len(cfg) > 9 else 'both'
                cfg_type = get_config_types().get(ctype, get_config_types()['both'])
                gb, days = cfg[3], cfg[5]
                price = gb * cfg_type['price_per_gb']
                new_label = get_next_user_label()  # اسم قدیمی رو تکرار نمی‌کنیم چون پنل هر اسم رو فقط یک‌بار قبول می‌کنه
                user_steps[str(chat_id)] = {
                    'step': 'confirm_buy',
                    'gb': gb,
                    'days': days,
                    'price': price,
                    'base_price': price,
                    'label': new_label,
                    'type': ctype,
                }
                send_message(
                    chat_id,
                    build_purchase_invoice(chat_id, user_steps[str(chat_id)]),
                    reply_markup=build_purchase_kb(chat_id)
                )

        elif data == 'confirm_purchase':
            s = user_steps.get(str(chat_id), {})
            if s.get('step') == 'confirm_buy':
                gb, label, days, price = s['gb'], s['label'], s['days'], s['price']
                ctype = s.get('type', 'both')
                cfg_type = get_config_types().get(ctype, get_config_types()['both'])
                ctype_label = get_ctype_label(chat_id, ctype)
                wallet = get_wallet_db(chat_id)
                if wallet < price:
                    shortfall = price - wallet
                    send_message(
                        chat_id,
                        u(chat_id, 'insufficient_balance', divider=DIVIDER, wallet=wallet, price=price, shortfall=shortfall),
                        reply_markup={'inline_keyboard': [[{'text': u(chat_id, 'btn_topup'), 'callback_data': 'menu_topup'}]]}
                    )
                else:
                    send_message(chat_id, u(chat_id, 'building_config'))
                    res = make_config(gb, label, days, proto=cfg_type['proto'])
                    if res['success'] and res['sub_url']:
                        update_wallet_db(chat_id, -price)
                        save_user_config(chat_id, res['sub_url'], res['config_id'], gb, label, days, price, ctype)
                        try:
                            save_order(chat_id, label, gb, days, price, ctype, res['config_id'])
                        except Exception as order_err:
                            print('⚠️ ثبت سفارش در جدول orders انجام نشد:', order_err)
                        set_config_note(
                            res['config_id'],
                            build_config_note(chat_id, query.get('from', {}).get('username'), price)
                        )
                        if s.get('discount_code'):
                            increment_discount_usage(s['discount_code'])
                        if ctype == 'wireguard':
                            output_label = u(chat_id, 'output_label_wireguard')
                        elif ctype == 'openvpn':
                            output_label = u(chat_id, 'output_label_openvpn')
                        else:
                            output_label = u(chat_id, 'output_label_default')
                        success_text = u(
                            chat_id, 'purchase_success', divider=DIVIDER, ctype_label=ctype_label,
                            gb=gb, label=label, days=days, price=price,
                            output_label=output_label, sub_url=res['sub_url'],
                        )
                        send_message(chat_id, success_text)
                        if price and price > 0:
                            process_referral_reward(chat_id, 'purchase')   # بعد از پیام موفقیت، تا خریدار معطل نشه
                    elif res.get('error_code') and 'proto_unavailable' in str(res.get('error_code')).lower():
                        send_message(chat_id, u(chat_id, 'proto_unavailable', ctype_label=ctype_label))
                    elif res.get('error_code') and any(
                        c in str(res.get('error_code')).lower() for c in ('dns_unavailable', 'dns_off_for_seller')
                    ):
                        send_message(chat_id, u(chat_id, 'dns_unavailable', ctype_label=ctype_label))
                    else:
                        send_message(chat_id, u(chat_id, 'server_error'))
                user_steps[str(chat_id)] = {}
                # توجه: قبلاً اینجا main_menu(chat_id) هم صدا زده می‌شد که باعث
                # می‌شد بلافاصله بعد از پیام «کانفیگ ساخته شد»، کل پیام منوی
                # اصلی (با لیست قیمت‌ها و موجودی) دوباره تکراری نمایش داده بشه.
                # چون کیبورد (چه reply چه دکمه‌ی Menu تلگرام) خودش همیشه در
                # دسترسه، نیازی به این پیام‌ِ اضافه نیست.
            else:
                main_menu(chat_id)

        elif data == 'ask_discount_code':
            s = user_steps.get(str(chat_id), {})
            if s.get('step') == 'confirm_buy':
                user_steps[str(chat_id)]['step'] = 'buy_enter_discount'
                send_message(
                    chat_id,
                    u(chat_id, 'discount_ask_prompt'),
                    reply_markup={'inline_keyboard': [[{'text': u(chat_id, 'btn_cancel'), 'callback_data': 'buy_discount_cancel'}]]}
                )
            else:
                main_menu(chat_id)

        elif data == 'buy_discount_cancel':
            s = user_steps.get(str(chat_id), {})
            if s.get('step') == 'buy_enter_discount':
                user_steps[str(chat_id)]['step'] = 'confirm_buy'
                send_message(chat_id, build_purchase_invoice(chat_id, user_steps[str(chat_id)]), reply_markup=build_purchase_kb(chat_id))
            else:
                main_menu(chat_id)

        elif data == 'cancel_purchase' or data == 'menu':
            user_steps[str(chat_id)] = {}
            main_menu(chat_id)

        elif data == 'confdel_yes':
            s = user_steps.get(str(chat_id), {})
            if s.get('step') == 'confirm_delete':
                idx = s['index']
                refund = s['refund']
                if delete_config_from_db_by_index(chat_id, idx):
                    if refund > 0:
                        update_wallet_db(chat_id, refund)
                        send_message(chat_id, u(chat_id, 'delete_success', refund=refund))
                    else:
                        send_message(chat_id, u(chat_id, 'delete_success_no_refund'))
                else:
                    send_message(chat_id, u(chat_id, 'delete_panel_error'))
            user_steps[str(chat_id)] = {}
            # نتیجه (موفق یا ناموفق) همین بالا با یه پیام مشخص گفته شده؛
            # دیگه نیازی به نمایش دوباره‌ی کل منوی اصلی نیست.

        elif data == 'confdel_no':
            user_steps[str(chat_id)] = {}
            send_message(chat_id, u(chat_id, 'delete_cancelled'))
            main_menu(chat_id)

        # ---------------- مدیریت کانفیگ (تمدید/تغییر نام/توقف/ازسرگیری/تغییر لینک) ----------------

        elif data.startswith('managecfg_'):
            row_id = int(data.split('_', 1)[1])
            cfg = get_config_row(chat_id, row_id)
            if not cfg:
                send_message(chat_id, u(chat_id, 'config_not_found'))
            else:
                send_manage_panel(chat_id, cfg)

        elif data.startswith('cfgext_'):
            row_id = int(data.split('_', 1)[1])
            cfg = get_config_row(chat_id, row_id)
            if not cfg:
                send_message(chat_id, u(chat_id, 'config_not_found'))
            else:
                user_steps[str(chat_id)] = {'step': 'ext_ask_gb', 'row_id': row_id}
                send_message(chat_id, u(chat_id, 'ext_ask_gb'), reply_markup=cancel_kb(chat_id))

        elif data.startswith('cfgrename_'):
            row_id = int(data.split('_', 1)[1])
            cfg = get_config_row(chat_id, row_id)
            if not cfg:
                send_message(chat_id, u(chat_id, 'config_not_found'))
            else:
                user_steps[str(chat_id)] = {'step': 'rename_ask_label', 'row_id': row_id}
                send_message(chat_id, u(chat_id, 'rename_ask'), reply_markup=cancel_kb(chat_id))

        elif data.startswith('cfgqr_'):
            row_id = int(data.split('_', 1)[1])
            cfg = get_config_row(chat_id, row_id)
            if not cfg:
                send_message(chat_id, u(chat_id, 'config_not_found'))
            elif not QRCODE_AVAILABLE:
                send_message(chat_id, u(chat_id, 'qr_not_available'))
            else:
                try:
                    qr_buf = generate_qr_png_bytes(str(cfg[1]))
                    send_photo_bytes(
                        chat_id, qr_buf, filename='qr_' + str(row_id) + '.png',
                        caption=u(chat_id, 'qr_caption', label=cfg[4], divider=DIVIDER, sub_url=cfg[1])
                    )
                except Exception:
                    send_message(chat_id, u(chat_id, 'qr_error'))

        elif data.startswith('cfgpause_'):
            row_id = int(data.split('_', 1)[1])
            cfg = get_config_row(chat_id, row_id)
            if not cfg:
                send_message(chat_id, u(chat_id, 'config_not_found'))
            else:
                res = pause_config_on_panel(cfg[2])
                if res['success']:
                    update_config_status_db(row_id, 'paused')
                    cfg = get_config_row(chat_id, row_id)
                    send_manage_panel(chat_id, cfg, note=u(chat_id, 'pause_success', label=cfg[4]))
                else:
                    send_message(chat_id, u(chat_id, 'pause_error'))

        elif data.startswith('cfgresume_'):
            row_id = int(data.split('_', 1)[1])
            cfg = get_config_row(chat_id, row_id)
            if not cfg:
                send_message(chat_id, u(chat_id, 'config_not_found'))
            else:
                res = resume_config_on_panel(cfg[2])
                if res['success']:
                    update_config_status_db(row_id, 'active')
                    cfg = get_config_row(chat_id, row_id)
                    send_manage_panel(chat_id, cfg, note=u(chat_id, 'resume_success', label=cfg[4]))
                else:
                    send_message(chat_id, u(chat_id, 'resume_error'))

        elif data.startswith('cfgrotate_'):
            row_id = int(data.split('_', 1)[1])
            cfg = get_config_row(chat_id, row_id)
            if not cfg:
                send_message(chat_id, u(chat_id, 'config_not_found'))
            else:
                res = rotate_link_config_on_panel(cfg[2])
                if res['success']:
                    resp = res.get('data') or {}
                    new_url = None
                    if isinstance(resp, dict):
                        new_url = resp.get('sub_url') or resp.get('subUrl') or resp.get('url')
                    if new_url:
                        update_config_suburl_db(row_id, new_url)
                        send_message(chat_id, u(chat_id, 'rotate_success', label=cfg[4], sub_url=new_url))
                    else:
                        send_message(chat_id, u(chat_id, 'rotate_success_no_url'))
                else:
                    send_message(chat_id, u(chat_id, 'rotate_error'))

        elif data == 'extconfirm_yes':
            s = user_steps.get(str(chat_id), {})
            if s.get('step') == 'ext_confirm':
                row_id = s['row_id']
                extra_gb = s['extra_gb']
                extra_days = s['extra_days']
                price = s['price']
                cfg = get_config_row(chat_id, row_id)
                if not cfg:
                    send_message(chat_id, u(chat_id, 'config_not_found'))
                elif get_wallet_db(chat_id) < price:
                    send_message(chat_id, u(chat_id, 'ext_insufficient'))
                else:
                    res = extend_config_on_panel(cfg[2], extra_gb, extra_days)
                    if res['success']:
                        extend_config_db(row_id, extra_gb, extra_days)
                        update_wallet_db(chat_id, -price)
                        send_message(chat_id, u(chat_id, 'ext_success', label=cfg[4], extra_gb=extra_gb, extra_days=extra_days, price=price))
                    else:
                        send_message(chat_id, u(chat_id, 'ext_panel_error'))
            user_steps[str(chat_id)] = {}
            # مثل بالا: پیام نتیجه‌ی تمدید همین بالا ارسال شده، نیازی به
            # تکرار منوی اصلی نیست.

        elif data == 'extconfirm_no':
            user_steps[str(chat_id)] = {}
            send_message(chat_id, u(chat_id, 'ext_cancelled'))
            main_menu(chat_id)

        elif data.startswith('buytype_'):
            ctype = data.split('_', 1)[1]
            cfg_type = get_config_types().get(ctype)
            if not cfg_type:
                main_menu(chat_id)
            else:
                user_steps[str(chat_id)] = {'step': 'pick_quantity', 'type': ctype, 'gb': get_default_gb(), 'days': get_default_days()}
                text, kb = build_quantity_screen(chat_id, user_steps[str(chat_id)])
                send_message(chat_id, text, reply_markup=kb)

        elif data in ('qty_gb_inc', 'qty_gb_dec', 'qty_days_inc', 'qty_days_dec'):
            s = user_steps.get(str(chat_id), {})
            if s.get('step') != 'pick_quantity':
                main_menu(chat_id)
            else:
                if data == 'qty_gb_inc':
                    s['gb'] = min(s['gb'] + 1, 100000)
                elif data == 'qty_gb_dec':
                    s['gb'] = max(s['gb'] - 1, 1)
                elif data == 'qty_days_inc':
                    s['days'] = min(s['days'] + 1, 3650)
                elif data == 'qty_days_dec':
                    s['days'] = max(s['days'] - 1, 1)
                text, kb = build_quantity_screen(chat_id, s)
                edit_message(chat_id, query['message']['message_id'], text, reply_markup=kb)

        elif data == 'qty_noop':
            pass  # دکمه‌ی نمایش مقدار وسط، فقط برای نشون‌دادنه و کاری انجام نمی‌ده

        elif data == 'qty_confirm':
            s = user_steps.get(str(chat_id), {})
            if s.get('step') != 'pick_quantity':
                main_menu(chat_id)
            else:
                ctype = s.get('type', 'both')
                cfg_type = get_config_types().get(ctype, get_config_types()['both'])
                gb, days = s['gb'], s['days']
                price = gb * cfg_type['price_per_gb']
                user_steps[str(chat_id)] = {'step': 'ask_label', 'gb': gb, 'days': days, 'price': price, 'type': ctype}
                send_ask_label_prompt(chat_id)

        elif data == 'skip_label':
            s = user_steps.get(str(chat_id), {})
            if s.get('step') == 'ask_label':
                label = get_next_user_label()  # USER-1, USER-2, ... — هر اسم فقط یک‌بار تو پنل قابل استفاده‌ست
                gb, days, price = s['gb'], s['days'], s['price']
                ctype = s.get('type', 'both')
                user_steps[str(chat_id)] = {
                    'step': 'confirm_buy',
                    'gb': gb,
                    'days': days,
                    'price': price,
                    'base_price': price,
                    'label': label,
                    'type': ctype
                }
                send_message(chat_id, build_purchase_invoice(chat_id, user_steps[str(chat_id)]), reply_markup=build_purchase_kb(chat_id))
            else:
                main_menu(chat_id)



        elif data.startswith('reply_ticket_'):
            tid = int(data.split('_')[2])
            user_steps[str(chat_id)] = {'step': 'admin_reply', 'ticket_id': tid}
            send_message(
                chat_id,
                u('fa', 'admin_reply_prompt', tid=str(tid)),
                reply_markup=cancel_kb(chat_id)
            )

        elif data.startswith('close_ticket_'):
            tid = int(data.split('_')[2])
            update_ticket_status(tid, 'closed')
            send_message(chat_id, u('fa', 'admin_ticket_closed', tid=str(tid)))

        elif data in ('tpm_card', 'tpm_crypto'):
            s_ = user_steps.get(str(chat_id), {})
            if s_.get('step') != 'choose_topup_method':
                main_menu(chat_id)
            elif data == 'tpm_card':
                if card_topup_enabled():
                    ask_topup_amount_for(chat_id, 'card')
                else:
                    send_message(chat_id, u(chat_id, 'disabled_feature'))
            else:
                if crypto_enabled():
                    start_crypto_topup(chat_id)
                else:
                    send_message(chat_id, u(chat_id, 'disabled_feature'))

        elif data.startswith('tpc_'):
            s_ = user_steps.get(str(chat_id), {})
            coins = get_crypto_coins() if crypto_enabled() else []
            coin = next((c for c in coins if 'tpc_' + c['id'] == data), None)
            if s_.get('step') != 'choose_topup_coin' or not coin:
                main_menu(chat_id)
            else:
                send_crypto_deposit_info(chat_id, coin)

        elif data == 'sendhash':
            req_id = get_latest_pending_crypto_request(chat_id)
            if not req_id:
                send_message(chat_id, u(chat_id, 'topup_hash_no_pending'))
            else:
                user_steps[str(chat_id)] = {'step': 'crypto_send_hash', 'req_id': req_id}
                send_message(chat_id, u(chat_id, 'topup_hash_prompt'), reply_markup=cancel_kb(chat_id))

        elif data == 'admin_channels' and chat_id == ADMIN_ID:
            user_steps[str(chat_id)] = {}
            admin_channels_panel(chat_id)

        elif data == 'admin_ch_add' and chat_id == ADMIN_ID:
            admin_add_channel_ask(chat_id)

        elif data.startswith('admin_ch_del_') and chat_id == ADMIN_ID:
            admin_remove_channel(chat_id, data[len('admin_ch_del_'):])

        elif data.startswith('topup_acc_') and chat_id == ADMIN_ID:
            req_id = int(data.split('_')[2])
            if not approve_topup_request(req_id):
                send_message(ADMIN_ID, u('fa', 'admin_already_reviewed'))

        elif data.startswith('topup_rej_') and chat_id == ADMIN_ID:     # رد کردن فقط با خود ادمینه، بات هیچ‌وقت خودش رد نمی‌کنه
            req_id = int(data.split('_')[2])
            req = get_topup_request(req_id)
            if req and req[3] == 'pending':
                update_topup_status(req_id, 'rejected')
                send_message(req[1], u(req[1], 'topup_rejected'))
                send_message(ADMIN_ID, u('fa', 'admin_topup_rejected', req_id=str(req_id)))
            else:
                send_message(ADMIN_ID, u('fa', 'admin_already_reviewed'))

    # ------------------------------------------------------------------
    # Regular messages
    # ------------------------------------------------------------------
    elif 'message' in update:
        message = update['message']
        chat_id = message['chat']['id']
        text = message.get('text', '')
        step = user_steps.get(str(chat_id), {})

        sender = message.get('from', {}) or {}
        upsert_user_info(chat_id, sender.get('username'), sender.get('first_name'))

        matched_action_key = COMMAND_TO_ACTION_KEY.get(text) or get_label_to_action_key().get(text)

        if text == '/nobitexcheck' and chat_id == ADMIN_ID:
            send_message(chat_id, nobitex_check_report())

        elif chat_id == ADMIN_ID and text in (admin_add_channel_label(), '/channels'):
            user_steps[str(chat_id)] = {}
            admin_channels_panel(chat_id)

        elif text == '/start' or text.startswith('/start '):
            add_user(chat_id)
            user_steps[str(chat_id)] = {}
            main_menu(chat_id)
            process_referral_reward(chat_id, 'join')

        elif matched_action_key:
            get_action_handlers()[matched_action_key](chat_id)

        # ---------------- step-based flows ----------------

        elif step.get('step') == 'admin_add_channel' and chat_id == ADMIN_ID:
            admin_add_channel_submit(chat_id, text)

        elif step.get('step') == 'ask_label':
            label = clean_label(text) or get_next_user_label()
            gb = step['gb']
            days = step['days']
            price = step['price']
            ctype = step.get('type', 'both')
            user_steps[str(chat_id)] = {
                'step': 'confirm_buy',
                'gb': gb,
                'days': days,
                'price': price,
                'base_price': price,
                'label': label,
                'type': ctype
            }
            send_message(
                chat_id,
                build_purchase_invoice(chat_id, user_steps[str(chat_id)]),
                reply_markup=build_purchase_kb(chat_id)
            )

        elif step.get('step') == 'buy_enter_discount':
            ok, result = validate_discount_code(text)
            if not ok:
                send_message(chat_id, u(chat_id, result))
            else:
                percent = result
                base_price = step.get('base_price', step['price'])
                final_price = round(base_price * (100 - percent) / 100)
                user_steps[str(chat_id)]['step'] = 'confirm_buy'
                user_steps[str(chat_id)]['price'] = final_price
                user_steps[str(chat_id)]['discount_code'] = text.strip().upper()
                user_steps[str(chat_id)]['discount_percent'] = percent
                send_message(
                    chat_id,
                    build_purchase_invoice(chat_id, user_steps[str(chat_id)]),
                    reply_markup=build_purchase_kb(chat_id)
                )

        elif step.get('step') == 'reseller_set_username':
            uname = (text or '').strip().lower()
            if not RESELLER_USERNAME_RE.match(uname):
                send_message(chat_id, u(chat_id, 'reseller_username_bad'))
            elif reseller_username_taken(uname, chat_id):
                send_message(chat_id, u(chat_id, 'reseller_username_taken'))
            else:
                user_steps[str(chat_id)] = {'step': 'reseller_set_password', 'username': uname}
                send_message(chat_id, u(chat_id, 'reseller_ask_password', min_len=RESELLER_PASSWORD_MIN),
                             reply_markup=cancel_kb(chat_id))

        elif step.get('step') == 'reseller_set_password':
            pw = text or ''
            try:
                delete_message(chat_id, message.get('message_id'))   # رمز تو چت نمونه
            except Exception:
                pass
            if (len(pw) < RESELLER_PASSWORD_MIN or len(pw) > RESELLER_PASSWORD_MAX or pw != pw.strip()):
                send_message(chat_id, u(chat_id, 'reseller_password_bad', min_len=RESELLER_PASSWORD_MIN,
                                         max_len=RESELLER_PASSWORD_MAX))
            else:
                uname = step.get('username')
                try:
                    set_reseller_credentials_db(chat_id, uname, hash_reseller_password(pw), pw)
                except Exception as e:
                    print('⚠️ ذخیره‌ی نام کاربری/رمز فروشنده ناموفق بود:', e)
                    user_steps[str(chat_id)] = {'step': 'reseller_set_username'}
                    send_message(chat_id, u(chat_id, 'reseller_username_taken'))
                else:
                    user_steps[str(chat_id)] = {}
                    send_message(chat_id, u(chat_id, 'reseller_creds_done', divider=DIVIDER, username=uname,
                                             panel_url=get_reseller_panel_url()))

        elif step.get('step') == 'reseller_chg_username':
            uname = (text or '').strip().lower()
            if not RESELLER_USERNAME_RE.match(uname):
                send_message(chat_id, u(chat_id, 'reseller_username_bad'))
            elif reseller_username_taken(uname, chat_id):
                send_message(chat_id, u(chat_id, 'reseller_username_taken'))
            else:
                try:
                    set_reseller_username_db(chat_id, uname)
                except Exception as e:
                    print('⚠️ تغییر نام کاربری فروشنده ناموفق بود:', e)
                    send_message(chat_id, u(chat_id, 'reseller_username_taken'))
                else:
                    user_steps[str(chat_id)] = {}
                    send_message(chat_id, u(chat_id, 'reseller_username_changed', username=uname))

        elif step.get('step') == 'reseller_chg_password':
            pw = text or ''
            try:
                delete_message(chat_id, message.get('message_id'))
            except Exception:
                pass
            if (len(pw) < RESELLER_PASSWORD_MIN or len(pw) > RESELLER_PASSWORD_MAX or pw != pw.strip()):
                send_message(chat_id, u(chat_id, 'reseller_password_bad', min_len=RESELLER_PASSWORD_MIN,
                                         max_len=RESELLER_PASSWORD_MAX))
            else:
                try:
                    set_reseller_password_db(chat_id, hash_reseller_password(pw), pw)
                except Exception as e:
                    print('⚠️ تغییر رمز فروشنده ناموفق بود:', e)
                    send_message(chat_id, u(chat_id, 'reseller_password_bad', min_len=RESELLER_PASSWORD_MIN,
                                             max_len=RESELLER_PASSWORD_MAX))
                else:
                    user_steps[str(chat_id)] = {}
                    send_message(chat_id, u(chat_id, 'reseller_password_changed'))

        elif step.get('step') == 'reseller_topup_gb':
            try:
                gb = float(text)
                if gb <= 0 or not math.isfinite(gb) or gb > 100000:
                    send_message(chat_id, u(chat_id, 'ext_number_error'))
                elif gb < get_reseller_topup_min_gb():
                    send_message(chat_id, u(chat_id, 'reseller_topup_min', min_gb=get_reseller_topup_min_gb()))
                else:
                    rate = reseller_topup_rate(gb)
                    price = round(gb * rate)
                    user_steps[str(chat_id)] = {'step': 'reseller_topup_confirm', 'gb': gb, 'price': price}
                    send_message(
                        chat_id,
                        u(chat_id, 'reseller_topup_confirm_title', gb=('%g' % gb), price=price, rate=rate),
                        reply_markup={'inline_keyboard': [[
                            {'text': u(chat_id, 'btn_confirm_pay'), 'callback_data': 'reseller_topup_confirm'},
                            {'text': u(chat_id, 'btn_cancel'), 'callback_data': 'menu'},
                        ]]}
                    )
            except ValueError:
                send_message(chat_id, u(chat_id, 'number_only_error'))

        elif step.get('step') == 'ext_ask_gb':
            try:
                extra_gb = float(text)
                if extra_gb <= 0 or not math.isfinite(extra_gb) or extra_gb > 100000:
                    send_message(chat_id, u(chat_id, 'ext_number_error'))
                else:
                    user_steps[str(chat_id)]['step'] = 'ext_ask_days'
                    user_steps[str(chat_id)]['extra_gb'] = extra_gb
                    send_message(chat_id, u(chat_id, 'ext_ask_days'), reply_markup=cancel_kb(chat_id))
            except ValueError:
                send_message(chat_id, u(chat_id, 'number_only_error'))

        elif step.get('step') == 'ext_ask_days':
            try:
                extra_days = int(text)
                if extra_days <= 0 or extra_days > 3650:
                    send_message(chat_id, u(chat_id, 'ext_number_error'))
                else:
                    row_id = step['row_id']
                    extra_gb = step['extra_gb']
                    cfg = get_config_row(chat_id, row_id)
                    if not cfg:
                        send_message(chat_id, u(chat_id, 'config_not_found'))
                        user_steps[str(chat_id)] = {}
                    else:
                        ctype = cfg[9] if len(cfg) > 9 else 'both'
                        price_per_gb = get_config_types().get(ctype, get_config_types()['both'])['price_per_gb']
                        price = round(extra_gb * price_per_gb)
                        user_steps[str(chat_id)] = {
                            'step': 'ext_confirm',
                            'row_id': row_id,
                            'extra_gb': extra_gb,
                            'extra_days': extra_days,
                            'price': price
                        }
                        confirm_text = u(
                            chat_id, 'ext_confirm_title', divider=DIVIDER,
                            label=cfg[4], extra_gb=extra_gb, extra_days=extra_days, price=price,
                        )
                        confirm_kb = {
                            'inline_keyboard': [[
                                {'text': u(chat_id, 'btn_confirm_pay'), 'callback_data': 'extconfirm_yes'},
                                {'text': u(chat_id, 'btn_cancel'), 'callback_data': 'extconfirm_no'}
                            ]]
                        }
                        send_message(chat_id, confirm_text, reply_markup=confirm_kb)
            except ValueError:
                send_message(chat_id, u(chat_id, 'number_only_error'))

        elif step.get('step') == 'rename_ask_label':
            new_label = clean_label(text)
            row_id = step.get('row_id')
            if not new_label:
                send_message(chat_id, u(chat_id, 'rename_empty_error'))
            else:
                cfg = get_config_row(chat_id, row_id)
                if not cfg:
                    send_message(chat_id, u(chat_id, 'config_not_found'))
                else:
                    res = rename_config_on_panel(cfg[2], new_label)
                    if res['success']:
                        update_config_label_db(row_id, new_label)
                        # فقط تغییر لیبل کافی نیست: خودِ فایل/ساب‌لینک قبلاً
                        # با نام قدیمی روی پنل ساخته و کش شده، برای همین بعد
                        # از تغییر نام، لینک رو هم رفرش (rotate) می‌کنیم تا
                        # نام جدید واقعاً داخل ساب‌لینک/فایل دیده بشه.
                        rotate_res = rotate_link_config_on_panel(cfg[2])
                        new_url = None
                        if rotate_res.get('success'):
                            resp = rotate_res.get('data') or {}
                            if isinstance(resp, dict):
                                new_url = resp.get('sub_url') or resp.get('subUrl') or resp.get('url')
                            if new_url:
                                update_config_suburl_db(row_id, new_url)
                        if new_url:
                            send_message(chat_id, u(chat_id, 'rename_success_new_url', label=new_label, sub_url=new_url))
                        else:
                            send_message(chat_id, u(chat_id, 'rename_success_no_url', label=new_label))
                    else:
                        send_message(chat_id, u(chat_id, 'rename_panel_error'))
                user_steps[str(chat_id)] = {}
                # پیام نتیجه (لینک جدید یا خطا) همین بالا فرستاده شده.

        elif step.get('step') == 'waiting_delete_id':
            try:
                idx = int(text) - 1
                configs = get_user_configs(chat_id)
                if not (0 <= idx < len(configs)):
                    send_message(chat_id, u(chat_id, 'delete_invalid_index'))
                    user_steps[str(chat_id)] = {}
                else:
                    cfg = configs[idx]
                    gb, price, config_id, label = cfg[3], cfg[6], cfg[2], cfg[4]
                    price_per_gb = (price / gb) if gb else 0

                    used_gb = get_config_usage_gb(config_id)
                    if used_gb is None:
                        used_gb = 0
                        refund = 0
                        usage_note = u(chat_id, 'delete_usage_unknown')
                    else:
                        used_gb = min(used_gb, gb)
                        used_value = used_gb * price_per_gb
                        remaining_value = price - used_value
                        refund = int(remaining_value * get_refund_ratio())
                        usage_note = ''

                    confirm_text = u(
                        chat_id, 'delete_confirm_title', divider=DIVIDER, label=label, gb=gb,
                        used_gb=f'{used_gb:.2f}', price=price, refund=refund, usage_note=usage_note,
                    )
                    confirm_kb = {
                        'inline_keyboard': [[
                            {'text': u(chat_id, 'btn_delete_yes'), 'callback_data': 'confdel_yes'},
                            {'text': u(chat_id, 'btn_cancel'), 'callback_data': 'confdel_no'}
                        ]]
                    }
                    user_steps[str(chat_id)] = {'step': 'confirm_delete', 'index': idx, 'refund': refund}
                    send_message(chat_id, confirm_text, reply_markup=confirm_kb)
            except ValueError:
                send_message(chat_id, u(chat_id, 'delete_row_number_error'))
                user_steps[str(chat_id)] = {}

        elif step.get('step') == 'ask_topup_amount':
            try:
                amount = int(text)
                method = step.get('method', 'card')
                if amount < get_min_topup_for(method):
                    send_message(chat_id, u(chat_id, 'topup_min_error', min_topup=get_min_topup_for(method)))
                else:
                    proceed_after_topup_amount(chat_id, amount, method)
            except ValueError:
                send_message(chat_id, u(chat_id, 'topup_amount_error'))

        elif step.get('step') == 'waiting_receipt' and (
                (step.get('method') != 'crypto' and 'photo' in message)
                or (step.get('method') == 'crypto' and _looks_like_tx_hash(text))):
            # رمزارز: فقط هش تراکنش (متن) قبول می‌شه و عکس لازم نیست؛ کارت‌به‌کارت: فقط عکس رسید
            # رسید کارت‌به‌کارت فقط عکسه؛ رمزارز هم عکس رسید و هم هش تراکنش (متن) رو قبول می‌کنه
            photo_id = message['photo'][-1]['file_id'] if 'photo' in message else None
            tx_hash = None if photo_id else text.strip()
            amount = step.get('amount')
            is_crypto = step.get('method') == 'crypto'
            if is_crypto:
                req_id = create_topup_request(chat_id, amount, 'crypto',
                                              f"{fmt_coin_amount(step.get('coin_amount'))} {step.get('coin_label')}",
                                              step.get('price'), coin_symbol=step.get('coin_symbol'),
                                              coin_qty=step.get('coin_amount'), tx_hash=tx_hash,
                                              req_ts=step.get('requested_at'))
            else:
                req_id = create_topup_request(chat_id, amount)

            paid_at = time.time()
            receipt_ok_text = (u(chat_id, 'topup_receipt_ok') if get_user_lang(chat_id) == 'en'
                               else get_bot_text('topup_receipt_ok', DEFAULT_TOPUP_RECEIPT_OK))
            if is_crypto:
                # اگه خودکار تأیید نشد، کاربر هر لحظه می‌تونه با این دکمه (یا فرستادن مستقیم هش) هش رو بفرسته
                send_message(chat_id, receipt_ok_text + u(chat_id, 'topup_receipt_ok_crypto_hint'),
                             reply_markup={'inline_keyboard': [[
                                 {'text': u(chat_id, 'btn_send_hash'), 'callback_data': 'sendhash'}]]})
            else:
                send_message(chat_id, receipt_ok_text)
            user_steps[str(chat_id)] = {}
            # پیام «رسید دریافت شد» همین بالا رفت؛ دیگه نیازی به تکرار منو نیست.

            if is_crypto:
                admin_caption = u('fa', 'admin_topup_request_crypto', divider=DIVIDER, user_id=str(chat_id),
                                  amount=f'{amount:,}', req_id=str(req_id),
                                  coin_amount=fmt_coin_amount(step.get('coin_amount')),
                                  coin=_html.escape(str(step.get('coin_label'))),
                                  price=f"{step.get('price'):,.0f}")
                if tx_hash:
                    admin_caption += '\n' + u('fa', 'admin_topup_hash_line', tx_hash=_html.escape(tx_hash))
            else:
                admin_caption = u('fa', 'admin_topup_request', divider=DIVIDER, user_id=str(chat_id),
                                  amount=f'{amount:,}', req_id=str(req_id))
            admin_caption += build_topup_timing_text(step.get('requested_at'), paid_at)
            admin_kb = {
                'inline_keyboard': [[
                    {'text': u('fa', 'admin_btn_accept'), 'callback_data': 'topup_acc_' + str(req_id)},
                    {'text': u('fa', 'admin_btn_reject'), 'callback_data': 'topup_rej_' + str(req_id)}
                ]]
            }
            if photo_id:
                send_photo(ADMIN_ID, photo_id, caption=admin_caption, reply_markup=admin_kb)
            else:
                send_message(ADMIN_ID, admin_caption, reply_markup=admin_kb)
            if is_crypto:
                check_crypto_request_async(req_id)    # تطبیق با واریزهای نوبیتکس (نتیجه جدا برای ادمین می‌آد)

        elif step.get('step') == 'exchange_amount':
            handle_exchange_amount(chat_id, text)

        elif step.get('step') == 'crypto_declare_amount':
            handle_crypto_declared_amount(chat_id, step, text)

        elif step.get('step') == 'crypto_send_hash':
            if not _looks_like_tx_hash(text):
                send_message(chat_id, u(chat_id, 'topup_crypto_need_proof'), reply_markup=cancel_kb(chat_id))
            else:
                req_id = get_latest_pending_crypto_request(chat_id) or step.get('req_id')
                user_steps[str(chat_id)] = {}
                if req_id and get_topup_request(req_id) and get_topup_request(req_id)[3] == 'pending':
                    attach_hash_to_pending_request(chat_id, req_id, text.strip())
                else:
                    send_message(chat_id, u(chat_id, 'topup_hash_no_pending'))

        elif step.get('step') == 'waiting_receipt' and step.get('method') == 'crypto':
            send_message(chat_id, u(chat_id, 'topup_crypto_need_proof'))

        elif step.get('step') == 'waiting_receipt' and 'photo' not in message:
            send_message(chat_id, u(chat_id, 'topup_need_photo') if get_user_lang(chat_id) == 'en'
                          else get_bot_text('topup_need_photo', DEFAULT_TOPUP_NEED_PHOTO))

        elif step.get('step') == 'support_message':
            tid = create_ticket(chat_id, text)
            ticket_text = (u(chat_id, 'support_ticket_created', tid=str(tid)) if get_user_lang(chat_id) == 'en'
                            else get_bot_text_fmt('support_ticket_created', DEFAULT_SUPPORT_TICKET_CREATED, tid=str(tid)))
            send_message(chat_id, ticket_text)
            notify_admin_new_ticket(tid, chat_id, text)
            user_steps[str(chat_id)] = {}

        elif step.get('step') == 'admin_reply' and chat_id == ADMIN_ID:
            tid = step.get('ticket_id')
            ticket = get_ticket(tid)
            if ticket:
                update_ticket_status(tid, 'answered', text)
                send_message(ticket[1], u(ticket[1], 'support_reply_received', tid=str(tid), reply_text=text))
                send_message(chat_id, u('fa', 'admin_ticket_replied'))
            else:
                send_message(chat_id, u('fa', 'admin_ticket_not_found'))
            user_steps[str(chat_id)] = {}

        elif not step.get('step') and text and _looks_like_tx_hash(text) and chat_id != ADMIN_ID:
            # کاربر بدون زدن هیچ دکمه‌ای مستقیم هش فرستاده: اگه درخواست رمزارزیِ معلق داره بهش وصل می‌شه
            pending_id = get_latest_pending_crypto_request(chat_id)
            if pending_id:
                attach_hash_to_pending_request(chat_id, pending_id, text.strip())


# ---------------------------------------------------------------------------
# عضویت اجباری در کانال — اکانت شخصی (userbot) داخل خودِ همین بات لاگین می‌شه
# ---------------------------------------------------------------------------
# روش کار: وقتی ADMIN_ID بات رو /start کنه و اکانت وصل نباشه، بات ازش شماره‌ی
# موبایل و بعد کد تأیید می‌گیره و اون اکانت (که باید مالک/ادمین کانال باشه) تو
# پس‌زمینه لاگین می‌مونه. قبل از جواب‌دادن به هر کاربر، عضویتش تو کانال با همین
# اکانت چک می‌شه. اگه عضو نبود، پیام «اول عضو کانال شو» + دکمه‌ی «✅ عضو شدم» می‌بینه.
#
# env ها (همه اختیاری):
#   GATE_ENABLED   : 0 = کل قابلیت خاموش (پیش‌فرض 1)
#   CHANNEL_LINK   : لینک/یوزرنیم کانال (پیش‌فرض https://splus.ir/skytunnel)
#   GATE_FAIL_OPEN : اگه اکانت هنوز وصل نیست/چک جواب نداد: 1 = کاربر رد شه، 0 = بسته بشه
# دستورهای ادمین: /start (لاگین)، /gatestatus، /gatedisconnect، /cancel
#
# نکته: سشن لاگین فقط روی دیسک سرور نگه داشته می‌شه و تو دیتابیس ذخیره نمی‌شه. با ریدیپلوی
# (که دیسک پاک می‌شه) سشن از بین می‌ره و بات به‌محض بالا اومدن از ادمین می‌خواد دوباره
# با /start لاگین کنه.
GATE_ENABLED = os.getenv("GATE_ENABLED", "1").strip() != "0"
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://splus.ir/skytunnel").strip()
GATE_FAIL_OPEN = os.getenv("GATE_FAIL_OPEN", "1").strip() != "0"
GATE_SESSION_NAME = "gate_session"
GATE_CONFIG_PATH = "gate_config.json"
GATE_CODE_TIMEOUT = 300       # چند ثانیه منتظر کد/رمز از ادمین بمونه
GATE_LIVE_TIMEOUT = 6         # حداکثر صبر برای چک زنده‌ی یک کاربر
GATE_SYNC_INTERVAL = max(5, int(os.getenv("GATE_SYNC_INTERVAL", "10") or 10))  # هر چند ثانیه لیست اعضا تازه بشه
GATE_CACHE_TTL = 60           # عضوِ تاییدشده تا این مدت دوباره چک نمی‌شه

try:
    import spluspy
    G_AVAILABLE = True
except Exception as _gate_imp_err:  # کتابخونه نصب نیست -> گیت خاموش، بات عادی کار می‌کنه
    spluspy = None
    G_AVAILABLE = False
    print('⚠️ کتابخونه‌ی spluspy نصب نیست؛ عضویت اجباری غیرفعال شد:', _gate_imp_err)

try:
    from spluspy.tl import functions as tl_functions, types as tl_types
except Exception:
    tl_functions, tl_types = None, None

try:
    from spluspy import events as sp_events
except Exception:
    sp_events = None

_G = {'running': False, 'starting': False, 'waiting': None, 'phone': None, 'account': None,
      'client': None, 'loop': None, 'gen': 0,
      # حالت چندکاناله: همه‌چیز بر اساس «لینک کانال» نگه داشته می‌شه
      'chs': {}, 'modes': {}, 'refreshed': {}, 'members': {}}
_G_ANSWERS = queue.Queue()
_G_TSTATE = {}
_member_cache = {}          # کلید: (user_id, لینک کانال)
_member_cache_guard = threading.Lock()


def _gm(link):
    """مجموعه‌ی آیدی اعضای کش‌شده‌ی یک کانال."""
    return _G['members'].setdefault(link, set())


# ---------------- لیست کانال‌های عضویت اجباری (از داخل خود بات مدیریت می‌شه) ----------------
# تو جدول settings با کلید gate_channels (JSON) ذخیره می‌شه. اگه هنوز هیچ‌وقت ست نشده باشه،
# همون CHANNEL_LINK پیش‌فرض تنها کانال لیسته. اگه ادمین همه رو حذف کنه، لیست خالیه و عضویت اجباری اعمال نمی‌شه.
_GATE_CH = {'list': None}
_gate_ch_lock = threading.Lock()


@with_db_retry
def _gate_ch_load_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key='gate_channels'")
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


@with_db_retry
def _gate_ch_save_db(links):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO settings (key, value) VALUES ('gate_channels', ?) "
              "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
              (json.dumps(links, ensure_ascii=False),))
    conn.commit()
    conn.close()


def get_gate_channels():
    with _gate_ch_lock:
        if _GATE_CH['list'] is None:
            links = None
            try:
                raw = _gate_ch_load_db()
                if raw is not None:
                    data = json.loads(raw)
                    if isinstance(data, list):
                        links = [str(x).strip() for x in data if str(x).strip()]
            except Exception as e:
                print('⚠️ خوندن لیست کانال‌های عضویت اجباری ناموفق بود:', e)
                return [CHANNEL_LINK] if CHANNEL_LINK else []     # کش نمی‌شه؛ دفعه‌ی بعد دوباره تلاش می‌کنه
            if links is None:
                links = [CHANNEL_LINK] if CHANNEL_LINK else []
            _GATE_CH['list'] = links
        return list(_GATE_CH['list'])


def set_gate_channels(links):
    _gate_ch_save_db(list(links))
    with _gate_ch_lock:
        _GATE_CH['list'] = list(links)


def _g_ch_name(link):
    n = _g_parse_channel(link)
    return str(n if n is not None else link).lower()


def g_normalize_channel_link(raw):
    """لینک یا @یوزرنیم → (لینک نرمال‌شده, یوزرنیم) یا None اگه معتبر نبود (لینک دعوت خصوصی هم پشتیبانی نمی‌شه)."""
    s = str(raw or '').strip()
    if not s or len(s) > 200:
        return None
    name = _g_parse_channel(s)
    if name is None or isinstance(name, int) or not re.fullmatch(r'[\w.\-]{3,64}', str(name)):
        return None
    name = str(name)
    if s.lower().startswith(('http://', 'https://')):
        link = s.split('?')[0].rstrip('/')
    elif '/' in s:
        link = 'https://' + s.split('?')[0].rstrip('/')
    else:
        link = 'https://splus.ir/' + name
    return link, name


def g_forget_channel(link):
    """وضعیت درون‌حافظه‌ای یه کانال حذف‌شده رو پاک می‌کنه."""
    for k in ('chs', 'modes', 'refreshed', 'members'):
        _G[k].pop(link, None)
    with _member_cache_guard:
        for k in [k for k in _member_cache if k[1] == link]:
            _member_cache.pop(k, None)

def g_contact_kb():
    return {
        'keyboard': [[{'text': u('fa', 'admin_btn_send_number'), 'request_contact': True}]],
        'resize_keyboard': True,
        'one_time_keyboard': True,
    }
G_REMOVE_KB = {'remove_keyboard': True}


# ---------------- تنظیمات محلی (فقط شماره‌ی ذخیره‌شده) ----------------
def _g_cfg_load():
    if os.path.exists(GATE_CONFIG_PATH):
        try:
            with open(GATE_CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _g_cfg_save(cfg):
    with open(GATE_CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False)


def g_normalize_phone(s):
    d = re.sub(r'\D', '', str(s))
    if d.startswith('00'):
        d = d[2:]
    if d.startswith('0'):
        d = '98' + d[1:]
    elif len(d) == 10 and d.startswith('9'):
        d = '98' + d
    return '+' + d if len(d) >= 10 else None


def _g_parse_channel(raw):
    s = str(raw or '').strip()
    if not s:
        return None
    if re.fullmatch(r'-?\d+', s):
        return int(s)
    s = s.split('?')[0].rstrip('/')
    if 'joinchat' in s.lower() or s.split('/')[-1].startswith('+'):
        return None  # لینک دعوت خصوصی پشتیبانی نمی‌شه
    return s.split('/')[-1].lstrip('@') or None


def g_notify_admin(text, markup=None):
    send_message(ADMIN_ID, text, parse_mode=None, reply_markup=markup)


# ---------------- گرفتن کد/رمز لاگین از ادمین ----------------
def g_ask(kind):
    while not _G_ANSWERS.empty():
        _G_ANSWERS.get_nowait()
    _G['waiting'] = kind
    if kind == 'code':
        g_notify_admin('📩 کد تأیید به سروش پلاسِ اکانتت ارسال شد.\n'
                       'کد رو همین‌جا بفرست — ولی با خط‌تیره بین رقم‌ها، مثلاً 1-2-3-4-5\n'
                       '(اگه کد رو سرراست تو چت بفرستی ممکنه سروش پلاس باطلش کنه)')
    else:
        g_notify_admin('🔐 اکانتت رمز دومرحله‌ای داره. رمزت رو بفرست:')
    try:
        ans = _G_ANSWERS.get(timeout=GATE_CODE_TIMEOUT)
    except queue.Empty:
        _G['waiting'] = None
        raise TimeoutError('از ادمین جوابی نیومد')
    _G['waiting'] = None
    return re.sub(r'\D', '', ans) if kind == 'code' else ans


def _g_fake_input(prompt=''):
    p = str(prompt).lower()
    if any(k in p for k in ('phone', 'mobile', 'number', 'شماره')):
        return _G['phone'] or ''
    if any(k in p for k in ('pass', '2fa', 'رمز')):
        return g_ask('password')
    return g_ask('code')


if G_AVAILABLE:
    builtins.input = _g_fake_input
    getpass.getpass = lambda prompt='', stream=None: _g_fake_input(prompt)


# ---------------- منطق یوزربات (async) ----------------
async def g_get_channel(client, link):
    ch = _G['chs'].get(link)
    if ch is not None:
        return ch
    getter = getattr(client, 'get_entity', None) or getattr(client, 'get_chat')
    ch = await getter(_g_parse_channel(link))
    _G['chs'][link] = ch
    return ch


async def g_raw_all_users(client, ch):
    """همه‌ی اعضا رو با چند فیلتر و صفحه‌بندی از GetParticipantsRequest می‌گیره (اجتماع نتایج)."""
    ids = set()
    if tl_functions is None or tl_types is None:
        return ids
    try:
        inp = await client.get_input_entity(ch)
    except Exception as e:
        print('[gate] get_input_entity(channel) error:', repr(e))
        return ids
    makers = (('Recent', lambda: tl_types.ChannelParticipantsRecent()),
              ('Search', lambda: tl_types.ChannelParticipantsSearch(q='')),
              ('Admins', lambda: tl_types.ChannelParticipantsAdmins()))

    async def _one(name, mk):
        got = set()
        offset = 0
        while offset < 20000:
            try:
                res = await client(tl_functions.channels.GetParticipantsRequest(
                    channel=inp, filter=mk(), offset=offset, limit=200, hash=0))
            except Exception as e:
                print(f'[gate] GetParticipants({name}) error:', repr(e))
                break
            parts = getattr(res, 'participants', None) or []
            if not parts:
                break
            for pt in parts:
                uid_ = _g_part_uid(pt)
                if uid_ is not None and _g_is_member_participant(pt):
                    got.add(uid_)
            offset += len(parts)
            if len(parts) < 200:
                break
        return got

    # فیلترها هم‌زمان اجرا می‌شن (به‌جای پشت‌سرهم) تا همگام‌سازی سریع‌تر تموم بشه
    for got in await asyncio.gather(*[_one(n, m) for n, m in makers]):
        ids |= got
    return ids


async def g_deep_search(client, ch, have):
    """اگه تعداد واقعی اعضای کانال بیشتر از لیست گرفته‌شده بود، با جست‌وجوی حرف‌به‌حرف دنبال بقیه می‌گرده."""
    extra = set()
    if os.getenv("GATE_DEEP_SEARCH", "0").strip() != "1":
        return extra  # پیش‌فرض خاموش: ۶۷ درخواست پشت‌سرهم بات رو کند می‌کرد
    if tl_functions is None or tl_types is None:
        return extra
    now = time.time()
    if now - _G.get('deep_ts', 0.0) < 600:
        return extra
    try:
        inp = await client.get_input_entity(ch)
        full = await client(tl_functions.channels.GetFullChannelRequest(inp))
        total = getattr(getattr(full, 'full_chat', None), 'participants_count', None)
    except Exception as e:
        print('[gate] GetFullChannel error:', repr(e))
        return extra
    if not total or total <= have:
        return extra
    _G['deep_ts'] = now
    print(f'[gate] count mismatch: channel={total} list={have}; deep search ...')
    letters = 'abcdefghijklmnopqrstuvwxyz0123456789' + 'ابپتثجچحخدذرزسشصضطظعغفقکگلمنوهی'
    for ch_q in letters:
        try:
            res = await client(tl_functions.channels.GetParticipantsRequest(
                channel=inp, filter=tl_types.ChannelParticipantsSearch(q=ch_q),
                offset=0, limit=200, hash=0))
        except Exception as e:
            print('[gate] deep search error:', repr(e))
            break
        for pt in (getattr(res, 'participants', None) or []):
            uid_ = _g_part_uid(pt)
            if uid_ is not None and _g_is_member_participant(pt):
                extra.add(uid_)
    print(f'[gate] deep search found {len(extra)} ids')
    return extra


async def g_list_members(client, ch):
    ids = await g_raw_all_users(client, ch)
    n_raw = len(ids)
    n_lib = 0
    if not ids:
        # روش خام جواب نداد؛ متد آماده‌ی کتابخونه رو امتحان کن
        try:
            if hasattr(client, 'iter_participants'):
                async for p in client.iter_participants(ch):
                    ids.add(p.id)
            elif hasattr(client, 'get_participants'):
                ids = {p.id for p in await client.get_participants(ch)}
        except Exception as e:
            print('[gate] list_members error:', repr(e))
        n_lib = len(ids)
    ids |= await g_deep_search(client, ch, len(ids))
    _lk = getattr(ch, 'id', None) or str(ch)
    _ln = _G.setdefault('last_log_n_map', {})
    if _ln.get(_lk) != len(ids):
        _ln[_lk] = len(ids)
        print(f'[gate] members: raw={n_raw} lib={n_lib} total={len(ids)} channel={(getattr(ch, "title", None) or getattr(ch, "id", ch))!r}')
    return ids


async def g_refresh_members(client, link, force=False):
    now = time.time()
    if now - _G['refreshed'].get(link, 0.0) < (2 if force else 10):
        return len(_gm(link))  # همین الان تازه شده؛ دوباره نزن
    _G['refreshed'][link] = now
    ch = await g_get_channel(client, link)
    ids = await g_list_members(client, ch)
    if ids:
        _G['members'][link] = set(ids)
        _G['modes'][link] = 'full'
    else:
        _G['modes'][link] = 'live'
    return len(ids)


async def g_resolve_user(client, uid):
    for getter in ('get_input_entity', 'get_entity'):
        fn = getattr(client, getter, None)
        if not fn:
            continue
        try:
            return await fn(uid)
        except Exception:
            pass
    if tl_types is not None and tl_functions is not None:
        try:
            iu = tl_types.InputUser(user_id=uid, access_hash=0)
            res = await client(tl_functions.users.GetUsersRequest([iu]))
            if res:
                return await client.get_input_entity(res[0])
        except Exception:
            pass
    return None


def _g_part_uid(pt):
    """آیدی کاربرِ یک participant (فقط خودِ participant؛ نه users جانبی مثل دعوت‌کننده)."""
    uid_ = getattr(pt, 'user_id', None)
    if uid_ is None:
        peer = getattr(pt, 'peer', None)
        uid_ = getattr(peer, 'user_id', None)
    return uid_


def _g_is_member_participant(part):
    if tl_types is None:
        return True
    return not isinstance(part, (tl_types.ChannelParticipantLeft, tl_types.ChannelParticipantBanned))


async def g_check_one(client, ch, link, uid, force=False):
    """True/False."""
    if force:
        # چک اجباری (/start یا دکمه‌ی «عضو شدم»): اول لیست رو تازه کن تا لفت‌دادن‌ها دیده بشن
        try:
            await g_refresh_members(client, link, force=True)
        except Exception as e:
            print('[gate] forced refresh failed:', repr(e))
    if uid in _gm(link):
        return True
    # لیست قدیمیه (هر ۵ دقیقه همگام می‌شه)؛ قبل از هر کاری تازه‌اش کن
    if not force:
        try:
            await g_refresh_members(client, link, force=False)
        except Exception as e:
            print('[gate] refresh before check failed:', repr(e))
        if uid in _gm(link):
            return True
    if _G.get('peruser_unsupported', os.getenv('GATE_PERUSER', '0').strip() != '1'):
        return False  # چک تکی پشتیبانی نمی‌شه و لیست تازه‌ست؛ الکی منتظر نمون
    print(f'[gate] check uid={uid}: not in list (size={len(_gm(link))}, mode={_G["modes"].get(link)}, '
          f'ids={sorted(_gm(link))})')
    user = await g_resolve_user(client, uid)
    if user is None:
        # اکانت هنوز این کاربر رو ندیده (مثلاً تازه عضو شده)؛ لیست رو تازه کن و دوباره تلاش کن
        await g_refresh_members(client, link, force=force)
        if uid in _gm(link):
            return True
        user = await g_resolve_user(client, uid)
        if user is None:
            print(f'[gate] user {uid} not in member list and cannot be resolved -> not member')
            return False

    if tl_functions is not None:
        try:
            res = await client(tl_functions.channels.GetParticipantRequest(ch, user))
            return _g_is_member_participant(res.participant)
        except Exception as e:
            if 'NotParticipant' in type(e).__name__:
                return False
            if 'NOT_SUPPORTED' in repr(e):
                _G['peruser_unsupported'] = True  # سروش پلاس چک تکی رو پشتیبانی نمی‌کنه
            print('[gate] GetParticipant error:', repr(e))

    if hasattr(client, 'get_chat_member'):
        try:
            m = await client.get_chat_member(ch, user)
            status = str(getattr(m, 'status', '')).lower()
            if status:
                return not any(s in status for s in ('left', 'banned', 'kicked'))
        except Exception as e:
            print('[gate] get_chat_member error:', repr(e))

    if hasattr(client, 'get_permissions'):
        try:
            if (await client.get_permissions(ch, user)) is not None:
                return True
        except Exception as e:
            if 'NotParticipant' in type(e).__name__:
                return False
            print('[gate] get_permissions error:', repr(e))

    return uid in _gm(link)


async def g_check_live(client, uid, link, force=False):
    ch = await g_get_channel(client, link)
    return await g_check_one(client, ch, link, uid, force=force)


def _g_event_links(event):
    """لینک کانال(های) مربوط به یه رویداد عضویت؛ اگه تشخیص داده نشه None."""
    try:
        cid = getattr(event, 'chat_id', None)
        if cid is None:
            return None
        cid_s = str(abs(int(cid)))
        hits = []
        for lk, ch in list(_G['chs'].items()):
            chid = getattr(ch, 'id', None)
            if chid is None:
                continue
            chid_s = str(abs(int(chid)))
            if cid_s == chid_s or cid_s.endswith(chid_s):
                hits.append(lk)
        return hits or None
    except Exception:
        return None


def g_register_join_handler(client):
    if sp_events is None or not hasattr(client, 'add_event_handler'):
        print('[gate] events پشتیبانی نمی‌شه؛ فقط چک زنده فعاله')
        return
    try:
        async def _on_action(event):
            try:
                uids = list(getattr(event, 'user_ids', None) or [])
                single = getattr(event, 'user_id', None)
                if single is not None:
                    uids.append(single)
                if not uids:
                    return
                links = _g_event_links(event)
                if getattr(event, 'user_left', False) or getattr(event, 'user_kicked', False):
                    # کانال رویداد معلوم نبود: از همه‌ی کانال‌ها حذف می‌کنیم (بی‌خطره؛ دور بعدی همگام‌سازی درستش می‌کنه)
                    for lk in (links if links is not None else list(_G['members'].keys())):
                        for x in uids:
                            _gm(lk).discard(x)
                elif links:
                    # عضو شدن فقط وقتی اعمال می‌شه که کانالش معلوم باشه؛ وگرنه همگام‌سازی دوره‌ای اضافه‌ش می‌کنه
                    for lk in links:
                        for x in uids:
                            _gm(lk).add(x)
            except Exception as e:
                print('[gate] event handler error:', repr(e))

        client.add_event_handler(_on_action, sp_events.ChatAction())
    except Exception as e:
        print('[gate] register handler error:', repr(e))


async def g_sync_loop(client, gen):
    notified = {}
    while _G['gen'] == gen:
        for link in get_gate_channels():
            if _G['gen'] != gen:
                return
            try:
                n = await g_refresh_members(client, link, force=True)
                mode = _G['modes'].get(link)
                key = (link, mode)
                if notified.get(link) != key:
                    notified[link] = key
                    if mode == 'full':
                        g_notify_admin(f'✅ کانال {link} همگام شد ({n} عضو). عضویت‌ها از الان چک می‌شن.')
                    else:
                        g_notify_admin(f'✅ به کانال {link} وصل شدم. لیست کامل اعضا برنگشت، پس عضویت هر کاربر '
                                       'موقع درخواست زنده چک می‌شه.')
            except Exception as e:
                print('[gate] sync error:', link, repr(e))
                if 'flood' in repr(e).lower() or 'too_many' in repr(e).lower() or '429' in repr(e):
                    _G['flood'] = True
                _G['chs'].pop(link, None)
                if notified.get(link) != ('err', link):
                    notified[link] = ('err', link)
                    g_notify_admin(f'⚠️ نتونستم به کانال {link} وصل بشم. مطمئن شو لینک درسته و اکانت '
                                   f'({_G["account"] or "؟"}) مالک/ادمین کانال هست.\nخطا: {e!r}')
        wait = GATE_SYNC_INTERVAL
        if _G.pop('flood', False):
            wait = max(wait, 60)  # محدودیت سرعت سروش پلاس؛ یه مدت آروم‌تر
        for _ in range(int(wait)):
            if _G['gen'] != gen:
                return
            await asyncio.sleep(1)


async def g_userbot_main(phone, gen):
    _G['loop'] = asyncio.get_running_loop()

    client = spluspy.Client(GATE_SESSION_NAME)
    kwargs = {'phone': phone}
    try:
        if 'code_callback' in inspect.signature(client.start).parameters:
            kwargs['code_callback'] = lambda: g_ask('code')
    except (TypeError, ValueError):
        pass

    res = client.start(**kwargs)
    if inspect.isawaitable(res):
        await res

    cfg = _g_cfg_load()
    cfg['phone'] = phone
    _g_cfg_save(cfg)

    try:
        me = client.get_me()
        if inspect.isawaitable(me):
            me = await me
        uname = getattr(me, 'username', None)
        _G['account'] = ('@' + uname) if uname else str(getattr(me, 'id', ''))
    except Exception as e:
        print('[gate] get_me error:', repr(e))

    if _G['gen'] != gen:
        return
    g_register_join_handler(client)
    _G['running'], _G['starting'], _G['client'] = True, False, client
    g_notify_admin('✅ لاگین انجام شد. در حال همگام‌سازی کانال‌ها ...')

    await g_sync_loop(client, gen)


def g_userbot_thread(phone, gen):
    try:
        asyncio.run(g_userbot_main(phone, gen))
    except Exception as e:
        print('[gate] userbot error:', repr(e))
        if _G['gen'] == gen:
            _G['running'], _G['starting'], _G['waiting'] = False, False, None
            g_notify_admin(f'❌ خطا در اتصال اکانت:\n{e!r}\n\nدوباره /start بزن.')


def g_start_userbot(phone):
    _G['gen'] += 1
    gen = _G['gen']
    _G.update({'phone': phone, 'starting': True, 'running': False, 'client': None, 'chs': {}})
    threading.Thread(target=g_userbot_thread, args=(phone, gen), daemon=True).start()


# ---------------- ذخیره‌ی سشن لاگین تو دیتابیس (تا با ریدیپلوی از بین نره) ----------------
_G_DB_KEY = 'session'
_G_SKIP_SUFFIX = ('-journal', '-wal', '-shm')


@with_db_retry
def _g_db_exec(sql, params=()):
    conn = get_conn()
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS gate_storage (name TEXT PRIMARY KEY, value TEXT)')
    c.execute(sql, params)
    row = c.fetchone() if sql.lstrip().upper().startswith('SELECT') else None
    conn.commit()
    conn.close()
    return row


def _g_session_files():
    return [f for f in glob.glob(GATE_SESSION_NAME + '*') if not f.endswith(_G_SKIP_SUFFIX) and os.path.isfile(f)]


def g_forget_session_in_db():
    try:
        _g_db_exec('DELETE FROM gate_storage WHERE name=?', (_G_DB_KEY,))
    except Exception as e:
        print('[gate] پاک‌کردن سشن از دیتابیس ناموفق بود:', repr(e))


def g_boot_restore():
    if not (GATE_ENABLED and G_AVAILABLE):
        return
    g_forget_session_in_db()                 # سشنِ باقی‌مونده‌ی قدیمی تو دیتابیس (اگه بود) پاک بشه
    phone = _g_cfg_load().get('phone')
    if phone and _g_session_files():
        g_start_userbot(phone)               # سشن روی همین دیسک هنوز هست (ریدیپلوی نشده)
        return
    # سشنی نیست (مثلاً بعد از ریدیپلوی): از ادمین بخواه دوباره لاگین کنه
    try:
        g_notify_admin('🔐 اکانت عضویت اجباری وصل نیست (احتمالاً بات ریدیپلوی شده).\n'
                       'برای وصل‌شدن دوباره، /start بزن و شماره/کد رو بفرست.')
    except Exception as e:
        print('[gate] پیام درخواست لاگین به ادمین نرفت:', repr(e))


async def _g_safe_disconnect(client):
    res = client.disconnect()
    if inspect.isawaitable(res):
        await res


def g_disconnect():
    _G['gen'] += 1  # حلقه‌ی همگام‌سازی قبلی خودش تموم می‌شه
    client, loop = _G['client'], _G['loop']
    if client is not None and loop is not None:
        try:
            asyncio.run_coroutine_threadsafe(_g_safe_disconnect(client), loop).result(timeout=10)
        except Exception:
            pass
    try:
        _g_cfg_save({})
    except Exception:
        pass
    g_forget_session_in_db()
    for f in glob.glob(GATE_SESSION_NAME + '*'):
        try:
            os.remove(f)
        except Exception:
            pass
    _G.update({'running': False, 'starting': False, 'waiting': None, 'phone': None, 'account': None,
               'client': None, 'loop': None, 'chs': {}, 'modes': {}, 'refreshed': {}, 'members': {}})
    with _member_cache_guard:
        _member_cache.clear()


_BOTAPI_GATE = {'works': None}


def bot_api_check_member(user_id, link=None):
    """چک عضویت با خود Bot API (getChatMember). True/False، یا None اگه پشتیبانی نشه
    یا بات تو کانال ادمین نباشه. برای کار کردنش بات باید ادمین کانال باشه."""
    if _BOTAPI_GATE['works'] is False:
        return None
    target = _g_parse_channel(link or CHANNEL_LINK)
    if target is None:
        return None
    chat = target if isinstance(target, int) else '@' + str(target)
    try:
        res = SESSION.post(BASE_URL + '/getChatMember', json={'chat_id': chat, 'user_id': user_id}, timeout=8)
        data = res.json()
    except Exception as e:
        print('[gate] botapi getChatMember exception:', repr(e))
        _BOTAPI_GATE['works'] = False
        return None
    if not data.get('ok'):
        print('[gate] botapi getChatMember not ok:', str(data)[:200])
        _BOTAPI_GATE['works'] = False  # بات ادمین کانال نیست/پشتیبانی نمی‌شه؛ دیگه تکرار نکن
        return None
    _BOTAPI_GATE['works'] = True
    status = str((data.get('result') or {}).get('status', '')).lower()
    if status in ('member', 'administrator', 'creator', 'owner', 'restricted'):
        return True
    if status in ('left', 'kicked', 'banned'):
        return False
    return None


# ---------------- چک عضویت (برای بقیه‌ی کد بات) ----------------
def _check_one_channel(user_id, link, use_cache=True):
    """True (عضوه) / False (عضو نیست) / None (اکانت وصل نیست یا چک جواب نداد) برای یک کانال مشخص."""
    client, loop = _G['client'], _G['loop']
    if not _G['running'] or client is None or loop is None:
        return None
    now = time.time()
    ck = (user_id, link)
    if use_cache:
        if user_id in _gm(link):
            return True
        with _member_cache_guard:
            ts = _member_cache.get(ck)
        if ts and now - ts < GATE_CACHE_TTL:
            return True
    if os.getenv('GATE_BOTAPI', '0').strip() == '1' and bot_api_check_member(user_id, link) is True:
        with _member_cache_guard:
            _member_cache[ck] = now
        return True
    if use_cache and _G['modes'].get(link) == 'full' and now - _G['refreshed'].get(link, 0.0) < 30 \
            and _G.get('peruser_unsupported', os.getenv('GATE_PERUSER', '0').strip() != '1'):
        # لیست همین چند ثانیه پیش تازه شده و چک تکی هم ممکن نیست؛ نیازی به رفت‌وبرگشت به لوپ یوزربات نیست
        return False
    try:
        fut = asyncio.run_coroutine_threadsafe(g_check_live(client, user_id, link, force=not use_cache), loop)
        member = bool(fut.result(timeout=GATE_LIVE_TIMEOUT))
    except Exception as e:
        print('⚠️ خطا در چک عضویت:', repr(e))
        return None
    with _member_cache_guard:
        if member:
            _member_cache[ck] = now
        else:
            _member_cache.pop(ck, None)
    if not member:
        _gm(link).discard(user_id)
    return member


def check_channels_status(user_id, use_cache=True):
    """(وضعیت, کانال‌های ناقص): وضعیت True = عضو «همه‌ی» کانال‌هاست، False = حداقل یکی رو عضو نیست
    (لینکش تو لیست دوم میاد)، None = چک جواب نداد. اگه هیچ کانالی ثبت نشده باشه همه رد می‌شن."""
    links = get_gate_channels()
    if not links:
        return True, []
    missing, unknown = [], False
    for link in links:
        st = _check_one_channel(user_id, link, use_cache)
        if st is False:
            missing.append(link)
        elif st is None:
            unknown = True
    if missing:
        return False, missing
    if unknown:
        return None, []
    return True, []


# ---------------- لاگین اکانت از طریق چت ادمین ----------------
def admin_gate_handler(update):
    """پیام‌های ادمین مربوط به لاگین/مدیریت اکانت رو مدیریت می‌کنه. True یعنی مصرف شد."""
    if not GATE_ENABLED:
        return False
    m = update.get('message')
    if not m:
        return False
    chat_id = m.get('chat', {}).get('id')
    if chat_id != ADMIN_ID:
        return False
    text = (m.get('text') or '').strip()
    if not G_AVAILABLE:
        # به‌جای سکوت، به ادمین بگو چرا شماره نمی‌خواد (منوی عادی هم نشون داده می‌شه)
        if text.startswith('/start') or text.startswith('/gatestatus'):
            g_notify_admin('⚠️ عضویت اجباری غیرفعاله چون کتابخونه‌ی spluspy روی سرور این بات نصب نیست.\n'
                           'spluspy رو به requirements همین بات اضافه کن و دوباره دیپلوی کن.')
        return False
    contact = m.get('contact')
    cmd = text.split()[0].split('@')[0].lower() if text.startswith('/') else ''

    # جواب کد تأیید / رمز دومرحله‌ای (پیام بعد از دریافت پاک می‌شه)
    if _G['waiting'] and text and not cmd:
        _G_ANSWERS.put(text)
        if m.get('message_id') is not None:
            delete_message(chat_id, m['message_id'])
        return True

    if cmd == '/gatestatus':
        status = '🟢 وصل' if _G['running'] else ('🟡 در حال وصل‌شدن' if _G['starting'] else '🔴 وصل نیست (/start)')
        lines = []
        for lk in get_gate_channels():
            md = {'full': 'لیست کامل', 'live': 'چک زنده'}.get(_G['modes'].get(lk), '—')
            lines.append(f'• {lk} — {md} — {len(_gm(lk))} عضو')
        g_notify_admin(f'وضعیت اکانت: {status}\nاکانت: {_G["account"] or "—"}\nکانال‌ها:\n' + ('\n'.join(lines) or '—'))
        return True

    if cmd == '/gatedisconnect':
        g_disconnect()
        g_notify_admin('🗑 اکانت قطع شد و سشن پاک شد. برای وصل‌شدن دوباره /start بزن.')
        return True

    if cmd == '/start' and not (_G['running'] or _G['starting'] or _G['waiting']):
        _G_TSTATE['phone'] = True
        send_message(chat_id, '📱 برای کنترل عضویت کاربرها تو کانال، شماره‌ی اکانتی رو بفرست که مالک/ادمین '
                              'کانال هست (با دکمه‌ی زیر یا دستی تایپ کن).\nبرای رد شدن /cancel بزن.',
                     parse_mode=None, reply_markup=g_contact_kb())
        return True

    if _G_TSTATE.get('phone'):
        if cmd == '/cancel':
            _G_TSTATE.pop('phone', None)
            send_message(chat_id, 'باشه، لغو شد.', parse_mode=None, reply_markup=G_REMOVE_KB)
            main_menu(chat_id)
            return True
        if contact or (text and not cmd):
            phone = g_normalize_phone((contact or {}).get('phone_number') or text)
            if not phone:
                send_message(chat_id, 'این رو نتونستم به‌عنوان شماره بخونم. دوباره بفرست.',
                             parse_mode=None, reply_markup=g_contact_kb())
                return True
            _G_TSTATE.pop('phone', None)
            print('[gate] شماره از ادمین دریافت شد؛ شروع لاگین اکانت:', phone)
            send_message(chat_id, f'📲 در حال ورود با شماره {phone} ...', parse_mode=None,
                         reply_markup=G_REMOVE_KB)
            g_start_userbot(phone)
            return True
        # پیامی که نه شماره بود نه متن (مثلاً ساختار غیرمنتظره‌ی contact): بی‌صدا ردش نکن
        print('[gate] پیام نامعتبر تو مرحله‌ی شماره؛ کلیدهای پیام:', list(m.keys()))
        send_message(chat_id, 'نتونستم شماره رو بخونم. با دکمه‌ی «ارسال شماره من» یا تایپ دستی بفرست '
                              '(برای رد شدن /cancel).', parse_mode=None, reply_markup=g_contact_kb())
        return True
    return False


# ---------------- گیت روی آپدیت‌ها ----------------
def join_keyboard(chat_id, links=None):
    """یه دکمه‌ی عضویت برای هر کانال (اگه معلوم باشه، فقط اونایی که کاربر هنوز عضوشون نیست) + «✅ عضو شدم»."""
    links = list(links or get_gate_channels())
    rows = []
    for i, lk in enumerate(links, 1):
        label = u(chat_id, 'btn_join_channel')
        if len(links) > 1:
            nm = _g_parse_channel(lk)
            label += f' @{nm}' if isinstance(nm, str) else f' {i}'
        rows.append([{'text': label, 'url': lk}])
    rows.append([{'text': u(chat_id, 'btn_joined'), 'callback_data': 'check_join'}])
    return {'inline_keyboard': rows}


def join_gate(update):
    """True یعنی این آپدیت همین‌جا مدیریت شد (کاربر عضو همه‌ی کانال‌ها نیست) و نباید به
    process_update بره؛ False یعنی ادامه بده."""
    if not (GATE_ENABLED and G_AVAILABLE):
        return False

    cb_id = None
    is_check_btn = False
    if 'callback_query' in update:
        q = update['callback_query']
        chat_id = q.get('message', {}).get('chat', {}).get('id')
        user_id = (q.get('from') or {}).get('id', chat_id)
        cb_id = q.get('id')
        is_check_btn = (q.get('data') == 'check_join')
    elif 'message' in update:
        msg = update['message']
        chat_id = msg.get('chat', {}).get('id')
        user_id = (msg.get('from') or {}).get('id', chat_id)
    else:
        return False

    if chat_id is None or user_id is None or chat_id == ADMIN_ID:
        return False

    if is_check_btn:
        answer_callback(cb_id)
        status, missing = check_channels_status(user_id, use_cache=False)
        for _retry in range(1):  # تازه‌عضو شده‌ها ممکنه چند ثانیه طول بکشه تا تو لیست بیان
            if status is not False:
                break
            time.sleep(2)
            status, missing = check_channels_status(user_id, use_cache=False)
        if status is True:
            add_user(chat_id)
            user_steps[str(chat_id)] = {}
            send_message(chat_id, u(chat_id, 'join_ok'))
            main_menu(chat_id)
            process_referral_reward(chat_id, 'join')
        elif status is False:
            send_message(chat_id, u(chat_id, 'join_not_yet'), reply_markup=join_keyboard(chat_id, missing))
        else:
            send_message(chat_id, u(chat_id, 'join_check_error'), reply_markup=join_keyboard(chat_id))
        return True

    # لیست اعضا هر ~۱۰ ثانیه تو پس‌زمینه تازه می‌شه؛ پس /start نیازی به چک اجباری (کند) نداره
    status, missing = check_channels_status(user_id)
    if status is True:
        return False
    if status is None and GATE_FAIL_OPEN:
        return False

    if cb_id:
        answer_callback(cb_id)
    if status is False:
        send_message(chat_id, u(chat_id, 'join_required', divider=DIVIDER), reply_markup=join_keyboard(chat_id, missing))
    else:
        send_message(chat_id, u(chat_id, 'join_check_error'), reply_markup=join_keyboard(chat_id))
    return True



# ---------------- پنل ادمین: اضافه/حذف کانال‌های عضویت اجباری ----------------


def _ch_hash(link):
    return hashlib.md5(link.encode('utf-8')).hexdigest()[:8]


async def g_validate_channel(client, link):
    """کانال رو با اکانت یوزربات باز می‌کنه و لیست اعضاش رو می‌گیره → (عنوان, تعداد اعضا).
    اگه لیست اعضا برنگرده (یعنی اکانت ادمین کانال نیست) خطا می‌ده؛ چون با چنین کانالی همه‌ی کاربرها گیر می‌کردن."""
    _G['chs'].pop(link, None)
    ch = await g_get_channel(client, link)
    ids = await g_list_members(client, ch)
    if not ids:
        _G['chs'].pop(link, None)
        raise RuntimeError('لیست اعضای کانال خالی برگشت؛ اکانت باید مالک/ادمین کانال باشه')
    _G['members'][link] = set(ids)
    _G['modes'][link] = 'full'
    _G['refreshed'][link] = time.time()
    title = getattr(ch, 'title', None) or getattr(ch, 'username', None) or link
    return str(title), len(ids)


def admin_channels_panel(chat_id, note=None):
    if not GATE_ENABLED:
        send_message(chat_id, '⛔ عضویت اجباری با GATE_ENABLED=0 خاموشه.', parse_mode=None)
        return
    if not G_AVAILABLE:
        send_message(chat_id, '⚠️ کتابخونه‌ی spluspy نصب نیست، برای همین عضویت اجباری کار نمی‌کنه.', parse_mode=None)
        return
    links = get_gate_channels()
    body = ('\n'.join(f'{i}. {lk}' for i, lk in enumerate(links, 1)) if links
            else 'هیچ کانالی ثبت نشده؛ فعلاً عضویت اجباری برای کاربرها اعمال نمی‌شه.')
    text = (note + '\n\n' if note else '') + '📢 کانال‌های عضویت اجباری\n' + DIVIDER + '\n' + body
    if links:
        text += '\n\nکاربر باید عضو همه‌ی این کانال‌ها باشه.'
    if not _G['running']:
        text += '\n\n⚠️ اکانت لاگین نیست؛ اول با /start لاگینش کن.'
    rows = [[{'text': u('fa', 'admin_btn_channel_add'), 'callback_data': 'admin_ch_add'}]]
    for i, lk in enumerate(links, 1):
        nm = _g_parse_channel(lk)
        rows.append([{'text': u('fa', 'admin_btn_channel_del', i=i, name=(f' (@{nm})' if isinstance(nm, str) else '')),
                      'callback_data': 'admin_ch_del_' + _ch_hash(lk)}])
    send_message(chat_id, text, parse_mode=None, reply_markup={'inline_keyboard': rows})


def admin_add_channel_ask(chat_id):
    if not (_G['running'] and _G['client'] is not None and _G['loop'] is not None):
        admin_channels_panel(chat_id, note='⚠️ اول باید اکانت لاگین باشه (با /start).')
        return
    user_steps[str(chat_id)] = {'step': 'admin_add_channel'}
    send_message(chat_id, '🔗 لینک یا @یوزرنیم کانال رو بفرست (مثلاً https://splus.ir/mychannel).\n'
                          f'اکانت ({_G["account"] or "؟"}) باید مالک/ادمین اون کانال باشه.',
                 parse_mode=None, reply_markup=cancel_kb(chat_id))


def admin_add_channel_submit(chat_id, text):
    norm = g_normalize_channel_link(text)
    if not norm:
        send_message(chat_id, '⚠️ این لینک/یوزرنیم معتبر نیست (لینک دعوت خصوصی هم پشتیبانی نمی‌شه). '
                              'دوباره بفرست یا انصراف بزن.', parse_mode=None, reply_markup=cancel_kb(chat_id))
        return
    link, name = norm
    links = get_gate_channels()
    if any(_g_ch_name(x) == name.lower() for x in links):
        user_steps[str(chat_id)] = {}
        admin_channels_panel(chat_id, note='ℹ️ این کانال از قبل تو لیست هست.')
        return
    client, loop = _G['client'], _G['loop']
    if not (_G['running'] and client is not None and loop is not None):
        user_steps[str(chat_id)] = {}
        admin_channels_panel(chat_id, note='⚠️ اکانت لاگین نیست؛ اول با /start لاگین کن.')
        return
    send_message(chat_id, '⏳ در حال بررسی کانال ...', parse_mode=None)
    try:
        title, count = asyncio.run_coroutine_threadsafe(g_validate_channel(client, link), loop).result(timeout=40)
    except Exception as e:
        print('[gate] validate channel error:', link, repr(e))
        user_steps[str(chat_id)] = {}
        send_message(chat_id, f'❌ نتونستم کانال رو اضافه کنم. مطمئن شو لینک درسته و اکانت ({_G["account"] or "؟"}) '
                              f'مالک/ادمین کانال هست.\nخطا: {str(e) or repr(e)}', parse_mode=None)
        return
    set_gate_channels(links + [link])
    user_steps[str(chat_id)] = {}
    admin_channels_panel(chat_id, note=f'✅ کانال «{title}» اضافه شد ({count} عضو). از الان کاربرها باید عضوش هم باشن.')


def admin_remove_channel(chat_id, h):
    links = get_gate_channels()
    target = next((lk for lk in links if _ch_hash(lk) == h), None)
    if not target:
        admin_channels_panel(chat_id, note='⚠️ این کانال دیگه تو لیست نیست.')
        return
    set_gate_channels([lk for lk in links if lk != target])
    g_forget_channel(target)
    admin_channels_panel(chat_id, note=f'🗑 کانال {target} از عضویت اجباری حذف شد.')


g_boot_restore()


def safe_process_update(update):
    """آپدیت رو پردازش می‌کنه، ولی قبلش قفل مخصوص همون chat_id رو می‌گیره.
    این یعنی دو تا آپدیت از دو کاربر مختلف هنوز کاملاً موازی پردازش می‌شن
    (سرعتی که هدفمون بود)، اما اگه یه کاربر رو دکمه‌ای مثل «تایید خرید» دوبار
    پشت‌سرهم بزنه، تردِ دوم صبر می‌کنه تا تردِ اول کاملاً تموم بشه (و
    user_steps کاربر رو ریست کنه) — و چون دیگه step به 'confirm_buy' نیست، تلاش
    دوم به جای ساخت/پرداخت تکراری، فقط منوی اصلی رو نشون می‌ده."""
    chat_id = None
    if 'callback_query' in update:
        chat_id = update['callback_query'].get('message', {}).get('chat', {}).get('id')
    elif 'message' in update:
        chat_id = update['message'].get('chat', {}).get('id')

    def _run():
        t0 = time.time()
        capture_referral(update)   # قبل از گیت عضویت اجباری، تا لینک دعوت گم نشه
        try:
            track_activity(update)
        except Exception as e:
            print('⚠️ track_activity:', e)
        handled = admin_gate_handler(update) or join_gate(update)
        t1 = time.time()
        if not handled:
            process_update(update)
        t2 = time.time()
        if t2 - t0 > 1.5:  # لاگ کندی: معلوم می‌کنه وقت تو گیت رفته یا تو خودِ هندلر
            what = ((update.get('message') or {}).get('text')
                    or (update.get('callback_query') or {}).get('data') or '?')
            print(f'[slow] chat={chat_id} {str(what)[:30]!r} gate={t1 - t0:.1f}s handler={t2 - t1:.1f}s')

    lock = get_chat_lock(chat_id) if chat_id is not None else None
    try:
        if lock:
            with lock:
                _run()
        else:
            _run()
    except Exception as e:
        print('⚠️ خطا در پردازش آپدیت:', e)


while True:
    try:
        _poll_started = time.time()
        updates = get_updates(last_update_id + 1)

        if updates.get('ok') and updates.get('result'):
            for update in updates['result']:
                last_update_id = update['update_id']

                # پردازش این آپدیت تو یه ترد جدا انجام می‌شه (نگاه کنید به
                # process_update/UPDATE_EXECUTOR بالای فایل) تا اگه یه کاربر منتظر
                # یه عملیات کند (مثلاً ساخت کانفیگ) بود، جواب‌دادن به بقیه‌ی
                # کاربرها معطل اون نمونه.
                UPDATE_EXECUTOR.submit(safe_process_update, update)

        else:
            # اگه سرور long-polling رو رعایت کرده (۲۵ ثانیه صبر کرده)، لازم نیست
            # دوباره بخوابیم. فقط وقتی جواب فوری و خالی اومده یه وقفه‌ی خیلی کوتاه
            # می‌ذاریم تا CPU نسوزه (قبلاً همیشه ۱ ثانیه بود و تا ۱ ثانیه به
            # جواب پیام‌ها اضافه می‌کرد).
            if time.time() - _poll_started < 3:
                time.sleep(1 if not updates.get('ok') else 0.2)

    except Exception as loop_error:
        print('⚠️ خطای غیرمنتظره در حلقه اصلی:', loop_error)
        reset_conn()
        time.sleep(2)
