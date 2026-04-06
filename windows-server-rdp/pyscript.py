# python pyscript.py --install --reg-path "HKLM\SYSTEM\CurrentControlSet\Control\Terminal Server\RCM\GracePeriod"
import argparse
import ctypes
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(r"C:\reg_cleanup")
LOG_FILE = BASE_DIR / "log.txt"
STATE_FILE = BASE_DIR / "state.json"
CONFIG_FILE = BASE_DIR / "config.json"
SCRIPT_NAME = "pyscript.py"

TASK_BOOT_NAME = "JUCA_RegCleanup_SYSTEM"
TASK_DAILY_NAME = "JUCA_RegCleanup_SYSTEM_DAILY"

DEFAULT_REG_PATH = r"HKLM\SYSTEM\CurrentControlSet\Control\Terminal Server\RCM\GracePeriod"


# -----------------------------
# Utils
# -----------------------------

def ensure_base_dir():
    BASE_DIR.mkdir(parents=True, exist_ok=True)


def now_str():
    return dt.datetime.now().strftime("%d/%m/%Y %H:%M")


def log_block(start_msg=None, end_msg=None, status=None):
    ensure_base_dir()

    lines = ["----------"]

    if start_msg:
        lines.append(f"[Start] {start_msg} em {now_str()}")

    if end_msg:
        if status:
            lines.append(f"[End] {end_msg} em {now_str()} // Status: {status}")
        else:
            lines.append(f"[End] {end_msg} em {now_str()}")

    lines.append("----------")

    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def run_cmd(cmd: list[str]):
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_json(path, default=None):
    if not path.exists():
        return default or {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# -----------------------------
# Config
# -----------------------------

def save_config(reg_path):
    save_json(CONFIG_FILE, {"registry_path": reg_path})


def load_config():
    cfg = load_json(CONFIG_FILE, {})
    return cfg.get("registry_path", DEFAULT_REG_PATH)


# -----------------------------
# Registry
# -----------------------------

def registry_exists(reg_path):
    return run_cmd(["reg", "query", reg_path]).returncode == 0


def delete_registry(reg_path):
    res = run_cmd(["reg", "delete", reg_path, "/f"])
    return res.returncode, res.stdout.strip(), res.stderr.strip()


# -----------------------------
# State
# -----------------------------

def should_run():
    state = load_json(STATE_FILE, {})
    last = state.get("last_success")

    if not last:
        return True

    try:
        last_dt = dt.datetime.fromisoformat(last)
    except:
        return True

    return (dt.datetime.now() - last_dt).days >= 7


def update_state(success, detail=""):
    state = load_json(STATE_FILE, {})
    state["last_attempt"] = dt.datetime.now().isoformat()

    if success:
        state["last_success"] = dt.datetime.now().isoformat()

    state["detail"] = detail

    save_json(STATE_FILE, state)


# -----------------------------
# Scheduler
# -----------------------------

def create_tasks():
    python_exe = sys.executable
    script = BASE_DIR / SCRIPT_NAME

    command = f'"{python_exe}" "{script}" --run'

    boot = [
        "schtasks",
        "/Create",
        "/TN", TASK_BOOT_NAME,
        "/TR", command,
        "/SC", "ONSTART",
        "/RU", "SYSTEM",
        "/RL", "HIGHEST",
        "/F"
    ]

    daily = [
        "schtasks",
        "/Create",
        "/TN", TASK_DAILY_NAME,
        "/TR", command,
        "/SC", "DAILY",
        "/ST", "03:00",
        "/RU", "SYSTEM",
        "/RL", "HIGHEST",
        "/F"
    ]

    r1 = run_cmd(boot)
    if r1.returncode != 0:
        raise RuntimeError(r1.stderr or r1.stdout)

    r2 = run_cmd(daily)
    if r2.returncode != 0:
        raise RuntimeError(r2.stderr or r2.stdout)


def delete_tasks():
    for t in [TASK_BOOT_NAME, TASK_DAILY_NAME]:
        run_cmd(["schtasks", "/Delete", "/TN", t, "/F"])


# -----------------------------
# Core
# -----------------------------

def install(reg_path):
    if not is_admin():
        print("Execute como ADMIN.")
        sys.exit(1)

    ensure_base_dir()

    src = Path(__file__).resolve()
    dst = BASE_DIR / SCRIPT_NAME

    if src != dst:
        shutil.copy2(src, dst)

    save_config(reg_path)
    create_tasks()

    print("OK instalado")


def run_cleanup():
    ensure_base_dir()

    if not should_run():
        return

    reg_path = load_config()

    log_block(start_msg="Iniciando remoção")

    try:
        if not registry_exists(reg_path):
            update_state(True, "não existia")
            log_block(end_msg="Finalizado", status="OK - NÃO EXISTIA")
            return

        code, out, err = delete_registry(reg_path)

        if code == 0:
            update_state(True, "removido")
            log_block(end_msg="Finalizado", status="SUCESSO")
        else:
            detail = err or out
            update_state(False, detail)
            log_block(end_msg="Finalizado", status=f"ERRO - {detail}")

    except Exception as e:
        update_state(False, str(e))
        log_block(end_msg="Finalizado", status=f"ERRO - {e}")


def uninstall():
    if not is_admin():
        print("Execute como ADMIN.")
        sys.exit(1)

    delete_tasks()
    print("Tasks removidas")


# -----------------------------
# CLI
# -----------------------------

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--install", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--reg-path", type=str)

    args = parser.parse_args()
    reg_path = args.reg_path or DEFAULT_REG_PATH

    if args.install:
        install(reg_path)
    elif args.run:
        run_cleanup()
    elif args.uninstall:
        uninstall()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
