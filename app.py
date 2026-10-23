import os
import subprocess
import sys
import time

# این فایل بات و پنل ادمین رو با هم، توی یه سرویس، اجرا می‌کنه و اگه یکی‌شون بمیره دوباره بالا میاره.
# Render > Start Command:   python app.py
# پنل (Flask) صاحب PORT هست و پینگ ۵ دقیقه‌ای خودش کل سرویس رو بیدار نگه می‌داره؛
# برای همین به بات DISABLE_HEALTH_SERVER=1 داده می‌شه تا پورت رو از پنل نگیره.

HERE = os.path.dirname(os.path.abspath(__file__))
# هر اسمی که برای فایل بات گذاشتی؛ اولین فایلی که وجود داشته باشه اجرا می‌شه
BOT_CANDIDATES = ("bot-9-donito.py", "bot-9.py", "bot.py")
PANEL_FILE = "web_panel.py"


def find_bot():
    for name in BOT_CANDIDATES:
        if os.path.exists(os.path.join(HERE, name)):
            return name
    raise SystemExit("فایل بات پیدا نشد: " + ", ".join(BOT_CANDIDATES))


def start_proc(filename, extra_env=None):
    print(f"در حال اجرای {filename} ...", flush=True)
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    env.update(extra_env or {})
    return subprocess.Popen([sys.executable, os.path.join(HERE, filename)], cwd=HERE, env=env)


def main():
    jobs = [
        (PANEL_FILE, {}),                                        # پنل اول بالا میاد و پورت رو می‌گیره
        (find_bot(), {"DISABLE_HEALTH_SERVER": "1"}),
    ]
    processes = []
    started = []
    for filename, env in jobs:
        processes.append(start_proc(filename, env))
        started.append(time.time())
        time.sleep(3)

    try:
        while True:
            for i, p in enumerate(processes):
                if p.poll() is not None:
                    filename, env = jobs[i]
                    wait = max(0, 10 - (time.time() - started[i]))    # حداقل ۱۰ ثانیه بین ری‌استارت‌ها
                    print(f"{filename} متوقف شد (کد خروج {p.returncode})، {wait:.0f} ثانیه دیگه ری‌استارت می‌شود...", flush=True)
                    time.sleep(wait)
                    processes[i] = start_proc(filename, env)
                    started[i] = time.time()
            time.sleep(3)
    except KeyboardInterrupt:
        for p in processes:
            p.terminate()


if __name__ == "__main__":
    main()
