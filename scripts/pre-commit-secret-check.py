#!/usr/bin/env python3
import re
import subprocess
import sys


BLOCKED_PATHS = (
    ".env",
    "backend/.env",
    ".backend.log",
    ".frontend.log",
    ".service_pids",
    ".frontend_pids",
)
BLOCKED_PREFIXES = (
    "frontend/dist/",
    "frontend/node_modules/",
    "logs/",
    "exports/",
)
TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_-])(sk-(?:proj-)?[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})(?![A-Za-z0-9_-])")
ENV_SECRET_RE = re.compile(
    r"^\s*[A-Z0-9_]*(?:API_KEY|SECRET_ACCESS_KEY|ACCESS_KEY_ID|JWT_SECRET|PASSWORD)\s*=\s*(.+?)\s*$"
)
PLACEHOLDER_VALUES = {
    "",
    "changeme",
    "change-me",
    "placeholder",
    "test-key",
    "phone-key",
    "openai-key",
    "embedding-key",
    "ai-match-key",
    "doubao-key",
}


def staged_files() -> list[tuple[str, str]]:
    result = subprocess.run(["git", "diff", "--cached", "--name-status"], capture_output=True, text=True)
    if result.returncode != 0:
        return []
    files = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        path = parts[-1]
        files.append((status, path))
    return files


def staged_content(path: str) -> str:
    result = subprocess.run(["git", "show", f":{path}"], capture_output=True, text=True, errors="ignore")
    return result.stdout if result.returncode == 0 else ""


def has_secret_like_content(content: str) -> bool:
    if TOKEN_RE.search(content):
        return True
    for line in content.splitlines():
        match = ENV_SECRET_RE.match(line)
        if not match:
            continue
        value = match.group(1).strip().strip('"').strip("'")
        if value.lower() not in PLACEHOLDER_VALUES:
            return True
    return False


def main() -> int:
    violations = []
    for status, path in staged_files():
        if status.startswith("D"):
            continue
        if path in BLOCKED_PATHS or any(path.startswith(prefix) for prefix in BLOCKED_PREFIXES):
            violations.append(f"{path}: blocked generated or sensitive path")
            continue
        if has_secret_like_content(staged_content(path)):
            violations.append(f"{path}: secret-like content")
    if violations:
        print("pre-commit secret check failed:")
        for item in violations:
            print(f"- {item}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
