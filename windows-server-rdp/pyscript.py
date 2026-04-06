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


def ensure_base_dir() -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)


def now_str() -> str:
    return dt.datetime.now().strftime("%d/%m/%Y %H:%M")


def log_block(start_msg: str | None = None, end_msg: str | None = None, status: str | None = None) -> None:
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


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run_cmd(cmd: list[str], use_shell: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd if not use_shell else " ".join(cmd),
        capture_output=True,
        text=True,
        shell=use_shell,
        encoding="utf-8",
        errors="replace",
    )


def save_json(path: Path, data: dict) -> None:
    ensure_base_dir()
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_json(path: Path, default: dict | None = None) -> dict:
    if not path.exists():
        return default or {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_config(reg_path: str) -> None:
    save_json(CONFIG_FILE, {"registry_path": reg_path})


def load_config() -> str:
    cfg = load_json(CONFIG_FILE, default={})
    return cfg.get("registry_path", DEFAULT_REG_PATH)


def registry_exists(reg_path: str) -> bool:
    result = run_cmd(["reg", "query", reg_path])
    return result.returncode == 0


def delete_registry_key(reg_path: str) -> tuple[int, str, str]:
    result = run_cmd(["reg", "delete", reg_path, "/f"])
    return result.returncode, (result.stdout or "").strip(), (result.stderr or "").strip()


def should_run_every_7_days() -> bool:
    state = load_json(STATE_FILE, default={})
    last_success = state.get("last_success")

    if not last_success:
        return True

    try:
        last_dt = dt.datetime.fromisoformat(last_success)
    except Exception:
        return True

    return (dt.datetime.now() - last_dt) >= dt.timedelta(days=7)


def update_state(success: bool, details: str = "") -> None:
    state = load_json(STATE_FILE, default={})
    state["last_attempt"] = dt.datetime.now().isoformat()
    state["details"] = details

    if success:
        state["last_success"] = dt.datetime.now().isoformat()

    save_json(STATE_FILE, state)


def create_scheduled_tasks() -> None:
    python_exe = sys.executable
    deployed_script = BASE_DIR / SCRIPT_NAME
    task_command = f'"{python_exe}" "{deployed_script}" --run'

    boot_cmd = [
        "schtasks",
        "/Create",
        "/TN", TASK_BOOT_NAME,
        "/TR", task_command,
        "/SC", "ONSTART",
        "/RU", "SYSTEM",
        "/RL", "HIGHEST",
        "/F",
    ]
    boot_res = run_cmd(boot_cmd, use_shell=True)
    if boot_res.returncode != 0:
        raise RuntimeError(boot_res.stderr or boot_res.stdout or "Falha ao criar tarefa ONSTART")

    daily_cmd = [
        "schtasks",
        "/Create",
        "/TN", TASK_DAILY_NAME,
        "/TR", task_command,
        "/SC", "DAILY",
        "/ST", "03:00",
        "/RU", "SYSTEM",
        "/RL", "HIGHEST",
        "/F",
    ]
    daily_res = run_cmd(daily_cmd, use_shell=True)
    if daily_res.returncode != 0:
        raise RuntimeError(daily_res.stderr or daily_res.stdout or "Falha ao criar tarefa DAILY")


def delete_scheduled_tasks() -> None:
    for task_name in (TASK_BOOT_NAME, TASK_DAILY_NAME):
        run_cmd(["schtasks", "/Delete", "/TN", task_name, "/F"])


def install(reg_path: str) -> None:
    if not is_admin():
        print("Erro: execute este script como Administrador para instalar.")
        sys.exit(1)

    ensure_base_dir()

    src_script = Path(__file__).resolve()
    dst_script = BASE_DIR / SCRIPT_NAME

    if src_script != dst_script:
        shutil.copy2(src_script, dst_script)

    save_config(reg_path)
    create_scheduled_tasks()

    print("Instalação concluída com sucesso.")
    print(f"Pasta base: {BASE_DIR}")
    print(f"Chave configurada: {reg_path}")
    print(f"Tarefas criadas: {TASK_BOOT_NAME} e {TASK_DAILY_NAME}")


def run_cleanup() -> None:
    ensure_base_dir()
    reg_path = load_config()

    if not should_run_every_7_days():
        return

    log_block(start_msg="Iniciando a remoção do registro")

    try:
        if not registry_exists(reg_path):
            update_state(True, "Chave já não existia")
            log_block(
                end_msg="Finalização da remoção do registro",
                status="SUCESSO - CHAVE JÁ NÃO EXISTIA",
            )
            return

        code, stdout, stderr = delete_registry_key(reg_path)

        if code == 0:
            update_state(True, stdout or "Removido com sucesso")
            log_block(
                end_msg="Finalização da remoção do registro",
                status="SUCESSO",
            )
        else:
            detail = stderr or stdout or "Erro desconhecido"
            update_state(False, detail)
            log_block(
                end_msg="Finalização da remoção do registro",
                status=f"ERRO - {detail}",
            )

    except Exception as exc:
        update_state(False, str(exc))
        log_block(
            end_msg="Finalização da remoção do registro",
            status=f"ERRO - {exc}",
        )


def uninstall() -> None:
    if not is_admin():
        print("Erro: execute este script como Administrador para desinstalar.")
        sys.exit(1)

    delete_scheduled_tasks()
    print("Tarefas removidas com sucesso.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove uma chave do Registro do Windows como SYSTEM usando Tarefa Agendada."
    )
    parser.add_argument("--install", action="store_true", help="Instala o script e cria as tarefas agendadas")
    parser.add_argument("--run", action="store_true", help="Executa a rotina de limpeza")
    parser.add_argument("--uninstall", action="store_true", help="Remove as tarefas agendadas")
    parser.add_argument("--reg-path", type=str, help="Caminho completo da chave do registro")

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
