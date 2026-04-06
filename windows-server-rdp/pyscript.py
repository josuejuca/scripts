# python pyscript.py --uninstall
# python pyscript.py --install --reg-path "HKLM\SYSTEM\CurrentControlSet\Control\Terminal Server\RCM\GracePeriod"
# python pyscript.py --run-now-system

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


def now():
    return dt.datetime.now()


def now_str():
    return now().strftime("%d/%m/%Y %H:%M")


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


def run_cmd(cmd):
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


def whoami():
    res = run_cmd(["whoami"])
    return (res.stdout or res.stderr or "").strip()


def registry_exists(reg_path: str):
    res = run_cmd(["reg", "query", reg_path])
    return res.returncode == 0

def delete_registry(reg_path: str):
    ps_path = reg_path.replace("HKLM\\", "Registry::HKEY_LOCAL_MACHINE\\")
    
    ps_script = f'''
$ErrorActionPreference = "Stop"
$path = "{ps_path}"

if (Test-Path $path) {{
    takeown /f "$path" /a /r /d y | Out-Null
    icacls "$path" /grant Administrators:F /t /c | Out-Null
    Remove-Item -LiteralPath $path -Recurse -Force
    Write-Output "REMOVIDO"
}} else {{
    Write-Output "NAO_EXISTE"
}}
'''

    res = run_cmd([
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-Command", ps_script
    ])

    ok = res.returncode == 0
    out = (res.stdout or "").strip()
    err = (res.stderr or "").strip()

    return (0 if ok else 1), out, err


def restart_termservice():
    stop_res = run_cmd(["net", "stop", "TermService"])
    start_res = run_cmd(["net", "start", "TermService"])

    ok = stop_res.returncode == 0 and start_res.returncode == 0
    detail = (
        f"STOP[{stop_res.returncode}]: {((stop_res.stdout or stop_res.stderr or '').strip())} | "
        f"START[{start_res.returncode}]: {((start_res.stdout or start_res.stderr or '').strip())}"
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

    delta = now() - last_dt
    return delta.days >= 7, False


def update_state(success: bool, detail: str = ""):
    state = load_json(STATE_FILE, {})
    state["last_attempt"] = now().isoformat()
    state["detail"] = detail

    if success:
        state["last_success"] = now().isoformat()

    save_json(STATE_FILE, state)


def to_registry_provider_path(reg_path: str) -> str:
    reg_path = reg_path.strip()
    if reg_path.upper().startswith("HKLM\\"):
        return "Registry::HKEY_LOCAL_MACHINE\\" + reg_path[5:]
    if reg_path.upper().startswith("HKEY_LOCAL_MACHINE\\"):
        return "Registry::" + reg_path
    if reg_path.upper().startswith("HKCU\\"):
        return "Registry::HKEY_CURRENT_USER\\" + reg_path[5:]
    if reg_path.upper().startswith("HKEY_CURRENT_USER\\"):
        return "Registry::" + reg_path
    return reg_path


def try_fix_registry_permissions(reg_path: str):
    ps_path = to_registry_provider_path(reg_path)

    ps_script = rf'''
$ErrorActionPreference = "Stop"
$path = "{ps_path}"
if (-not (Test-Path $path)) {{
    Write-Output "PATH_NOT_FOUND"
    exit 0
}}

$key = Get-Item -LiteralPath $path
$acl = $key.GetAccessControl()

$admins = New-Object System.Security.Principal.NTAccount("Administrators")
$system = New-Object System.Security.Principal.NTAccount("SYSTEM")

$acl.SetOwner($admins)

$ruleAdmins = New-Object System.Security.AccessControl.RegistryAccessRule(
    "Administrators",
    "FullControl",
    "ContainerInherit,ObjectInherit",
    "None",
    "Allow"
)

$ruleSystem = New-Object System.Security.AccessControl.RegistryAccessRule(
    "SYSTEM",
    "FullControl",
    "ContainerInherit,ObjectInherit",
    "None",
    "Allow"
)

$acl.SetAccessRule($ruleAdmins)
$acl.SetAccessRule($ruleSystem)
$key.SetAccessControl($acl)

Write-Output "ACL_FIXED"
'''
    res = run_cmd([
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        ps_script
    ])
    ok = res.returncode == 0
    detail = (res.stdout or res.stderr or "").strip()
    return ok, detail


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
        raise RuntimeError(f"Erro task ONSTART: {r1.stderr or r1.stdout}")

    r2 = run_cmd(daily)
    if r2.returncode != 0:
        raise RuntimeError(f"Erro task DAILY: {r2.stderr or r2.stdout}")


def run_system_now():
    return run_cmd(["schtasks", "/Run", "/TN", TASK_BOOT_NAME])


def delete_tasks():
    for t in [TASK_BOOT_NAME, TASK_DAILY_NAME]:
        run_cmd(["schtasks", "/Delete", "/TN", t, "/F"])


def install(reg_path: str):
    if not is_admin():
        print("Execute como ADMIN.")
        sys.exit(1)

    ensure_base_dir()
    log_block(start_msg="Instalação da rotina")

    src = Path(__file__).resolve()
    dst = BASE_DIR / SCRIPT_NAME

    if src != dst:
        shutil.copy2(src, dst)

    save_config(reg_path)
    create_tasks()

    log_block(
        end_msg="Instalação da rotina",
        status=f"SUCESSO - PYTHON: {sys.executable}"
    )

    print("OK instalado")
    print(f"Pasta: {BASE_DIR}")
    print(f"Registro: {reg_path}")
    print(f"Python: {sys.executable}")
    print("Para testar como SYSTEM: schtasks /Run /TN JUCA_RegCleanup_SYSTEM")


def run_cleanup(force: bool = False):
    ensure_base_dir()

    should_execute, is_first_run = should_run()
    if not should_execute and not force:
        log_block(
            start_msg=f"Verificação agendada da remoção do registro // Usuário: {whoami()}",
            end_msg="Finalização da verificação agendada",
            status="SKIP - AINDA NÃO PASSARAM 7 DIAS"
        )
        return

    reg_path = load_config()
    identity = whoami()

    if is_first_run:
        log_block(start_msg=f"Primeira execução da rotina de remoção do registro // Usuário: {identity}")
    else:
        log_block(start_msg=f"Iniciando a remoção do registro // Usuário: {identity}")

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
            fix_ok, fix_detail = try_fix_registry_permissions(reg_path)
            code, out, err = delete_registry(reg_path)

            if code != 0:
                detail = err or out or "Erro ao remover chave"
                if fix_detail:
                    detail = f"{detail} | ACL: {fix_detail}"
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
    log_block(
        start_msg="Desinstalação da rotina",
        end_msg="Desinstalação da rotina",
        status="SUCESSO"
    )
    print("Tasks removidas")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--run-now-system", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--reg-path", type=str)

    args = parser.parse_args()
    reg_path = args.reg_path or DEFAULT_REG_PATH

    if args.install:
        install(reg_path)
    elif args.run:
        run_cleanup()
    elif args.run_now_system:
        res = run_system_now()
        print((res.stdout or res.stderr or "").strip())
    elif args.uninstall:
        uninstall()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
