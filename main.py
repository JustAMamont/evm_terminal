import sys
import os
import subprocess
import shutil
from pathlib import Path


if os.name == "posix":
    os.environ.setdefault("LANG", "en_US.UTF-8")
    os.environ.setdefault("LC_ALL", "en_US.UTF-8")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

def set_terminal_title(title: str):
    if sys.platform == "win32":
        os.system(f"title {title}")
    else:
        sys.stdout.write(f"\x1b]2;{title}\x07")
        sys.stdout.flush()

try:
    import certifi
    os.environ['SSL_CERT_FILE'] = certifi.where()
    os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
except ImportError:
    print("Ошибка импорта certifi")

def set_high_priority():
    try:
        import psutil
        p = psutil.Process(os.getpid())
        if sys.platform == "win32":
            p.nice(psutil.HIGH_PRIORITY_CLASS)
        else:
            try:
                p.nice(-10)
            except psutil.AccessDenied:
                print("Ошибка в повышении приоритета приложения")
    except ImportError:
        print("Ошибка импорта psutil")
    except Exception:
        traceback.print_exc()

def ensure_terminal_linux():
    if sys.platform == "win32" or sys.platform == "darwin": return
    if os.environ.get("DEXBOT_IN_TERMINAL") == "1": return
    if not sys.stdout.isatty():
        exe_path = os.path.abspath(sys.executable)
        exe_dir = os.path.dirname(exe_path)

        bash_cmd = (f"echo -ne '\\033]2;EVM_TRADER\\007'; "
                    f"cd '{exe_dir}'; "
                    f"'{exe_path}'; "
                    f"echo -e '\\n\\nПрограмма завершила работу. Нажмите Enter для выхода.'; read line")

        terminals = [
            ("gnome-terminal", ["--", "bash", "-c", bash_cmd]),
            ("konsole", ["-e", "bash", "-c", bash_cmd]),
            ("xfce4-terminal", ["-x", "bash", "-c", bash_cmd]),
            ("terminology", ["-e", "bash", "-c", bash_cmd]),
            ("lxterminal", ["-e", "bash", "-c", bash_cmd]),
            ("xterm", ["-e", "bash", "-c", bash_cmd]),
            ("mate-terminal", ["--", "bash", "-c", bash_cmd]),
            ("tilix", ["-e", "bash", "-c", bash_cmd]),
        ]

        env = os.environ.copy()
        env["DEXBOT_IN_TERMINAL"] = "1"
        
        vars_to_kill = ["PYTHONPATH", "PYTHONHOME"]
        for var in vars_to_kill:
            if var in env:
                del env[var]

        for term_cmd, term_args in terminals:
            if shutil.which(term_cmd):
                try:
                    subprocess.Popen([term_cmd] + term_args, cwd=exe_dir, env=env)
                    sys.exit(0) 
                except Exception: continue

def ensure_terminal_mac():
    if sys.platform != "darwin": return
    if os.environ.get("DEXBOT_IN_TERMINAL") == "1": return
    if not sys.stdout.isatty():
        exe_path = os.path.abspath(sys.executable)
        exe_dir = os.path.dirname(exe_path)

        cmd_bash = (f"echo -ne '\\033]2;EVM_TRADER\\007'; "
               f"export DEXBOT_IN_TERMINAL=1; "
               f"cd \\\"{exe_dir}\\\"; \\\"{exe_path}\\\"; read -p 'Программа завершена. Нажмите Enter для выхода...' ")

        applescript = f'tell application "Terminal" to do script "{cmd_bash}" activate'
        
        try:
            subprocess.run(["osascript", "-e", applescript])
            sys.exit(0)
        except Exception: pass

ensure_terminal_linux()
ensure_terminal_mac()

if getattr(sys, 'frozen', False):
    application_path = Path(sys.executable).parent.resolve() 
else:
    application_path = Path(__file__).parent.resolve()
os.chdir(application_path)

if sys.platform != "win32":
    try:
        import uvloop
    except ImportError:
        uvloop = None
else:
    uvloop = None


if __name__ == "__main__":
    set_terminal_title("EVM_TRADER")
    set_high_priority()

    if uvloop:
        uvloop.install()
    
    try:
        import bot.bot
        bot.bot.run()
    except KeyboardInterrupt:
        print("\nЗапуск отменен.")
        sys.exit(0)
    except Exception as e:
        print(f"Критическая ошибка инициализации: {e}")
        import traceback
        traceback.print_exc()
        input("Нажмите Enter для выхода...")