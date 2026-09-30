# run_all.py
import subprocess
import sys
import os
import threading
import time
import signal

# اسم فایل‌ها (اگه تو پوشه‌ی دیگه‌ای هستن مسیر کامل بده)
BOT_FILE = "bot-9.py"
PANEL_FILE = "web_panel.py"

# پورت پنل (اگه تو web_panel.py تغییر دادی، اینجا هم عوض کن)
PANEL_PORT = os.getenv("PORT", "8080")

processes = []
stop_event = threading.Event()


def stream_output(proc, prefix, color):
    """خروجی هر پروسه رو با پیشوند رنگی تو ترمینال چاپ می‌کنه."""
    try:
        for line in iter(proc.stdout.readline, ''):
            if not line:
                break
            print(f"{color}[{prefix}]{RESET} {line.rstrip()}", flush=True)
    except Exception:
        pass


# رنگ‌های ANSI برای تفکیک خروجی دو پروسه
GREEN = "\033[92m"
BLUE = "\033[94m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def start_process(name, script, color):
    if not os.path.exists(script):
        print(f"{RED}❌ فایل {script} پیدا نشد!{RESET}")
        sys.exit(1)

    print(f"{color}▶️  در حال اجرای {name} ({script}) ...{RESET}")
    # bufsize=1 و universal_newlines=True برای اینکه خط‌به‌خط خروجی بگیریم
    proc = subprocess.Popen(
        [sys.executable, "-u", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        universal_newlines=True,
    )
    processes.append((name, proc))

    t = threading.Thread(target=stream_output, args=(proc, name, color), daemon=True)
    t.start()
    return proc


def shutdown(signum=None, frame=None):
    if stop_event.is_set():
        return
    stop_event.set()
    print(f"\n{YELLOW}⏹  در حال خاموش کردن همه‌ی سرویس‌ها...{RESET}")
    for name, proc in processes:
        if proc.poll() is None:
            try:
                proc.terminate()
                print(f"{YELLOW}   → {name} خاتمه یافت{RESET}")
            except Exception as e:
                print(f"{RED}   → خطا در بستن {name}: {e}{RESET}")
    # فرصت کوتاه برای خروج تمیز
    time.sleep(2)
    for name, proc in processes:
        if proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
    print(f"{GREEN}✅ همه‌ی سرویس‌ها متوقف شدند.{RESET}")
    sys.exit(0)


signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)


if __name__ == "__main__":
    print(f"{GREEN}{'='*55}{RESET}")
    print(f"{GREEN}🚀 اجرای همزمان ربات تلگرام و پنل وب{RESET}")
    print(f"{GREEN}{'='*55}{RESET}")
    print(f"   🤖 ربات    : {BOT_FILE}")
    print(f"   🌐 پنل وب : {PANEL_FILE}  (پورت {PANEL_PORT})")
    print(f"{GREEN}{'='*55}{RESET}\n")

    start_process("BOT  ", BOT_FILE, GREEN)
    time.sleep(1.5)  # مکث کوتاه تا ربات اول بالا بیاد
    start_process("PANEL", PANEL_FILE, BLUE)

    print(f"\n{GREEN}✅ هر دو سرویس اجرا شدند. برای توقف Ctrl+C بزنید.{RESET}\n")

    # حلقه‌ی نگهبان: اگه یکی از پروسه‌ها کرش کرد، همه رو ببند
    try:
        while not stop_event.is_set():
            time.sleep(2)
            for name, proc in processes:
                code = proc.poll()
                if code is not None:
                    print(f"{RED}⚠️  سرویس {name} با کد {code} متوقف شد! در حال بستن بقیه...{RESET}")
                    shutdown()
    except KeyboardInterrupt:
        shutdown()
