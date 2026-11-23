from __future__ import annotations

from typing import Literal

import bcrypt
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from routers.auth import (
    ROLE_OPTIONS,
    USER_ROLE,
    _require_administrator,
    _require_authentication,
)
from core.storage import sql_database


class UserCreate(BaseModel):
    username: str = Field(min_length=1)
    email: str = Field(min_length=1)
    role: Literal[1, 2] = USER_ROLE


class UserUpdate(BaseModel):
    username: str = Field(min_length=1)
    email: str = Field(min_length=1)
    active: bool = Field()
    reset: bool = Field()
    role: Literal[1, 2]


class ResetPassword(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=1)
    confirm_password: str = Field(min_length=1)


users_router = APIRouter(prefix="/api/users")


def generate_random_password(length: int = 12) -> str:
    """Generates a random password of the specified length."""
    import random
    import string

    characters = string.ascii_letters + string.digits + string.punctuation
    return "".join(random.choice(characters) for _ in range(length))


@users_router.get("")
def get_users(_admin: dict[str, object] = Depends(_require_administrator)):
    """Returns a list of all users."""

    conn = sql_database.get_connection()

    try:
        query = "SELECT id, username, email, reset, active, role FROM users ORDER BY id"
        rows = conn.execute(query).fetchall()
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error fetching users: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "data": None,
                "error": "Error fetching users",
            },
        )
    finally:
        conn.close()

    users = [
        {
            "id": row[0],
            "username": row[1],
            "email": row[2],
            "reset": row[3],
            "active": row[4],
            "role": row[5],
        }
        for row in rows
    ]

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"data": users, "error": None},
    )


@users_router.get("/roles")
def get_roles(
    _admin: dict[str, object] = Depends(_require_administrator),
) -> JSONResponse:
    """Return the role values to assign."""
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"data": list(ROLE_OPTIONS), "error": None},
    )


@users_router.post("")
def create_user(
    user: UserCreate, _admin: dict[str, object] = Depends(_require_administrator)
) -> dict[str, str]:
    """Creates a new user."""

    conn = sql_database.get_connection()

    try:
        query = "SELECT id FROM users WHERE username = %s OR email = %s LIMIT 1"
        existing_user = conn.execute(query, (user.username, user.email)).fetchone()
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"Error checking duplicate user: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "data": None,
                "error": "Error creating user",
            },
        )

    if existing_user:
        conn.close()
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "data": None,
                "error": "User with that username or email already exists",
            },
        )

    new_password = generate_random_password(length=12)
    hashed_password = bcrypt.hashpw(
        new_password.encode("utf-8"), bcrypt.gensalt(rounds=12, prefix=b"2b")
    ).decode("utf-8")

    try:
        query = "INSERT INTO users (username, email, password, role) VALUES (%s, %s, %s, %s) RETURNING id"
        result = conn.execute(
            query, (user.username, user.email, hashed_password, user.role)
        ).fetchone()
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error creating user: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "data": None,
                "error": f"Error creating user",
            },
        )
    finally:
        conn.close()

    if not result:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"data": None, "error": "Failed to create user"},
        )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "data": "User created successfully. Temporary password: " + new_password,
            "error": None,
        },
    )


@users_router.put("/reset-password")
def reset_password(
    data: ResetPassword,
    _user: dict[str, object] = Depends(_require_authentication),
):
    """Resets the password for the authenticated user."""

    if not data:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"data": None, "error": "Request body is required"},
        )

    if data.new_password != data.confirm_password:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "data": None,
                "error": "New password and confirm password do not match",
            },
        )

    conn = sql_database.get_connection()
    id = int(_user["id"])

    try:
        query = "SELECT password FROM users WHERE id = %s LIMIT 1"
        result = conn.execute(query, (id,)).fetchone()
    except Exception as e:
        conn.rollback()
        conn.close()
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "data": None,
                "error": f"Error checking existing user: {e}",
            },
        )

    if not result or not bcrypt.checkpw(
        data.old_password.encode("utf-8"), result[0].encode("utf-8")
    ):
        conn.rollback()
        conn.close()
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"data": None, "error": "Old password is incorrect"},
        )

    hashed_new_password = bcrypt.hashpw(
        data.new_password.encode("utf-8"), bcrypt.gensalt(rounds=12, prefix=b"2b")
    ).decode("utf-8")

    try:
        query = "UPDATE users SET password = %s, reset = false WHERE id = %s"
        conn.execute(query, (hashed_new_password, id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "data": None,
                "error": f"Error updating password: {e}",
            },
        )
    finally:
        conn.close()

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"data": "Password updated successfully", "error": None},
    )


@users_router.put("/reset-password/user/{user_id}")
def reset_user_password(
    user_id: int,
    _admin: dict[str, object] = Depends(_require_administrator),
) -> dict[str, str]:
    """Resets the password for a user by ID."""

    conn = sql_database.get_connection()

    try:
        query = "SELECT id FROM users WHERE id = %s LIMIT 1"
        existing_user = conn.execute(query, (user_id,)).fetchone()
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"Error checking existing user: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "data": None,
                "error": "Error resetting user password",
            },
        )

    if not existing_user:
        conn.close()
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"data": None, "error": "User not found"},
        )

    new_password = generate_random_password(length=12)
    hashed_new_password = bcrypt.hashpw(
        new_password.encode("utf-8"), bcrypt.gensalt(rounds=12, prefix=b"2b")
    ).decode("utf-8")

    try:
        query = "UPDATE users SET password = %s, reset = true WHERE id = %s"
        conn.execute(query, (hashed_new_password, user_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error resetting user password: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "data": None,
                "error": "Error resetting user password",
            },
        )
    finally:
        conn.close()

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "data": f"User password has been reset successfully. Temporary password: {new_password}",
            "error": None,
        },
    )


@users_router.put("/{user_id}")
def update_user(
    user_id: int,
    user: UserUpdate,
    _admin: dict[str, object] = Depends(_require_administrator),
) -> dict[str, str]:
    """Updates a user's information by ID."""

    conn = sql_database.get_connection()

    try:
        query = "SELECT id FROM users WHERE id = %s LIMIT 1"
        existing_user = conn.execute(query, (user_id,)).fetchone()
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"Error checking existing user: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "data": None,
                "error": "Error updating user",
            },
        )

    if not existing_user:
        conn.close()
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"data": None, "error": "User not found"},
        )

    try:
        query = "SELECT id FROM users WHERE (username = %s OR email = %s) AND id != %s LIMIT 1"
        duplicate_user = conn.execute(
            query,
            (
                user.username,
                user.email,
                user_id,
            ),
        ).fetchone()
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"Error checking for duplicate user: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "data": None,
                "error": "Error updating user",
            },
        )

    if duplicate_user:
        conn.close()
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "data": None,
                "error": "Another user with that username or email already exists",
            },
        )

    try:
        query = "UPDATE users SET username = %s, email = %s, active = %s, reset = %s, role = %s WHERE id = %s"
        conn.execute(
            (
                user.username,
                user.email,
                user.active,
                user.reset,
                user.role,
                user_id,
            )
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error updating user: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "data": None,
                "error": "Error updating user",
            },
        )
    finally:
        conn.close()

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"data": "User updated successfully", "error": None},
    )


@users_router.delete("/{user_id}")
def delete_user(
    user_id: int, _admin: dict[str, object] = Depends(_require_administrator)
) -> dict[str, str]:
    """Deletes a user by ID."""

    conn = sql_database.get_connection()

    try:
        query = "DELETE FROM users WHERE id = %s RETURNING id"
        result = conn.execute(query, (user_id,)).fetchone()
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error deleting user: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "data": None,
                "error": "Error deleting user",
            },
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
        content={"data": "User deleted successfully", "error": None},
    )
