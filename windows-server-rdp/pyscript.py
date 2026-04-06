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
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run_cmd(cmd: list[str]):
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )


def save_json(path: Path, data: dict):
    ensure_base_dir()
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_json(path: Path, default=None):
    if not path.exists():
        return default or {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_config(reg_path: str):
    save_json(CONFIG_FILE, {"registry_path": reg_path})


def load_config():
    cfg = load_json(CONFIG_FILE, {})
    return cfg.get("registry_path", DEFAULT_REG_PATH)


def registry_exists(reg_path: str):
    return run_cmd(["reg", "query", reg_path]).returncode == 0


def delete_registry(reg_path: str):
    res = run_cmd(["reg", "delete", reg_path, "/f"])
    return res.returncode, (res.stdout or "").strip(), (res.stderr or "").strip()


def restart_termservice():
    stop_res = run_cmd(["net", "stop", "TermService"])
    start_res = run_cmd(["net", "start", "TermService"])

    ok = stop_res.returncode == 0 and start_res.returncode == 0
    detail = (
        f"STOP[{stop_res.returncode}]: {(stop_res.stdout or stop_res.stderr or '').strip()} | "
        f"START[{start_res.returncode}]: {(start_res.stdout or start_res.stderr or '').strip()}"
    )
    return ok, detail


def should_run():
    state = load_json(STATE_FILE, {})
    last = state.get("last_success")

    if not last:
        return True, True

    try:
        last_dt = dt.datetime.fromisoformat(last)
    except Exception:
        return True, False

    return (dt.datetime.now() - last_dt).days >= 7, False


def update_state(success: bool, detail: str = ""):
    state = load_json(STATE_FILE, {})
    state["last_attempt"] = dt.datetime.now().isoformat()

    if success:
        state["last_success"] = dt.datetime.now().isoformat()

    state["detail"] = detail
    save_json(STATE_FILE, state)


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
        raise RuntimeError(r1.stderr or r1.stdout or "Erro ao criar task ONSTART")

    r2 = run_cmd(daily)
    if r2.returncode != 0:
        raise RuntimeError(r2.stderr or r2.stdout or "Erro ao criar task DAILY")


def delete_tasks():
    for t in [TASK_BOOT_NAME, TASK_DAILY_NAME]:
        run_cmd(["schtasks", "/Delete", "/TN", t, "/F"])


def install(reg_path: str):
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
    print(f"Pasta: {BASE_DIR}")
    print(f"Registro: {reg_path}")


def run_cleanup():
    ensure_base_dir()

    should_execute, is_first_run = should_run()
    if not should_execute:
        return

    reg_path = load_config()

    if is_first_run:
        log_block(start_msg="Primeira execução da rotina de remoção do registro")
    else:
        log_block(start_msg="Iniciando a remoção do registro")

    try:
        if not registry_exists(reg_path):
            update_state(True, "Chave já não existia")
            log_block(
                end_msg="Finalização da remoção do registro",
                status="OK - CHAVE NÃO EXISTIA"
            )
            return

        code, out, err = delete_registry(reg_path)

        if code != 0:
            detail = err or out or "Erro ao remover chave"
            update_state(False, detail)
            log_block(
                end_msg="Finalização da remoção do registro",
                status=f"ERRO - {detail}"
            )
            return

        svc_ok, svc_detail = restart_termservice()

        if svc_ok:
            update_state(True, f"Registro removido com sucesso | {svc_detail}")
            log_block(
                end_msg="Finalização da remoção do registro",
                status="SUCESSO - REGISTRO REMOVIDO E TERMSERVICE REINICIADO"
            )
        else:
            update_state(False, f"Registro removido, mas falhou ao reiniciar serviço | {svc_detail}")
            log_block(
                end_msg="Finalização da remoção do registro",
                status=f"PARCIAL - REGISTRO REMOVIDO, FALHA AO REINICIAR SERVIÇO | {svc_detail}"
            )

    except Exception as e:
        update_state(False, str(e))
        log_block(
            end_msg="Finalização da remoção do registro",
            status=f"ERRO - {e}"
        )


def uninstall():
    if not is_admin():
        print("Execute como ADMIN.")
        sys.exit(1)

    delete_tasks()
    print("Tasks removidas")


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


if __name__ == "__main__":
    main()
