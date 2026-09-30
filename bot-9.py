import requests
import time
import json
import os
import io
import math
import threading
import turso_serverless
import secrets
import hashlib
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False

TOKEN = os.getenv("BOT_TOKEN", "69786607:U_ltmyh-8XS6RuBUsLNiIVi9l0Mq0aekXvE")
BASE_URL = "https://api.splus.ir/bot" + TOKEN
CONFIG_API = os.getenv("CONFIG_API", "https://su.randomatic.ir/api/v1/configs")
CONFIG_KEY = os.getenv("CONFIG_KEY", "sk_live_azIaKWpOvQDoD2-7vX8-yyf3WNPg6U1p")

# --- فروشندگی (reseller): حداقل خرید استخر برای فعال‌سازی و قیمت هر گیگ ---
RESELLER_MIN_GB = int(os.getenv("RESELLER_MIN_GB", "50"))
RESELLER_PRICE_PER_GB = int(os.getenv("RESELLER_PRICE_PER_GB", "2000"))
RESELLER_API_BASE = os.getenv("RESELLER_API_BASE", "http://YOUR-SERVER-IP:8088")
# آدرس پنلی که فروشنده بعد از خرید استخر گیگ باهاش کانفیگ می‌سازه (پیش‌فرض: همون آدرس API)
RESELLER_PANEL_URL = os.getenv("RESELLER_PANEL_URL", "https://web-production-bfd2e.up.railway.app")
ADMIN_ID = int(os.getenv("ADMIN_ID", "48198481"))

# مقادیر پیش‌فرض (fallback) — اگه از پنل وب مقداری تو جدول settings ثبت نشده
# باشه، همین مقادیر استفاده می‌شن. مقدار واقعی و قابل‌تغییر همیشه با
# get_setting() خونده می‌شه (پایین‌تر) تا بدون نیاز به ری‌استارت ربات، از پنل
# قابل تغییر باشه.
DEFAULT_CARD_NUMBER = os.getenv("CARD_NUMBER", "6219861957006504")
DEFAULT_CARD_OWNER = os.getenv("CARD_OWNER", "کمالزاده")
DEFAULT_MIN_TOPUP = os.getenv("MIN_TOPUP", "10000")

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
    return int(get_setting('min_topup', DEFAULT_MIN_TOPUP))


def get_topup_multiplier():
    """ضریب واریزی: مبلغی که کاربر واریز می‌کنه، وقتی ادمین تاییدش می‌کنه، تو
    این ضریب ضرب می‌شه و همون مقدار به کیف پول اضافه می‌شه (مثلاً با ضریب ۲،
    واریز ۱۰,۰۰۰ تومانی = ۲۰,۰۰۰ تومان شارژ کیف پول). پیش‌فرض ۱ یعنی بدون
    تغییر."""
    try:
        return float(get_setting('topup_multiplier', '1'))
    except (TypeError, ValueError):
        return 1.0

TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN")

DIVIDER = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"

# دکمه‌ی «انصراف» که زیر پیام‌های «فقط عدد/متن ارسال کنید» گذاشته می‌شه، تا تو
# سبک کیبورد اینلاین هم کاربر یه راه برگشت به منو داشته باشه (قبلاً فقط با
# تایپ‌کردن یه چیزی یا رفتن به /start می‌شد از این مرحله‌ها خارج شد).
CANCEL_KB = {'inline_keyboard': [[{'text': '❌ انصراف', 'callback_data': 'menu'}]]}

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
            '📶 حجم: <b>0.1</b> گیگابایت\n'
            '⏳ مدت اعتبار: <b>1</b> روز\n{divider}\n'
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
            'بعد از فعال‌سازی، آدرس پنل و کلید API رو می‌گیرید و از همون‌جا برای '
            'مشتری‌هاتون کانفیگ می‌سازید — هر بار ساخت، از همون استخر گیگ کم می‌شه.\n\n'
            '📦 حداقل خرید فعال‌سازی: <b>{min_gb} گیگ</b>\n'
            '💵 مبلغ فعال‌سازی: <b>{activation_price}</b> تومان\n'
        ),
        'btn_reseller_activate': '✅ فعال‌سازی فروشندگی',
        'reseller_activated': (
            '🎉 <b>فروشندگی شما فعال شد!</b>\n{divider}\n'
            '📦 استخر اولیه: <b>{gb} گیگ</b>\n\n'
            '🌐 <b>آدرس پنل:</b>\n<code>{panel_url}</code>\n\n'
            '🔑 <b>API Key:</b>\n<code>{api_key}</code>\n\n'
            '🔒 <b>API Secret</b> (فقط همین یک‌بار نشون داده می‌شه، جایی امن ذخیره‌ش کنید):\n'
            '<code>{api_secret}</code>'
        ),
        'reseller_dashboard': (
            '🧑‍💼 <b>پنل فروشندگی</b>\n{divider}\n'
            '📦 استخر باقیمونده: <b>{gb_balance}</b> گیگ\n'
            '💰 قیمت هر گیگ برای شما: <b>{price_per_gb}</b> تومان\n'
            '📡 وضعیت: <b>{status}</b>\n'
            '🌐 آدرس پنل: <code>{panel_url}</code>\n'
            '🔑 API Key: <code>{api_key}</code>\n'
        ),
        'btn_reseller_topup': '➕ افزایش استخر گیگ',
        'btn_reseller_regen': '🔄 ساخت مجدد کلید API',
        'reseller_topup_prompt': 'چند گیگ می‌خواید به استخرتون اضافه بشه؟ فقط عدد بفرستید.',
        'reseller_topup_confirm_title': (
            '📦 <b>{gb}</b> گیگ به قیمت <b>{price:,}</b> تومان\n'
            'از کیف پولتون کم می‌شه و به استخر اضافه می‌شه. تایید می‌کنید؟'
        ),
        'reseller_topup_done': '✅ {gb} گیگ به استخر شما اضافه شد. موجودی جدید: {gb_balance} گیگ.',
        'reseller_regen_warning': (
            '⚠️ با ساخت کلید جدید، کلید/رمز قبلی دیگه کار نمی‌کنه و هر برنامه‌ای که باهاش '
            'وصل بود قطع می‌شه. مطمئنید؟'
        ),
        'reseller_regen_done': (
            '🔑 <b>کلید جدید API</b>\n{divider}\n'
            'API Key:\n<code>{api_key}</code>\n\n'
            'API Secret (فقط الان نشون داده می‌شه):\n<code>{api_secret}</code>'
        ),
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
            '📶 Volume: <b>0.1</b> GB\n'
            '⏳ Validity: <b>1</b> day\n{divider}\n'
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


def u(chat_id_or_lang, key, **kwargs):
    """متن ترجمه‌شده رو برمی‌گردونه؛ اولین آرگومان یا خودِ chat_id است یا مستقیم
    'fa'/'en'. اگه کلید تو زبان فعلی نبود، از فارسی و در نهایت از خودِ کلید
    استفاده می‌کنه تا هیچ‌وقت پیام خالی/خطا نده."""
    lang = chat_id_or_lang if chat_id_or_lang in ('fa', 'en') else get_user_lang(chat_id_or_lang)
    table = UI_TEXT.get(lang, UI_TEXT['fa'])
    s = table.get(key)
    if s is None:
        s = UI_TEXT['fa'].get(key, key)
    if kwargs:
        try:
            return s.format(**kwargs)
        except Exception:
            return s
    return s


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
_adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=0)
SESSION.mount('https://', _adapter)
SESSION.mount('http://', _adapter)

# آپدیت‌های تلگرام (پیام/callback) به‌جای اجرای یکی‌یکی و پشت‌سرهم، تو این
# استخر ترد پردازش می‌شن. مهم‌ترین اثرش رو زمانی نشون می‌ده که یه کاربر یه کار
# کند (مثلاً ساخت/تمدید کانفیگ روی پنل که وابسته به شبکه‌ست) در حال انجامه:
# قبلاً تا اون تموم نمی‌شد، بات به هیچ پیام دیگه‌ای (حتی «/start» یه نفر دیگه)
# جواب نمی‌داد. max_workers=8 یعنی هم‌زمان حداکثر ۸ آپدیت می‌تونن پردازش بشن؛
# برای یه بات فروش با حجم معمولی کاربر، عدد امن و کافی‌ایه.
UPDATE_EXECUTOR = ThreadPoolExecutor(max_workers=8)

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
    # (RESELLER_PRICE_PER_GB) پر می‌شه؛ سرویس API جدا (reseller_api.py) از همین
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
    c.execute('''CREATE TABLE IF NOT EXISTS topup_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        status TEXT DEFAULT "pending",
        created_at TEXT
    )''')
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
        'ALTER TABLE user_configs ADD COLUMN type TEXT',
        "ALTER TABLE user_configs ADD COLUMN status TEXT DEFAULT 'active'",
        'ALTER TABLE users ADD COLUMN kb_style TEXT',
        'ALTER TABLE users ADD COLUMN lang TEXT',
        "ALTER TABLE reseller_api_configs ADD COLUMN source TEXT DEFAULT 'api'",
    ):
        try:
            c.execute(statement)
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


@with_db_retry
def get_user_kb_style(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT kb_style FROM users WHERE user_id=?', (user_id,))
    res = c.fetchone()
    conn.close()
    return res[0] if res and res[0] else None


@with_db_retry
def set_user_kb_style(user_id, style):
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


@with_db_retry
def upsert_user_info(user_id, username, first_name):
    conn = get_conn()
    c = conn.cursor()
    c.execute('''INSERT INTO users (user_id, wallet, joined_at, username, first_name)
        VALUES (?, 0, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name''',
        (user_id, datetime.now().isoformat(), username, first_name))
    conn.commit()
    conn.close()


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
            api_key=excluded.api_key, secret_hash=excluded.secret_hash,
            gb_balance=resellers.gb_balance + excluded.gb_balance""",
        (user_id, api_key, secret_hash, gb, RESELLER_PRICE_PER_GB, datetime.now().isoformat()))
    conn.commit()
    conn.close()


@with_db_retry
def regenerate_reseller_secret_db(user_id, api_key, secret_hash):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE resellers SET api_key=?, secret_hash=? WHERE user_id=?", (api_key, secret_hash, user_id))
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
def create_topup_request(user_id, amount):
    conn = get_conn()
    c = conn.cursor()
    c.execute('INSERT INTO topup_requests (user_id, amount, created_at) VALUES (?, ?, ?)',
               (user_id, amount, datetime.now().isoformat()))
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
    global _settings_cache, _settings_cache_ts
    now = time.time()
    if now - _settings_cache_ts > _SETTINGS_CACHE_TTL:
        try:
            _settings_cache = _fetch_all_settings()
            _settings_cache_ts = now
        except Exception as e:
            print('⚠️ خطا در رفرش کش تنظیمات (با آخرین مقادیر کش‌شده ادامه داده می‌شه):', e)
    return _settings_cache.get(key, default)


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
]

# دستورهای اسلش معادل دکمه‌های منو، به COMMAND_TO_ACTION_KEY (پایین‌تر، کنار
# main_menu) نگاشت می‌شن.


def set_bot_commands():
    try:
        res = SESSION.post(BASE_URL + '/setMyCommands', json={'commands': BOT_COMMANDS}, timeout=10)
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


def answer_callback(callback_query_id):
    try:
        SESSION.post(BASE_URL + '/answerCallbackQuery', json={'callback_query_id': callback_query_id}, timeout=5)
    except Exception:
        pass


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


def build_config_note(chat_id, username, price):
    """متن یادداشتی که رو هر کانفیگ (تو پنل su.randomatic.ir) ثبت می‌شه:
    تاریخ شمسی و ساعت دقیق (با ثانیه) ساخت به وقت ایران، آیدی عددی و
    یوزرنیم خریدار، و مبلغی که برای این کانفیگ پرداخت کرده."""
    dt = now_iran()
    jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
    jalali_date = f'{jy:04d}/{jm:02d}/{jd:02d}'
    time_str = dt.strftime('%H:%M:%S')
    uname = ('@' + username) if username else 'بدون یوزرنیم'
    return (
        f'تاریخ ساخت: {jalali_date} | '
        f'ساعت: {time_str} | '
        f'آیدی عددی: {chat_id} | '
        f'یوزرنیم: {uname} | '
        f'مبلغ پرداختی: {price:,} تومان'
    )


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
        return UI_TEXT['en'].get('btn_' + key, default)
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
    '📶 حجم: <b>0.1</b> گیگابایت\n'
    '⏳ مدت اعتبار: <b>1</b> روز\n{divider}\n'
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
                {'text': '➖', 'callback_data': 'qty_gb_dec'},
                {'text': '📶 ' + str(gb) + ' ' + u(chat_id, 'unit_gb'), 'callback_data': 'qty_noop'},
                {'text': '➕', 'callback_data': 'qty_gb_inc'},
            ],
            [
                {'text': '➖', 'callback_data': 'qty_days_dec'},
                {'text': '⏳ ' + str(days) + ' ' + u(chat_id, 'unit_day'), 'callback_data': 'qty_noop'},
                {'text': '➕', 'callback_data': 'qty_days_inc'},
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
        send_message(chat_id, DISABLED_TEXT)
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
    unit_suffix = (' Toman/GB' if get_user_lang(chat_id) == 'en' else ' تومان/گیگ')
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


def action_topup_menu(chat_id):
    if not is_feature_enabled('topup'):
        send_message(chat_id, DISABLED_TEXT)
        return
    user_steps[str(chat_id)] = {'step': 'ask_topup_amount'}
    text = (u(chat_id, 'topup_prompt', min_topup=f'{get_min_topup():,}') if get_user_lang(chat_id) == 'en'
            else get_bot_text_fmt('topup_prompt', DEFAULT_TOPUP_PROMPT, min_topup=f'{get_min_topup():,}'))
    send_message(chat_id, text, reply_markup=cancel_kb(chat_id))


def action_trial(chat_id):
    if not is_feature_enabled('trial'):
        send_message(chat_id, DISABLED_TEXT)
        return
    lang = get_user_lang(chat_id)
    if check_free_trial(chat_id) > 0:
        send_message(chat_id, u(chat_id, 'trial_used') if lang == 'en' else get_bot_text('trial_used', DEFAULT_TRIAL_USED))
        return
    send_message(chat_id, u(chat_id, 'trial_building') if lang == 'en' else get_bot_text('trial_building', DEFAULT_TRIAL_BUILDING))
    res = make_config(0.1, 'تست رایگان', 1)
    if res['success'] and res['sub_url']:
        set_free_trial(chat_id)
        save_user_config(chat_id, res['sub_url'], res['config_id'], 0.1, 'تست رایگان', 1, 0)
        set_config_note(res['config_id'], build_config_note(chat_id, get_username_db(chat_id), 0))
        if lang == 'en':
            trial_text = u(chat_id, 'trial_ready', sub_url=str(res['sub_url']), divider=DIVIDER)
        else:
            trial_text = get_bot_text_fmt(
                'trial_ready', DEFAULT_TRIAL_READY,
                sub_url=str(res['sub_url']), divider=DIVIDER,
            )
        send_message(chat_id, trial_text)
    else:
        # اگه پنل به‌خاطر «قبلاً تست رایگان گرفته» رد کرده باشه (مثلاً چون این
        # کاربر رو از یه شناسه‌ی دیگه/قبلی شناسایی کرده)، به‌جای پیام گنگِ
        # «خطا در ارتباط با سرور»، پیام درست و واضح رو نشون می‌دیم و محلی هم
        # ثبتش می‌کنیم تا دفعه‌ی بعد اصلاً به پنل درخواست نزنه.
        err_blob = (str(res.get('error_code') or '') + ' ' + str(res.get('error') or '')).lower()
        if any(k in err_blob for k in ('trial', 'already', 'duplicate', 'تکراری', 'قبلا')):
            set_free_trial(chat_id)
            send_message(chat_id, u(chat_id, 'trial_used_on_panel'))
        else:
            send_message(chat_id, u(chat_id, 'trial_error') if lang == 'en' else get_bot_text('trial_error', DEFAULT_TRIAL_ERROR))


# لینک‌های دانلود برنامه‌ی V2Pro (با متغیر محیطی هم قابل تغییرن)
APP_DOWNLOAD_LINKS = [
    ('android', os.getenv('APP_LINK_ANDROID', 'https://play.google.com/store/apps/details?id=com.v2pro.client')),
    ('ios', os.getenv('APP_LINK_IOS', 'https://apps.apple.com/us/app/v2pro/id6801607092')),
    ('windows', os.getenv('APP_LINK_WINDOWS', 'https://su.randomatic.ir/v2pro/1.1.2/V2Pro-Setup-x64.exe')),
    ('mac', os.getenv('APP_LINK_MAC', 'https://su.randomatic.ir/v2pro/1.1.2/v2pro-macos-universal.zip')),
    ('linux', os.getenv('APP_LINK_LINUX', 'https://su.randomatic.ir/v2pro/1.1.2/v2pro-linux-x64.tar.gz')),
]


def _reseller_gen_key_secret():
    api_key = 'rk_' + secrets.token_hex(10)
    api_secret = secrets.token_urlsafe(32)
    secret_hash = hashlib.sha256(api_secret.encode('utf-8')).hexdigest()
    return api_key, api_secret, secret_hash


def action_reseller_menu(chat_id):
    """صفحه‌ی فروشندگی: اگه هنوز فروشنده نشده، پیشنهاد فعال‌سازی؛ وگرنه
    پنل کوچیکش (موجودی استخر، کلید API، افزایش استخر)."""
    row = get_reseller(chat_id)
    if not row:
        activation_price = round(RESELLER_MIN_GB * RESELLER_PRICE_PER_GB)
        send_message(
            chat_id,
            u(chat_id, 'reseller_intro', divider=DIVIDER, price_per_gb=f'{RESELLER_PRICE_PER_GB:,}',
              min_gb=RESELLER_MIN_GB, activation_price=f'{activation_price:,}'),
            reply_markup={'inline_keyboard': [[
                {'text': u(chat_id, 'btn_reseller_activate'), 'callback_data': 'reseller_activate'}
            ]]}
        )
        return
    _, api_key, _secret_hash, gb_balance, price_per_gb, status, _created = row
    status_label = 'فعال ✅' if status == 'active' else 'مسدود ⛔️'
    send_message(
        chat_id,
        u(chat_id, 'reseller_dashboard', divider=DIVIDER, gb_balance=('%g' % gb_balance),
          price_per_gb=f'{price_per_gb:,}', status=status_label, api_key=api_key,
          panel_url=RESELLER_PANEL_URL),
        reply_markup={'inline_keyboard': [
            [{'text': u(chat_id, 'btn_reseller_topup'), 'callback_data': 'reseller_topup'}],
            [{'text': u(chat_id, 'btn_reseller_regen'), 'callback_data': 'reseller_regen_ask'}],
        ]}
    )


def action_guide(chat_id):
    """دکمه‌ی «دانلود برنامه»: برای هر سیستم‌عامل یه دکمه‌ی لینک‌دار می‌فرسته. اگه
    پیام‌رسان دکمه‌ی url رو قبول نکرد، همون لینک‌ها به‌صورت متن ساده فرستاده می‌شن."""
    rows = [[{'text': u(chat_id, 'plat_' + key), 'url': url}] for key, url in APP_DOWNLOAD_LINKS]
    res = send_message(chat_id, u(chat_id, 'guide_text', divider=DIVIDER), reply_markup={'inline_keyboard': rows})
    if not (isinstance(res, dict) and res.get('ok')):
        lines = [u(chat_id, 'guide_fallback_title'), DIVIDER]
        for key, url in APP_DOWNLOAD_LINKS:
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
        send_message(chat_id, DISABLED_TEXT)
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
        send_message(chat_id, DISABLED_TEXT)
        return
    user_steps[str(chat_id)] = {'step': 'support_message'}
    send_message(chat_id, u(chat_id, 'support_prompt') if get_user_lang(chat_id) == 'en'
                 else get_bot_text('support_prompt', DEFAULT_SUPPORT_PROMPT), reply_markup=cancel_kb(chat_id))


def action_recent_orders(chat_id):
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


# هر آیتم: (کلید داخلی ثابت, متن پیش‌فرض دکمه, تابع اجراکننده)
BUTTON_ACTIONS = [
    ('recentorders', '🧾 سفارشات اخیر من', action_recent_orders),
    ('buy', '🛍 خرید کانفیگ', action_buy_menu),
    ('trial', '🧪 تست رایگان', action_trial),
    ('topup', '💠 شارژ کیف پول', action_topup_menu),
    ('account', '👤 حساب من', action_account),
    ('myconfigs', '🗂 کانفیگ‌های من', action_my_configs),
    ('delete', '🗑 حذف کانفیگ', action_delete_config_start),
    ('support', '🎧 پشتیبانی', action_support_start),
    ('guide', '📲 اپ مخصوص کانفیگ‌ها', action_guide),
    ('language', '🌐 تغییر زبان', action_language_menu),
    ('reseller', '🧑‍💼 فروشنده شو', action_reseller_menu),
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
    '/recentorders': 'recentorders',
    '/language': 'language',
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
        en_label = UI_TEXT['en'].get('btn_' + key)
        if en_label:
            mapping[en_label] = key
    return mapping


MAIN_MENU_DEFAULT_ORDER = [key for key, _label, _fn in BUTTON_ACTIONS]


def _chunk_pairs(items):
    return [items[i:i + 2] for i in range(0, len(items), 2)]


def main_menu(chat_id, note=None):
    wallet = get_wallet_db(chat_id)
    labels = {key: get_button_label_for(chat_id, key, default_label) for key, default_label, _fn in BUTTON_ACTIONS}
    order = get_ordered_keys('menu_order_main', MAIN_MENU_DEFAULT_ORDER)
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
            send_message(chat_id, '⌨️', reply_markup={'remove_keyboard': True})
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
            {'text': '✍️ پاسخ', 'callback_data': 'reply_ticket_' + str(tid)},
            {'text': '🔒 بستن', 'callback_data': 'close_ticket_' + str(tid)}
        ]]
    }
    txt = (
        '🎫 <b>تیکت جدید #' + str(tid) + '</b>\n' + DIVIDER + '\n'
        '👤 کاربر: <code>' + str(user_id) + '</code>\n\n' + str(message)
    )
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


init_db()
network_diagnostic()
delete_webhook()
set_bot_commands()
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
                activation_price = round(RESELLER_MIN_GB * RESELLER_PRICE_PER_GB)
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
                    api_key, api_secret, secret_hash = _reseller_gen_key_secret()
                    update_wallet_db(chat_id, -activation_price)
                    create_reseller(chat_id, api_key, secret_hash, RESELLER_MIN_GB)
                    try:
                        conn = get_conn(); c = conn.cursor()
                        c.execute('INSERT INTO reseller_pool_log (user_id, gb, price, created_at) VALUES (?, ?, ?, ?)',
                                   (chat_id, RESELLER_MIN_GB, activation_price, datetime.now().isoformat()))
                        conn.commit(); conn.close()
                    except Exception as log_err:
                        print('⚠️ ثبت لاگ فعال‌سازی فروشندگی انجام نشد:', log_err)
                    send_message(
                        chat_id,
                        u(chat_id, 'reseller_activated', divider=DIVIDER, gb=RESELLER_MIN_GB,
                          api_key=api_key, api_secret=api_secret, panel_url=RESELLER_PANEL_URL)
                    )

        elif data == 'reseller_topup':
            if not get_reseller(chat_id):
                action_reseller_menu(chat_id)
            else:
                user_steps[str(chat_id)] = {'step': 'reseller_topup_gb'}
                send_message(chat_id, u(chat_id, 'reseller_topup_prompt'), reply_markup=cancel_kb(chat_id))

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

        elif data == 'reseller_regen_ask':
            if not get_reseller(chat_id):
                action_reseller_menu(chat_id)
            else:
                send_message(
                    chat_id, u(chat_id, 'reseller_regen_warning'),
                    reply_markup={'inline_keyboard': [[
                        {'text': u(chat_id, 'btn_confirm_pay'), 'callback_data': 'reseller_regen_yes'},
                        {'text': u(chat_id, 'btn_cancel'), 'callback_data': 'menu'},
                    ]]}
                )

        elif data == 'reseller_regen_yes':
            if get_reseller(chat_id):
                api_key, api_secret, secret_hash = _reseller_gen_key_secret()
                regenerate_reseller_secret_db(chat_id, api_key, secret_hash)
                send_message(chat_id, u(chat_id, 'reseller_regen_done', divider=DIVIDER, api_key=api_key, api_secret=api_secret))
            else:
                action_reseller_menu(chat_id)

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
                user_steps[str(chat_id)] = {'step': 'pick_quantity', 'type': ctype, 'gb': 1, 'days': 30}
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
                '✍️ پاسخ تیکت #' + str(tid) + ' را ارسال کنید:',
                reply_markup={'inline_keyboard': [[{'text': '❌ انصراف', 'callback_data': 'menu'}]]}
            )

        elif data.startswith('close_ticket_'):
            tid = int(data.split('_')[2])
            update_ticket_status(tid, 'closed')
            send_message(chat_id, '🔒 تیکت #' + str(tid) + ' بسته شد.')

        elif data.startswith('topup_acc_'):
            req_id = int(data.split('_')[2])
            req = get_topup_request(req_id)
            if req and req[3] == 'pending':
                multiplier = get_topup_multiplier()
                credited = int(round(req[2] * multiplier))
                update_topup_status(req_id, 'approved')
                update_wallet_db(req[1], credited)
                if multiplier != 1:
                    mult_str = ('%g' % multiplier)
                    send_message(
                        req[1],
                        '✅ کیف پول شما به مبلغ <b>' + f'{credited:,}' + '</b> تومان شارژ شد ' +
                        '(واریزی ' + f'{req[2]:,}' + ' تومان × ضریب ' + mult_str + ').'
                    )
                else:
                    send_message(req[1], '✅ کیف پول شما به مبلغ <b>' + f'{credited:,}' + '</b> تومان شارژ شد.')
                send_message(ADMIN_ID, '✅ درخواست شارژ #' + str(req_id) + ' تایید شد — ' + f'{credited:,}' + ' تومان به کیف پول کاربر اضافه شد.')
            else:
                send_message(ADMIN_ID, '⚠️ این درخواست قبلاً بررسی شده یا وجود ندارد.')

        elif data.startswith('topup_rej_'):
            req_id = int(data.split('_')[2])
            req = get_topup_request(req_id)
            if req and req[3] == 'pending':
                update_topup_status(req_id, 'rejected')
                send_message(req[1], '❌ رسید واریز شما رد شد. لطفاً با پشتیبانی در ارتباط باشید.')
                send_message(ADMIN_ID, '❌ درخواست #' + str(req_id) + ' رد شد.')
            else:
                send_message(ADMIN_ID, '⚠️ این درخواست قبلاً بررسی شده یا وجود ندارد.')

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

        if text == '/start' or text.startswith('/start '):
            add_user(chat_id)
            user_steps[str(chat_id)] = {}
            main_menu(chat_id)

        elif matched_action_key:
            get_action_handlers()[matched_action_key](chat_id)

        # ---------------- step-based flows ----------------

        elif step.get('step') == 'ask_label':
            label = text.strip() if text.strip() else get_next_user_label()
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

        elif step.get('step') == 'reseller_topup_gb':
            try:
                gb = float(text)
                if gb <= 0:
                    send_message(chat_id, u(chat_id, 'ext_number_error'))
                else:
                    row = get_reseller(chat_id)
                    price_per_gb = row[4] if row else RESELLER_PRICE_PER_GB
                    price = round(gb * price_per_gb)
                    user_steps[str(chat_id)] = {'step': 'reseller_topup_confirm', 'gb': gb, 'price': price}
                    send_message(
                        chat_id,
                        u(chat_id, 'reseller_topup_confirm_title', gb=('%g' % gb), price=price),
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
                if extra_gb <= 0:
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
                if extra_days <= 0:
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
            new_label = text.strip()
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
                        refund = int(remaining_value / 2)
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
                if amount < get_min_topup():
                    send_message(chat_id, u(chat_id, 'topup_min_error', min_topup=get_min_topup()))
                else:
                    user_steps[str(chat_id)] = {'step': 'waiting_receipt', 'amount': amount}
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
            except ValueError:
                send_message(chat_id, u(chat_id, 'topup_amount_error'))

        elif step.get('step') == 'waiting_receipt' and 'photo' in message:
            photo_id = message['photo'][-1]['file_id']
            amount = step.get('amount')
            req_id = create_topup_request(chat_id, amount)

            send_message(chat_id, u(chat_id, 'topup_receipt_ok') if get_user_lang(chat_id) == 'en'
                          else get_bot_text('topup_receipt_ok', DEFAULT_TOPUP_RECEIPT_OK))
            user_steps[str(chat_id)] = {}
            # پیام «رسید دریافت شد» همین بالا رفت؛ دیگه نیازی به تکرار منو نیست.

            admin_caption = (
                '💳 <b>درخواست شارژ کیف پول</b>\n' + DIVIDER + '\n'
                '👤 کاربر: <code>' + str(chat_id) + '</code>\n'
                '💵 مبلغ: <b>' + f'{amount:,}' + '</b> تومان\n'
                '🎫 شناسه درخواست: <b>' + str(req_id) + '</b>'
            )
            admin_kb = {
                'inline_keyboard': [[
                    {'text': '✅ تایید', 'callback_data': 'topup_acc_' + str(req_id)},
                    {'text': '❌ رد کردن', 'callback_data': 'topup_rej_' + str(req_id)}
                ]]
            }
            send_photo(ADMIN_ID, photo_id, caption=admin_caption, reply_markup=admin_kb)

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
                send_message(chat_id, '✅ پاسخ برای کاربر ارسال شد.')
            else:
                send_message(chat_id, '⚠️ تیکت یافت نشد.')
            user_steps[str(chat_id)] = {}


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

    lock = get_chat_lock(chat_id) if chat_id is not None else None
    try:
        if lock:
            with lock:
                process_update(update)
        else:
            process_update(update)
    except Exception as e:
        print('⚠️ خطا در پردازش آپدیت:', e)


while True:
    try:
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
            time.sleep(1)

    except Exception as loop_error:
        print('⚠️ خطای غیرمنتظره در حلقه اصلی:', loop_error)
        reset_conn()
        time.sleep(2)
