import psutil
import time
from colorama import Fore, Style, init

init(autoreset=True)

print(f"\n{Fore.CYAN}🔎 SEARCHING FOR TRADING BOT...{Style.RESET_ALL}")

found = False
for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
    try:
        cmd = proc.info['cmdline']
        if cmd and 'master_bot.py' in ' '.join(cmd):
            found = True
            pid = proc.info['pid']
            uptime_seconds = time.time() - proc.info['create_time']
            hours = int(uptime_seconds // 3600)
            minutes = int((uptime_seconds % 3600) // 60)

            print(f"{Fore.GREEN}✅ BOT IS RUNNING!{Style.RESET_ALL}")
            print(f"   • PID:      {pid}")
            print(f"   • Uptime:   {hours} hours, {minutes} minutes")
            print(f"   • Status:   ACTIVE")
            print(f"   • Threads:  {proc.num_threads()} (Look for 4: Main, Swing, Scalp, News)")
            break
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

if not found:
    print(f"{Fore.RED}❌ BOT IS OFFLINE!{Style.RESET_ALL}")
    print(f"   Run '~/run_bot.sh' to start it.")

print()
