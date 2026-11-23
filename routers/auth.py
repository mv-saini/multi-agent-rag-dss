from __future__ import annotations

from datetime import datetime, timedelta, timezone
import config
import uuid

import bcrypt
import jwt
from fastapi import APIRouter, Cookie, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.storage import sql_database

ADMIN_ROLE = 1
USER_ROLE = 2
ROLE_OPTIONS = (
    {"id": ADMIN_ROLE, "name": "Administrator"},
    {"id": USER_ROLE, "name": "User"},
)


class AuthenticationError(Exception):
    """Raised when a request does not have valid authentication."""


class AuthorizationError(Exception):
    """Raised when an authenticated user lacks the required permission."""


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


def _role_value(value: object) -> int:
    return value if type(value) is int else USER_ROLE


def _require_authentication(
    request: Request,
    access_token: str | None = Cookie(default=None, alias=config.ACCESS_COOKIE_NAME),
) -> dict[str, object]:
    if not access_token:
        raise AuthenticationError("Missing access token.")

    try:
        payload = jwt.decode(
            access_token, config.JWT_SECRET_KEY, algorithms=[config.JWT_ALGORITHM]
        )
    except jwt.PyJWTError as exc:
        raise AuthenticationError from exc

    username = payload.get("username")
    if not isinstance(username, str):
        raise AuthenticationError("Invalid access token.")
    user = {
        "id": str(payload.get("id", "")),
        "username": username,
        "email": str(payload.get("email", "")),
        "active": bool(payload.get("active", "")),
        "reset": bool(payload.get("reset", "")),
        "role": _role_value(payload.get("role")),
    }

    request.state.authenticated_user = {
        "id": user["id"],
        "username": user["username"],
    }
    return user


def _require_administrator(
    user: dict[str, object] = Depends(_require_authentication),
) -> dict[str, object]:
    conn = sql_database.get_connection()
    try:
        row = conn.execute(
            "SELECT active, role FROM users WHERE id = %s LIMIT 1",
            (user["id"],),
        ).fetchone()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if not row or not row[0] or _role_value(row[1]) != ADMIN_ROLE:
        raise AuthorizationError("Administrator access is required.")

    return {**user, "role": ADMIN_ROLE}


auth_router = APIRouter(prefix="/api/auth")


@auth_router.post("/login")
def login(request: LoginRequest) -> dict[str, str]:
    """Authenticates the configured user and returns a JWT."""

    conn = sql_database.get_connection()
    try:
        query = "SELECT id, username, email, password, reset, active, role FROM users WHERE username = %s LIMIT 1"
        result = conn.execute(query, (request.username,)).fetchone()
    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"Error during login user query. {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"data": None, "error": "Internal Server Error"},
        )

    if not result:
        conn.close()
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"data": None, "error": "Invalid username or password"},
        )

    user = {
        "id": result[0],
        "username": result[1],
        "email": result[2],
        "password": result[3],
        "reset": result[4],
        "active": result[5],
        "role": _role_value(result[6]),
    }

    if not user["active"]:
        conn.close()
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "data": None,
                "error": "User account is inactive. Please contact the administrator.",
            },
        )

    if not bcrypt.checkpw(
        request.password.encode("utf-8"), user["password"].encode("utf-8")
    ):
        conn.close()
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"data": None, "error": "Invalid username or password"},
        )

    token = jwt.encode(
        {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "active": user["active"],
            "reset": user["reset"],
            "role": user["role"],
            "exp": datetime.now(timezone.utc)
            + timedelta(hours=config.ACCESS_TOKEN_EXPIRATION_SEC / 3600),
        },
        config.JWT_SECRET_KEY,
        algorithm=config.JWT_ALGORITHM,
    )

    login_response = JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "data": {
                "id": user["id"],
                "username": user["username"],
                "email": user["email"],
                "active": user["active"],
                "reset": user["reset"],
                "role": user["role"],
            },
            "error": None,
        },
    )

    login_response.set_cookie(
        key=config.ACCESS_COOKIE_NAME,
        value=token,
        max_age=config.ACCESS_TOKEN_EXPIRATION_SEC,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="strict",
        path="/",
    )

    refresh_val = uuid.uuid4().hex

    try:
        query = "INSERT INTO usersrefreshtokens (token, userid) VALUES (%s, %s)"
        conn.execute(query, (refresh_val, user["id"]))
        conn.commit()
    except Exception as e:
        print(f"Error storing refresh token: {e}")
        conn.rollback()
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"data": None, "error": "Internal Server Error"},
        )
    finally:
        conn.close()

    login_response.set_cookie(
        key=config.REFRESH_COOKIE_NAME,
        value=refresh_val,
        max_age=config.REFRESH_TOKEN_EXPIRATION_SEC,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="strict",
        path="/api/auth/refresh",
    )

    return login_response


@auth_router.post("/refresh")
def refresh_token(
    refresh_token: str | None = Cookie(default=None, alias=config.REFRESH_COOKIE_NAME),
) -> dict[str, str]:
    """Refreshes the JWT for the authenticated user."""

    if not refresh_token:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"data": None, "error": "Missing refresh token. Please log in."},
        )

    conn = sql_database.get_connection()
    try:
        query = """
            SELECT users.id, users.username, users.email, users.active, users.reset, users.role
            FROM usersrefreshtokens
            INNER JOIN users ON usersrefreshtokens.userid = users.id
            WHERE usersrefreshtokens.token = %s
              AND usersrefreshtokens.datetime
                  > NOW() - (%s * INTERVAL '1 second')
            LIMIT 1
        """
        result = conn.execute(
            query, (refresh_token, config.REFRESH_TOKEN_EXPIRATION_SEC)
        ).fetchone()
    except Exception as e:
        conn.rollback()
        print(f"Error during refresh token query: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"data": None, "error": "Internal Server Error"},
        )
    finally:
        conn.close()

    if not result:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"data": None, "error": "Invalid refresh token. Please log in."},
        )

    new_token = jwt.encode(
        {
            "id": result[0],
            "username": result[1],
            "email": result[2],
            "active": result[3],
            "reset": result[4],
            "role": _role_value(result[5]),
            "exp": datetime.now(timezone.utc)
            + timedelta(hours=config.ACCESS_TOKEN_EXPIRATION_SEC / 3600),
        },
        config.JWT_SECRET_KEY,
        algorithm=config.JWT_ALGORITHM,
    )

    refresh_response = JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "data": "Token refreshed successfully",
            "error": None,
        },
    )

    refresh_response.set_cookie(
        key=config.ACCESS_COOKIE_NAME,
        value=new_token,
        max_age=config.ACCESS_TOKEN_EXPIRATION_SEC,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="strict",
        path="/",
    )

    return refresh_response


@auth_router.get("/me")
def get_current_user(
    _user: dict[str, object] = Depends(_require_authentication),
) -> dict[str, object]:
    """Returns the currently authenticated user."""

    if not _user:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"data": None, "error": "User is not authenticated"},
        )

    conn = sql_database.get_connection()
    try:
        query = "SELECT id, username, email, reset, active, role FROM users WHERE id = %s LIMIT 1"
        result = conn.execute(query, (_user.get("id", ""),)).fetchone()
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error during user query. {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"data": None, "error": "Internal Server Error"},
        )
    finally:
        conn.close()

    if not result:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"data": None, "error": "User not found"},
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "data": {
                "id": result[0],
                "username": result[1],
                "email": result[2],
                "reset": result[3],
                "active": result[4],
                "role": _role_value(result[5]),
            },
            "error": None,
        },
    )


@auth_router.post("/logout")
def logout(
    refresh_token: str | None = Cookie(default=None, alias=config.REFRESH_COOKIE_NAME),
) -> dict[str, str]:
    if refresh_token:
        conn = sql_database.get_connection()
        try:
            query = "DELETE FROM usersrefreshtokens WHERE token = %s"
            conn.execute(query, (refresh_token,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Error deleting refresh token: {e}")
        finally:
            conn.close()

    response = JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"data": "Logged out successfully", "error": None},
    )
    response.delete_cookie(key=config.ACCESS_COOKIE_NAME, path="/")
    response.delete_cookie(key=config.REFRESH_COOKIE_NAME, path="/api/auth/refresh")

    return response
