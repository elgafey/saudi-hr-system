from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.auth import service as auth_service
from app.auth.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    MeResponse,
    TokenResponse,
    UserSummary,
)
from app.core.database import get_db
from app.core.deps import Principal, client_ip, get_current_principal
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import csrf_tokens_match, new_csrf_token
from app.shared.models import User

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "hr_refresh_token"
CSRF_COOKIE = "hr_csrf_token"
CSRF_HEADER = "X-CSRF-Token"
REFRESH_COOKIE_PATH = "/api/v1/auth"
CSRF_COOKIE_PATH = "/"


def _set_auth_cookies(
    response: Response,
    *,
    refresh_token: str,
    csrf_token: str,
    max_age: int,
    secure: bool,
) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=refresh_token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=secure,
        path=REFRESH_COOKIE_PATH,
    )
    response.set_cookie(
        key=CSRF_COOKIE,
        value=csrf_token,
        max_age=max_age,
        httponly=False,
        samesite="lax",
        secure=secure,
        path=CSRF_COOKIE_PATH,
    )


def _clear_auth_cookies(response: Response, secure: bool) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, samesite="lax", secure=secure
    )
    response.delete_cookie(
        key=CSRF_COOKIE, path=CSRF_COOKIE_PATH, samesite="lax", secure=secure
    )


def _require_csrf(request: Request) -> None:
    header = request.headers.get(CSRF_HEADER)
    cookie = request.cookies.get(CSRF_COOKIE)
    if not csrf_tokens_match(header, cookie):
        raise ForbiddenError("CSRF token missing or invalid")


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    from app.core.config import get_settings

    settings = get_settings()
    user, _company_ids, access_token = auth_service.login(
        db,
        identifier=payload.identifier,
        password=payload.password,
        ip_address=client_ip(request),
    )
    refresh_token, refresh_row = auth_service.issue_refresh_token(
        db, user, client_ip(request)
    )
    db.commit()

    csrf = new_csrf_token()
    _set_auth_cookies(
        response,
        refresh_token=refresh_token,
        csrf_token=csrf,
        max_age=settings.refresh_token_expire_days * 86400,
        secure=settings.secure_cookies,
    )
    return TokenResponse(
        access_token=access_token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse | JSONResponse:
    from app.core.config import get_settings

    settings = get_settings()
    _require_csrf(request)
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise UnauthorizedError("Refresh token missing")

    try:
        _user, access_token, new_raw, new_row = auth_service.rotate_refresh_token(
            db, raw_token=raw, ip_address=client_ip(request)
        )
    except UnauthorizedError as exc:
        db.rollback()
        failure = JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "code": exc.code},
        )
        _clear_auth_cookies(failure, settings.secure_cookies)
        return failure
    db.commit()

    _set_auth_cookies(
        response,
        refresh_token=new_raw,
        csrf_token=new_csrf_token(),
        max_age=settings.refresh_token_expire_days * 86400,
        secure=settings.secure_cookies,
    )
    return TokenResponse(
        access_token=access_token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> Response:
    from app.core.config import get_settings

    settings = get_settings()
    _require_csrf(request)
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        auth_service.revoke_session_family(
            db, raw, ip_address=client_ip(request)
        )
    db.commit()
    _clear_auth_cookies(response, settings.secure_cookies)
    response.status_code = 204
    return response


@router.get("/me", response_model=MeResponse)
def me(
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> MeResponse:
    user = db.get(User, principal.user_id)
    if user is None:
        raise UnauthorizedError("User not found")
    return MeResponse(
        user=UserSummary.model_validate(user),
        company_ids=principal.company_ids,
        permissions=sorted(principal.permissions),
    )


@router.post("/change-password", status_code=204)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> Response:
    user = db.get(User, principal.user_id)
    if user is None:
        raise UnauthorizedError("User not found")
    auth_service.change_own_password(
        db,
        user=user,
        current_password=payload.current_password,
        new_password=payload.new_password,
        ip_address=client_ip(request),
    )
    db.commit()
    return Response(status_code=204)
