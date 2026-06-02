import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime
from typing import Iterable
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app import crud, models
from app.config import settings
from app.database import get_db


VALID_ROLES = {"admin", "operator", "viewer"}
VALID_USER_STATUSES = {"active", "disabled"}
ROLE_RANK = {"viewer": 1, "operator": 2, "admin": 3}


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password is required")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 260_000)
    return "pbkdf2_sha256$260000$" + base64.urlsafe_b64encode(salt).decode() + "$" + base64.urlsafe_b64encode(digest).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_b64.encode())
        expected = base64.urlsafe_b64decode(digest_b64.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _b64_json(data: dict) -> str:
    raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64_decode_json(data: str) -> dict:
    padded = data + "=" * (-len(data) % 4)
    return json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))


def _sign(message: str) -> str:
    digest = hmac.new(settings.JWT_SECRET.encode("utf-8"), message.encode("ascii"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def create_access_token(user: models.User) -> str:
    now = int(time.time())
    header = _b64_json({"alg": "HS256", "typ": "JWT"})
    payload = _b64_json({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "iat": now,
        "exp": now + settings.JWT_EXPIRES_MINUTES * 60,
    })
    message = f"{header}.{payload}"
    return f"{message}.{_sign(message)}"


def decode_access_token(token: str) -> dict:
    try:
        header, payload, signature = token.split(".", 2)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    message = f"{header}.{payload}"
    if not hmac.compare_digest(_sign(message), signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    data = _b64_decode_json(payload)
    if int(data.get("exp", 0)) < int(time.time()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    return data


def token_from_request(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    query_token = request.query_params.get("token")
    return query_token.strip() if query_token else None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> models.User:
    token = token_from_request(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    data = decode_access_token(token)
    try:
        user_id = UUID(str(data["sub"]))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    user = crud.get_user(db, user_id)
    if not user or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive")
    return user


def optional_current_user(request: Request, db: Session = Depends(get_db)) -> models.User | None:
    token = token_from_request(request)
    if not token:
        return None
    return get_current_user(request, db)


def require_roles(*roles: str):
    allowed = set(roles)

    def dependency(user: models.User = Depends(get_current_user)) -> models.User:
        if user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return dependency


def require_at_least(role: str):
    def dependency(user: models.User = Depends(get_current_user)) -> models.User:
        if ROLE_RANK.get(user.role, 0) < ROLE_RANK[role]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return dependency


def data_scope_user_id(user: models.User) -> UUID | None:
    if not user or not hasattr(user, "role"):
        return None
    if ROLE_RANK.get(user.role, 0) >= ROLE_RANK["operator"]:
        return None
    return user.id


def validate_role(role: str) -> str:
    if role not in VALID_ROLES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role")
    return role


def validate_user_status(value: str) -> str:
    if value not in VALID_USER_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user status")
    return value


def roles_at_least(role: str) -> Iterable[str]:
    minimum = ROLE_RANK[role]
    return [name for name, rank in ROLE_RANK.items() if rank >= minimum]
