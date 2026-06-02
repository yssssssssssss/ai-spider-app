from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID
import re

from app import crud, schemas, models
from app.database import get_db
from app.services.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    require_roles,
    validate_role,
    validate_user_status,
    verify_password,
)

router = APIRouter(tags=["auth"])


def _invite_code_or_400(invite_code: str) -> str:
    code = invite_code.strip()
    if not re.fullmatch(r"\d{4}", code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invite code must be 4 digits")
    return code


@router.post("/auth/login", response_model=schemas.LoginResponse)
def login(body: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = crud.get_user_by_username(db, body.username.strip())
    if not user or user.status != "active" or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    user = crud.record_login(db, user)
    return schemas.LoginResponse(access_token=create_access_token(user), user=schemas.UserOut.model_validate(user))


@router.post("/auth/register", response_model=schemas.LoginResponse)
def register(body: schemas.RegisterRequest, db: Session = Depends(get_db)):
    username = body.username.strip()
    if not username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username is required")
    if not body.password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password is required")
    invite_code = _invite_code_or_400(body.invite_code)
    if invite_code != crud.get_registration_invite_code(db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid invite code")
    if crud.get_user_by_username(db, username):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    user = crud.create_user(
        db,
        username=username,
        display_name=username,
        password_hash=hash_password(body.password),
        role="viewer",
    )
    user = crud.record_login(db, user)
    return schemas.LoginResponse(access_token=create_access_token(user), user=schemas.UserOut.model_validate(user))


@router.post("/auth/logout")
def logout():
    return {"ok": True}


@router.get("/auth/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(get_current_user)):
    return user


@router.get("/admin/users", response_model=list[schemas.UserOut])
def list_users(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_roles("admin")),
):
    return crud.list_users(db, skip=skip, limit=limit)


@router.get("/admin/settings/registration-invite-code", response_model=schemas.RegistrationInviteCodeOut)
def get_registration_invite_code(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_roles("admin")),
):
    return schemas.RegistrationInviteCodeOut(invite_code=crud.get_registration_invite_code(db))


@router.patch("/admin/settings/registration-invite-code", response_model=schemas.RegistrationInviteCodeOut)
def update_registration_invite_code(
    body: schemas.RegistrationInviteCodeUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles("admin")),
):
    invite_code = _invite_code_or_400(body.invite_code)
    setting = crud.set_registration_invite_code(db, invite_code, updated_by=user.id)
    return schemas.RegistrationInviteCodeOut(invite_code=setting.value)


@router.post("/admin/users", response_model=schemas.UserOut)
def create_user(
    body: schemas.UserCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_roles("admin")),
):
    username = body.username.strip()
    if not username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username is required")
    if crud.get_user_by_username(db, username):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    role = validate_role(body.role)
    user = crud.create_user(
        db,
        username=username,
        display_name=body.display_name,
        password_hash=hash_password(body.password),
        role=role,
    )
    return user


@router.patch("/admin/users/{user_id}", response_model=schemas.UserOut)
def update_user(
    user_id: UUID,
    body: schemas.UserUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_roles("admin")),
):
    role = validate_role(body.role) if body.role is not None else None
    user_status = validate_user_status(body.status) if body.status is not None else None
    password_hash = hash_password(body.password) if body.password else None
    user = crud.update_user(
        db,
        user_id,
        display_name=body.display_name,
        role=role,
        status=user_status,
        password_hash=password_hash,
    )
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user
