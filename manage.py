#!/usr/bin/env python3
"""
项目服务管理脚本
支持一键启动、停止、重启 PostgreSQL + FastAPI 后端 + Vite 前端
优先使用本地 PostgreSQL，未安装时回退到 Docker
"""
import os
import sys
import time
import signal
import subprocess
import argparse
import socket
import shutil
from datetime import datetime, timedelta
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.resolve()
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
PID_FILE = PROJECT_ROOT / ".service_pids"
FRONTEND_PID_FILE = PROJECT_ROOT / ".frontend_pids"
DOCKER_COMPOSE_FILE = PROJECT_ROOT / "docker-compose.yml"
BACKEND_LOG_FILE = PROJECT_ROOT / ".backend.log"
FRONTEND_LOG_FILE = PROJECT_ROOT / ".frontend.log"
EXPORTS_DIR = PROJECT_ROOT / "exports"

GENERATED_LOG_FILES = (
    ".backend.log",
    ".frontend.log",
)
GENERATED_PID_FILES = (
    ".service_pids",
    ".frontend_pids",
)
SECRET_ENV_FILES = (
    ".env",
    "backend/.env",
)
SECRET_KEYWORDS = (
    "API_KEY",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "ACCESS_KEY",
    "PRIVATE_KEY",
    "JWT_SECRET",
)
SECRET_VALUE_PREFIXES = (
    "sk-",
    "ak-",
)
IGNORED_TRACKED_PATTERNS = (
    ".env",
    "backend/.env",
    ".backend.log",
    ".frontend.log",
    ".service_pids",
    ".frontend_pids",
    "frontend/dist/",
    "__pycache__/",
    ".pyc",
)

# 颜色输出
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
RESET = "\033[0m"

# PostgreSQL 连接配置（本地模式）
PG_HOST = "localhost"
PG_PORT = 5432
PG_USER = os.getenv("USER", "postgres")
PG_DB = "competitor_db"
PG_URL = f"postgresql://{PG_USER}@{PG_HOST}:{PG_PORT}/{PG_DB}"
FRONTEND_HOST = "0.0.0.0"
FRONTEND_PORT = 6173
BACKEND_HOST = "0.0.0.0"
BACKEND_PORT = 8000


def log_info(msg: str):
    print(f"{BLUE}[INFO]{RESET} {msg}")


def log_ok(msg: str):
    print(f"{GREEN}[OK]{RESET} {msg}")


def log_warn(msg: str):
    print(f"{YELLOW}[WARN]{RESET} {msg}")


def log_err(msg: str):
    print(f"{RED}[ERR]{RESET} {msg}")


def run_cmd(cmd: list[str], cwd: Path = None, capture: bool = True) -> subprocess.CompletedProcess:
    """运行 shell 命令"""
    return subprocess.run(
        cmd,
        cwd=cwd or PROJECT_ROOT,
        capture_output=capture,
        text=True,
    )


def _within_project(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _add_existing(paths: list[Path], path: Path, root: Path):
    if path.exists() and _within_project(path, root):
        paths.append(path)


def _pid_file_safe_to_clean(path: Path) -> bool:
    if not path.exists():
        return False
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        if is_pid_running(pid):
            return False
    return True


def plan_clean(
    root: Path = PROJECT_ROOT,
    *,
    logs: bool = True,
    pycache: bool = True,
    dist: bool = False,
    exports: bool = False,
) -> list[Path]:
    """Return generated files/directories that are safe to remove."""
    targets: list[Path] = []

    if logs:
        for rel_path in GENERATED_LOG_FILES:
            _add_existing(targets, root / rel_path, root)
        for rel_path in GENERATED_PID_FILES:
            pid_file = root / rel_path
            if _pid_file_safe_to_clean(pid_file):
                _add_existing(targets, pid_file, root)
        _add_existing(targets, root / "logs", root)

    if pycache:
        for cache_dir in root.rglob("__pycache__"):
            _add_existing(targets, cache_dir, root)
        for pyc_file in root.rglob("*.pyc"):
            _add_existing(targets, pyc_file, root)

    if dist:
        _add_existing(targets, root / "frontend" / "dist", root)

    if exports:
        _add_existing(targets, root / "exports", root)

    unique = {}
    for target in targets:
        unique[target.resolve()] = target
    return sorted(unique.values(), key=lambda path: path.relative_to(root).as_posix())


def plan_prune_task_logs(root: Path = PROJECT_ROOT, *, days: int = 14) -> list[Path]:
    cutoff = datetime.now() - timedelta(days=max(days, 0))
    log_root = root / "logs" / "tasks"
    if not log_root.exists():
        return []
    targets: list[Path] = []
    for path in log_root.rglob("*.log"):
        if not path.is_file() or not _within_project(path, root):
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime)
        if modified < cutoff:
            targets.append(path)
    return sorted(targets, key=lambda path: path.relative_to(root).as_posix())


def prune_task_logs(root: Path = PROJECT_ROOT, *, days: int = 14, apply: bool = False) -> list[Path]:
    targets = plan_prune_task_logs(root, days=days)
    if not apply:
        return targets
    for path in targets:
        path.unlink(missing_ok=True)
        parent = path.parent
        while parent != root and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    return targets


def clean_generated_files(
    root: Path = PROJECT_ROOT,
    *,
    apply: bool = False,
    logs: bool = True,
    pycache: bool = True,
    dist: bool = False,
    exports: bool = False,
) -> list[Path]:
    """Clean generated files. Dry-run unless apply=True."""
    targets = plan_clean(root, logs=logs, pycache=pycache, dist=dist, exports=exports)
    if not apply:
        return targets

    for target in sorted(targets, key=lambda path: len(path.parts), reverse=True):
        if not target.exists():
            continue
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    return targets


def _line_has_secret(key: str, value: str) -> bool:
    key_upper = key.strip().upper()
    value = value.strip()
    has_secret_key = any(keyword in key_upper for keyword in SECRET_KEYWORDS)
    has_secret_value = any(value.startswith(prefix) for prefix in SECRET_VALUE_PREFIXES)
    return bool(has_secret_key and value or has_secret_value)


def _tracked_files(root: Path = PROJECT_ROOT) -> list[str]:
    result = run_cmd(["git", "ls-files"], cwd=root, capture=True)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def scan_tracked_ignored_files(root: Path = PROJECT_ROOT) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for rel_path in _tracked_files(root):
        if (
            rel_path in {".env", "backend/.env", ".backend.log", ".frontend.log", ".service_pids", ".frontend_pids"}
            or rel_path.startswith("frontend/dist/")
            or "/__pycache__/" in f"/{rel_path}"
            or rel_path.endswith(".pyc")
        ):
            findings.append({
                "path": rel_path,
                "line": 0,
                "reason": "tracked generated or sensitive file",
            })
    return findings


def scan_log_secret_risks(root: Path = PROJECT_ROOT) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    log_paths = [root / ".backend.log", root / ".frontend.log"]
    log_dir = root / "logs"
    if log_dir.exists():
        log_paths.extend(path for path in log_dir.rglob("*.log") if path.is_file())

    for path in log_paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            rel_path = path.relative_to(root).as_posix()
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line_no, line in enumerate(lines, start=1):
            normalized = line.strip()
            if "=" in normalized:
                key, value = normalized.split("=", 1)
                if _line_has_secret(key, value):
                    findings.append({"path": rel_path, "line": line_no, "reason": f"{key.strip()} appears in log"})
                    continue
            lower = normalized.lower()
            if "authorization:" in lower or "bearer sk-" in lower or "api_key" in lower and "sk-" in lower:
                findings.append({"path": rel_path, "line": line_no, "reason": "secret-like token appears in log"})
    return findings


def scan_secret_risks(root: Path = PROJECT_ROOT) -> list[dict[str, object]]:
    """Report likely secret locations without returning secret values."""
    findings: list[dict[str, object]] = []

    for rel_path in SECRET_ENV_FILES:
        path = root / rel_path
        if not path.exists() or not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line_no, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if _line_has_secret(key, value):
                findings.append({
                    "path": rel_path,
                    "line": line_no,
                    "reason": f"{key.strip()} looks sensitive",
                })
    return findings


def scan_all_secret_risks(root: Path = PROJECT_ROOT) -> list[dict[str, object]]:
    return scan_secret_risks(root) + scan_log_secret_risks(root) + scan_tracked_ignored_files(root)


def get_docker_compose_cmd() -> list[str] | None:
    """检测系统可用的 docker compose 命令"""
    result = run_cmd(["docker", "compose", "version"], capture=True)
    if result.returncode == 0:
        return ["docker", "compose"]
    result = run_cmd(["docker-compose", "version"], capture=True)
    if result.returncode == 0:
        return ["docker-compose"]
    return None


# 全局检测一次
DOCKER_COMPOSE_CMD = get_docker_compose_cmd()


def is_port_open(host: str, port: int) -> bool:
    """检查端口是否监听"""
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def is_local_postgres_running() -> bool:
    """检查本地 PostgreSQL 是否运行（通过端口检测）"""
    return is_port_open(PG_HOST, PG_PORT)


def is_docker_postgres_running() -> bool:
    """检查 Docker PostgreSQL 容器是否运行中"""
    result = run_cmd(["docker", "ps", "--filter", "name=competitor_pg", "--format", "{{.Names}}"])
    return "competitor_pg" in result.stdout


def is_postgres_running() -> bool:
    """检查 PostgreSQL 是否运行（本地优先）"""
    return is_local_postgres_running() or is_docker_postgres_running()


def is_pid_running(pid: int) -> bool:
    """检查 PID 是否仍然存在"""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_pids(pid_file: Path) -> list[int]:
    """读取 PID 文件中的有效 PID"""
    if not pid_file.exists():
        return []
    pids = []
    for pid_str in pid_file.read_text().strip().split("\n"):
        if not pid_str.strip():
            continue
        try:
            pids.append(int(pid_str.strip()))
        except ValueError:
            continue
    return pids


def is_service_running(pid_file: Path) -> bool:
    """根据 PID 文件检查服务是否运行中"""
    return any(is_pid_running(pid) for pid in read_pids(pid_file))


def is_backend_running() -> bool:
    """检查 FastAPI 后端是否运行中"""
    return is_service_running(PID_FILE) and is_port_open("127.0.0.1", BACKEND_PORT)


def is_frontend_running() -> bool:
    """检查 Vite 前端是否运行中"""
    return is_service_running(FRONTEND_PID_FILE) and is_port_open("127.0.0.1", FRONTEND_PORT)


def stop_pid_file(pid_file: Path, service_name: str):
    """停止 PID 文件中记录的进程组"""
    if not pid_file.exists():
        log_warn(f"{service_name} 未在运行（无 PID 文件）")
        return

    stopped = False
    for pid in read_pids(pid_file):
        try:
            os.killpg(pid, signal.SIGTERM)
            log_info(f"发送 SIGTERM 到 {service_name} 进程组 {pid}...")
        except ProcessLookupError:
            continue
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
                log_info(f"发送 SIGTERM 到 {service_name} 进程 {pid}...")
            except OSError as e:
                log_warn(f"停止 {service_name} 进程 {pid} 失败: {e}")
                continue

        for _ in range(10):
            if not is_pid_running(pid):
                break
            time.sleep(0.5)
        if is_pid_running(pid):
            try:
                os.killpg(pid, signal.SIGKILL)
                log_warn(f"强制终止 {service_name} 进程组 {pid}")
            except OSError:
                try:
                    os.kill(pid, signal.SIGKILL)
                    log_warn(f"强制终止 {service_name} 进程 {pid}")
                except OSError:
                    pass
        stopped = True

    pid_file.unlink(missing_ok=True)
    if stopped:
        log_ok(f"{service_name} 已停止")


def is_adb_connected() -> bool:
    """检查是否有 ADB 设备连接"""
    result = run_cmd(["adb", "devices"])
    lines = result.stdout.strip().split("\n")
    for line in lines[1:]:
        if line.strip() and "\tdevice" in line:
            return True
    return False


def save_pid(pid: int, pid_file: Path = PID_FILE):
    """保存进程 PID 到文件"""
    existing = []
    if pid_file.exists():
        existing = [p for p in pid_file.read_text().strip().split("\n") if p.strip()]
    existing.append(str(pid))
    pid_file.write_text("\n".join(existing) + "\n")


def clear_pids(pid_file: Path = PID_FILE):
    """清除 PID 文件"""
    if pid_file.exists():
        pid_file.unlink()


def start_local_postgres() -> bool:
    """尝试启动本地 PostgreSQL（Homebrew 服务）"""
    log_info("尝试启动本地 PostgreSQL...")

    # 尝试 brew services start
    result = run_cmd(["brew", "services", "start", "postgresql"], capture=True)
    if result.returncode == 0:
        log_ok("PostgreSQL 服务已启动")
        time.sleep(3)
        return True

    # 尝试 pg_ctl（如果知道数据目录）
    data_dirs = [
        "/opt/homebrew/var/postgresql@14",
        "/opt/homebrew/var/postgresql@15",
        "/opt/homebrew/var/postgresql@16",
        "/opt/homebrew/var/postgresql@17",
        "/opt/homebrew/var/postgresql@18",
        "/opt/homebrew/var/postgres",
        "/usr/local/var/postgresql@14",
        "/usr/local/var/postgresql@15",
        "/usr/local/var/postgresql@16",
        "/usr/local/var/postgresql@17",
        "/usr/local/var/postgresql@18",
        "/usr/local/var/postgres",
    ]
    for data_dir in data_dirs:
        if Path(data_dir).exists():
            pg_ctl = run_cmd(["which", "pg_ctl"], capture=True).stdout.strip()
            if pg_ctl:
                result = run_cmd([pg_ctl, "-D", data_dir, "start"], capture=True)
                if result.returncode == 0 or "server starting" in result.stdout.lower():
                    log_ok(f"PostgreSQL 通过 pg_ctl 启动 (数据目录: {data_dir})")
                    time.sleep(3)
                    return True

    return False


def start_postgres() -> bool:
    """启动 PostgreSQL（优先本地，回退 Docker）"""
    if is_local_postgres_running():
        log_ok(f"本地 PostgreSQL 已在运行 (postgresql://{PG_USER}@localhost:{PG_PORT}/{PG_DB})")
        return True

    if is_docker_postgres_running():
        log_ok("Docker PostgreSQL 已在运行中")
        return True

    # 先尝试启动本地 PostgreSQL
    if start_local_postgres():
        if is_local_postgres_running():
            log_ok("本地 PostgreSQL 已就绪")
            return True

    # 本地启动失败，回退到 Docker
    log_warn("本地 PostgreSQL 未安装或未运行，尝试 Docker...")
    if DOCKER_COMPOSE_CMD is None:
        log_err("未检测到 docker compose 命令")
        log_info("请安装 PostgreSQL: brew install postgresql@18")
        return False

    log_info("启动 PostgreSQL Docker 容器...")
    result = run_cmd(DOCKER_COMPOSE_CMD + ["-f", str(DOCKER_COMPOSE_FILE), "up", "-d"])
    if result.returncode != 0:
        log_err(f"启动 Docker PostgreSQL 失败: {result.stderr}")
        return False

    # 等待 Docker PostgreSQL 就绪
    log_info("等待 Docker PostgreSQL 就绪...")
    for i in range(30):
        result = run_cmd(["docker", "exec", "competitor_pg", "pg_isready", "-U", "postgres"])
        if result.returncode == 0:
            log_ok("Docker PostgreSQL 已就绪")
            return True
        time.sleep(1)
    log_err("Docker PostgreSQL 启动超时")
    return False


def stop_postgres():
    """停止 PostgreSQL（仅停止 Docker，不停止本地服务）"""
    if is_docker_postgres_running():
        log_info("停止 Docker PostgreSQL 容器...")
        if DOCKER_COMPOSE_CMD:
            result = run_cmd(DOCKER_COMPOSE_CMD + ["-f", str(DOCKER_COMPOSE_FILE), "down"])
            if result.returncode == 0:
                log_ok("Docker PostgreSQL 已停止")
            else:
                log_err(f"停止 Docker PostgreSQL 失败: {result.stderr}")
        else:
            run_cmd(["docker", "stop", "competitor_pg"])
            run_cmd(["docker", "rm", "competitor_pg"])
    elif is_local_postgres_running():
        log_warn("检测到本地 PostgreSQL 正在运行")
        log_info("manage.py stop 不会停止本地 PostgreSQL 服务（避免影响其他项目）")
        log_info("如需停止，请手动执行: brew services stop postgresql")
    else:
        log_warn("PostgreSQL 未在运行")


def init_database():
    """确保数据库和 pgvector 扩展存在"""
    if not is_local_postgres_running():
        return

    # 检查数据库是否存在
    result = run_cmd([
        "psql", "-U", PG_USER, "-d", "postgres", "-c",
        f"SELECT 1 FROM pg_database WHERE datname = '{PG_DB}';"
    ], capture=True)
    if result.returncode != 0 or PG_DB not in result.stdout:
        log_info(f"创建数据库 {PG_DB}...")
        run_cmd(["createdb", "-U", PG_USER, PG_DB], capture=True)

    # 启用 pgvector
    run_cmd([
        "psql", "-U", PG_USER, "-d", PG_DB, "-c",
        "CREATE EXTENSION IF NOT EXISTS vector;"
    ], capture=True)


def ensure_frontend_dependencies() -> bool:
    """确保前端依赖已安装"""
    if (FRONTEND_DIR / "node_modules").exists():
        return True

    log_info("安装前端依赖...")
    result = run_cmd(["npm", "install"], cwd=FRONTEND_DIR)
    if result.returncode != 0:
        log_err(f"安装前端依赖失败: {result.stderr}")
        return False
    return True


def start_backend() -> bool:
    """启动 FastAPI 后端服务"""
    if is_backend_running():
        log_warn("FastAPI 后端已在运行中")
        return True
    if is_service_running(PID_FILE):
        log_warn("检测到旧的 FastAPI 后端进程，但目标端口未就绪，先停止旧进程")
        stop_backend()
    if is_port_open("127.0.0.1", BACKEND_PORT):
        log_err(f"端口 {BACKEND_PORT} 已被占用，但没有匹配的后端 PID 记录")
        log_info(f"请先释放该端口后重试")
        return False

    log_info("启动 FastAPI 后端服务...")

    # 确保依赖已安装
    result = run_cmd([sys.executable, "-m", "pip", "show", "uvicorn"], capture=True)
    if result.returncode != 0:
        log_info("安装后端依赖...")
        req_file = BACKEND_DIR / "requirements.txt"
        run_cmd([sys.executable, "-m", "pip", "install", "-r", str(req_file)])

    # 后台启动 uvicorn
    env = os.environ.copy()
    # 根据 PostgreSQL 模式设置 DATABASE_URL
    if is_local_postgres_running():
        env["DATABASE_URL"] = PG_URL
        log_info(f"使用本地 PostgreSQL: {PG_URL}")
    else:
        env["DATABASE_URL"] = "postgresql://postgres:postgres@localhost:5432/competitor_db"
        log_info("使用 Docker PostgreSQL")

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--reload",
            "--host",
            BACKEND_HOST,
            "--port",
            str(BACKEND_PORT),
        ],
        cwd=BACKEND_DIR,
        env=env,
        stdout=open(BACKEND_LOG_FILE, "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    save_pid(process.pid)

    # 等待服务就绪
    time.sleep(2)
    result = run_cmd(["curl", "-s", f"http://localhost:{BACKEND_PORT}/health"], capture=True)
    if result.returncode == 0 and '"status":"ok"' in result.stdout:
        log_ok(f"FastAPI 后端已启动 (PID: {process.pid})，访问 http://localhost:{BACKEND_PORT}")
        return True
    else:
        log_warn("FastAPI 后端可能还在启动中，请稍后用 status 检查")
        return True


def start_frontend() -> bool:
    """启动 Vite 前端服务"""
    if is_frontend_running():
        log_warn("Vite 前端已在运行中")
        return True
    if is_service_running(FRONTEND_PID_FILE):
        log_warn("检测到旧的 Vite 前端进程，但目标端口未就绪，先停止旧进程")
        stop_frontend()
    if is_port_open("127.0.0.1", FRONTEND_PORT):
        log_err(f"端口 {FRONTEND_PORT} 已被占用，但没有匹配的前端 PID 记录")
        log_info("请先释放该端口后重试")
        return False

    if not ensure_frontend_dependencies():
        return False

    log_info("启动 Vite 前端服务...")
    process = subprocess.Popen(
        ["npm", "run", "dev", "--", "--host", FRONTEND_HOST, "--port", str(FRONTEND_PORT), "--strictPort"],
        cwd=FRONTEND_DIR,
        stdout=open(FRONTEND_LOG_FILE, "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    save_pid(process.pid, FRONTEND_PID_FILE)

    for _ in range(20):
        if is_port_open("127.0.0.1", FRONTEND_PORT):
            log_ok(f"Vite 前端已启动 (PID: {process.pid})，访问 http://localhost:{FRONTEND_PORT}")
            return True
        time.sleep(0.5)

    log_warn("Vite 前端可能还在启动中，请稍后用 status 检查")
    return True


def stop_backend():
    """停止 FastAPI 后端服务"""
    stop_pid_file(PID_FILE, "FastAPI 后端")


def stop_frontend():
    """停止 Vite 前端服务"""
    stop_pid_file(FRONTEND_PID_FILE, "Vite 前端")


def start_all():
    """启动所有服务"""
    print(f"\n{'='*50}")
    print(" 启动服务")
    print(f"{'='*50}\n")

    # 1. 启动 PostgreSQL
    if not start_postgres():
        log_err("PostgreSQL 启动失败，中止")
        return False

    # 1.5 如果是本地 PostgreSQL，确保数据库和扩展存在
    if is_local_postgres_running() and not is_docker_postgres_running():
        init_database()

    # 2. 启动 FastAPI 后端
    if not start_backend():
        log_err("FastAPI 后端启动失败")
        return False

    # 3. 启动 Vite 前端
    if not start_frontend():
        log_err("Vite 前端启动失败")
        return False

    print(f"\n{'='*50}")
    log_ok("所有服务已启动")
    print(f"{'='*50}\n")
    print("服务地址:")
    print(f"  - 前端页面:     http://localhost:{FRONTEND_PORT}")
    print(f"  - FastAPI API:  http://localhost:{BACKEND_PORT}")
    print(f"  - API 文档:     http://localhost:{BACKEND_PORT}/docs")
    print("  - PostgreSQL:   localhost:5432")
    print("")
    print("常用命令:")
    print("  npm start                  启动前后端")
    print("  npm stop                   停止前后端")
    print("  npm run reset              重启前后端")
    print("  python manage.py status    查看服务状态")
    print("  python manage.py logs      查看后端日志")
    print("")
    return True


def stop_all():
    """停止所有服务"""
    print(f"\n{'='*50}")
    print(" 停止服务")
    print(f"{'='*50}\n")

    stop_frontend()
    stop_backend()
    stop_postgres()

    print(f"\n{'='*50}")
    log_ok("所有服务已停止")
    print(f"{'='*50}\n")


def restart_all():
    """重启所有服务"""
    print(f"\n{'='*50}")
    print(" 重启服务")
    print(f"{'='*50}\n")
    stop_all()
    time.sleep(2)
    return start_all()


def show_status():
    """显示所有服务状态"""
    print(f"\n{'='*50}")
    print(" 服务状态")
    print(f"{'='*50}\n")

    # PostgreSQL（区分本地和 Docker）
    if is_local_postgres_running():
        log_ok("PostgreSQL    : 运行中 (本地 Homebrew)")
    elif is_docker_postgres_running():
        log_ok("PostgreSQL    : 运行中 (Docker: competitor_pg)")
    else:
        log_err("PostgreSQL    : 未运行")

    # FastAPI 后端
    if is_backend_running():
        log_ok("FastAPI 后端   : 运行中")
    else:
        log_err("FastAPI 后端   : 未运行")

    # Vite 前端
    if is_frontend_running():
        log_ok(f"Vite 前端      : 运行中 (http://localhost:{FRONTEND_PORT})")
    else:
        log_err("Vite 前端      : 未运行")

    # ADB 设备
    if is_adb_connected():
        result = run_cmd(["adb", "devices"])
        devices = [line.split("\t")[0] for line in result.stdout.strip().split("\n")[1:] if "\tdevice" in line]
        log_ok(f"ADB 设备      : 已连接 ({', '.join(devices)})")
    else:
        log_warn("ADB 设备      : 未连接")

    print(f"\n{'='*50}\n")


def show_log_file(title: str, log_file: Path):
    """显示指定日志文件最近 50 行"""
    if not log_file.exists():
        log_warn(f"暂无{title}日志文件")
        return

    print(f"\n{'='*50}")
    print(f" {title}日志 (最近 50 行)")
    print(f"{'='*50}\n")

    result = run_cmd(["tail", "-n", "50", str(log_file)])
    print(result.stdout)


def show_logs():
    """显示服务日志"""
    show_log_file("后端", BACKEND_LOG_FILE)
    show_log_file("前端", FRONTEND_LOG_FILE)
    print(f"\n{'='*50}\n")


def show_task_logs(args):
    log_root = PROJECT_ROOT / "logs" / "tasks"
    print(f"\n{'='*50}")
    print(" 任务日志")
    print(f"{'='*50}\n")
    if not log_root.exists():
        log_warn("暂无任务日志")
        return
    logs = sorted((path for path in log_root.rglob("*.log") if path.is_file()), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in logs[: max(args.limit, 1)]:
        print(path.relative_to(PROJECT_ROOT))


def show_prune_task_logs(args):
    targets = prune_task_logs(PROJECT_ROOT, days=args.days, apply=args.apply)
    print(f"\n{'='*50}")
    print(" 清理任务日志")
    print(f"{'='*50}\n")
    if not targets:
        log_ok("没有发现过期任务日志")
        return
    action = "已删除" if args.apply else "将清理"
    for target in targets:
        print(f"{action}: {target.relative_to(PROJECT_ROOT)}")
    if not args.apply:
        log_info("当前为 dry-run，未删除任何文件。确认后可追加 --apply")


def show_clean_plan(args):
    targets = clean_generated_files(
        PROJECT_ROOT,
        apply=args.apply,
        logs=args.logs,
        pycache=args.pycache,
        dist=args.dist,
        exports=args.exports,
    )

    print(f"\n{'='*50}")
    print(" 清理生成文件")
    print(f"{'='*50}\n")
    if not targets:
        log_ok("没有发现需要清理的生成文件")
        return

    action = "已删除" if args.apply else "将清理"
    for target in targets:
        print(f"{action}: {target.relative_to(PROJECT_ROOT)}")
    if not args.apply:
        log_info("当前为 dry-run，未删除任何文件。确认后可追加 --apply")
    else:
        log_ok(f"已清理 {len(targets)} 项")


def show_secret_risks():
    findings = scan_all_secret_risks(PROJECT_ROOT)
    print(f"\n{'='*50}")
    print(" 敏感配置检查")
    print(f"{'='*50}\n")
    if not findings:
        log_ok("未在常见配置文件中发现已填写的敏感变量")
        return

    log_warn("发现可能包含敏感值的配置项（仅显示路径和变量名，不显示值）")
    for finding in findings:
        print(f"- {finding['path']}:{finding['line']} {finding['reason']}")
    log_info("请确保这些文件未被提交；如需共享配置，请使用 .env.example")


def main():
    parser = argparse.ArgumentParser(description="竞品分析平台服务管理")
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    subparsers.add_parser("start", help="启动所有服务")
    subparsers.add_parser("stop", help="停止所有服务")
    subparsers.add_parser("restart", help="重启所有服务")
    subparsers.add_parser("status", help="查看服务状态")
    subparsers.add_parser("logs", help="查看后端日志")
    task_logs_parser = subparsers.add_parser("task-logs", help="列出最近任务日志")
    task_logs_parser.add_argument("--limit", type=int, default=20, help="最多列出多少条")
    prune_logs_parser = subparsers.add_parser("prune-task-logs", help="按天数清理过期任务日志")
    prune_logs_parser.add_argument("--days", type=int, default=14, help="保留最近多少天")
    prune_logs_parser.add_argument("--apply", action="store_true", help="实际删除；默认只 dry-run")
    clean_parser = subparsers.add_parser("clean", help="清理日志、缓存、构建和导出产物")
    clean_mode = clean_parser.add_mutually_exclusive_group()
    clean_mode.add_argument("--dry-run", dest="apply", action="store_false", help="只列出将清理内容，不删除文件")
    clean_mode.add_argument("--apply", dest="apply", action="store_true", help="实际删除；默认只 dry-run")
    clean_parser.set_defaults(apply=False)
    clean_parser.add_argument("--logs", action=argparse.BooleanOptionalAction, default=True, help="包含日志和 PID 文件")
    clean_parser.add_argument("--pycache", action=argparse.BooleanOptionalAction, default=True, help="包含 Python 缓存")
    clean_parser.add_argument("--dist", action="store_true", help="包含 frontend/dist")
    clean_parser.add_argument("--exports", action="store_true", help="包含 exports 导出目录")
    subparsers.add_parser("doctor-secrets", help="检查常见敏感配置风险")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "start":
        sys.exit(0 if start_all() else 1)
    elif args.command == "stop":
        stop_all()
    elif args.command == "restart":
        sys.exit(0 if restart_all() else 1)
    elif args.command == "status":
        show_status()
    elif args.command == "logs":
        show_logs()
    elif args.command == "task-logs":
        show_task_logs(args)
    elif args.command == "prune-task-logs":
        show_prune_task_logs(args)
    elif args.command == "clean":
        show_clean_plan(args)
    elif args.command == "doctor-secrets":
        show_secret_risks()


if __name__ == "__main__":
    main()
