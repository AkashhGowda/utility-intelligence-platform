from __future__ import annotations

from typing import Any

import pandas as pd
import psycopg2

from database import get_config, set_config
from services.db import get_connection


def _query_df(query: str, params: tuple[Any, ...] = ()) -> pd.DataFrame:
    conn = get_connection()
    try:
        return pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()


def _query_rows(query: str, params: tuple[Any, ...] = ()) -> list[tuple]:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall()
    finally:
        conn.close()


def _require_admin(current_user: dict[str, Any] | None) -> None:
    """Require an authenticated ADMIN account for administrative writes."""
    if not current_user or not current_user.get("logged_in"):
        raise PermissionError("You must be signed in to manage locations.")

    username = str(current_user.get("username") or "").strip()
    if not username or str(current_user.get("user_role", "")).upper() != "ADMIN":
        raise PermissionError("Only authenticated ADMIN users may manage locations.")

    rows = _query_rows(
        """
        SELECT ut.type_code
        FROM platform.users u
        JOIN platform.user_types ut ON ut.user_type_id = u.user_type_id
        WHERE u.username = %s AND u.is_active = TRUE
        """,
        (username,),
    )
    if not rows or str(rows[0][0]).upper() != "ADMIN":
        raise PermissionError("Only authenticated ADMIN users may manage locations.")


def _validate_location_fields(location_code: str, location_name: str, plant_id: int) -> tuple[str, str, int]:
    location_code = str(location_code or "").strip()
    location_name = str(location_name or "").strip()
    if not location_code:
        raise ValueError("Location code is required.")
    if not location_name:
        raise ValueError("Location name is required.")
    try:
        plant_id = int(plant_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("A valid plant is required.") from exc
    return location_code, location_name, plant_id


def get_locations() -> pd.DataFrame:
    """Return the platform location master data, including active state."""
    return _query_df(
        """
        SELECT l.location_id AS id,
               l.location_code AS code,
               l.location_name AS name,
               l.plant_id,
               p.plant_name AS plant,
               l.is_active AS active,
               l.created_at
        FROM platform.locations l
        LEFT JOIN platform.plants p ON p.plant_id = l.plant_id
        ORDER BY l.location_name
        """
    )


def get_solar_locations() -> pd.DataFrame:
    """Return solar asset locations, separate from platform login locations."""
    return _query_df(
        """
        SELECT location_id AS id, location_name AS name,
               site_location, plant_name, line_name,
               created_date, modified_date,
               EXISTS (
                   SELECT 1 FROM public.solar_daily_summary d
                   WHERE d.location_id = s.location_id
               ) OR EXISTS (
                   SELECT 1 FROM public.solar_time_logs t
                   WHERE t.location_id = s.location_id
               ) AS has_history
        FROM public.solar_locations s
        ORDER BY location_id
        """
    )


def _validate_solar_location_fields(location_id: Any, location_name: str) -> tuple[int, str]:
    location_id = _as_int(location_id, "solar location ID")
    location_name = str(location_name or "").strip()
    if not location_name:
        raise ValueError("Solar location name is required.")
    if location_id <= 0:
        raise ValueError("Solar location ID must be positive.")
    return location_id, location_name


def add_solar_location(
    current_user: dict[str, Any], location_id: Any, location_name: str,
    site_location: str, plant_name: str, line_name: str,
) -> int:
    """Create a solar asset location using the existing public table."""
    _require_admin(current_user)
    location_id, location_name = _validate_solar_location_fields(location_id, location_name)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1 FROM public.solar_locations
                WHERE location_id = %s OR LOWER(location_name) = LOWER(%s)
                """,
                (location_id, location_name),
            )
            if cursor.fetchone() is not None:
                raise ValueError("That solar location ID or name already exists.")
            cursor.execute(
                """
                INSERT INTO public.solar_locations
                    (location_id, location_name, site_location, plant_name, line_name)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (location_id, location_name, str(site_location or "").strip() or None,
                 str(plant_name or "").strip() or None, str(line_name or "").strip() or None),
            )
        conn.commit()
        return location_id
    except psycopg2.errors.UniqueViolation as exc:
        conn.rollback()
        raise ValueError("That solar location ID already exists.") from exc
    finally:
        conn.close()


def update_solar_location(
    current_user: dict[str, Any], location_id: Any, location_name: str,
    site_location: str, plant_name: str, line_name: str,
) -> None:
    """Update solar asset metadata while preserving historical references."""
    _require_admin(current_user)
    location_id, location_name = _validate_solar_location_fields(location_id, location_name)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE public.solar_locations
                SET location_name = %s, site_location = %s, plant_name = %s,
                    line_name = %s, modified_date = CURRENT_TIMESTAMP,
                    modified_by = %s
                WHERE location_id = %s
                """,
                (location_name, str(site_location or "").strip() or None,
                 str(plant_name or "").strip() or None, str(line_name or "").strip() or None,
                 str(current_user.get("username") or "admin"), location_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Solar location was not found.")
        conn.commit()
    except psycopg2.errors.UniqueViolation as exc:
        conn.rollback()
        raise ValueError("That solar location name already exists.") from exc
    finally:
        conn.close()


def delete_solar_location(current_user: dict[str, Any], location_id: Any) -> None:
    """Delete only an unused solar asset; historical locations must be retained."""
    _require_admin(current_user)
    location_id = _as_int(location_id, "solar location")
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM public.solar_daily_summary WHERE location_id = %s),
                    (SELECT COUNT(*) FROM public.solar_time_logs WHERE location_id = %s)
                """,
                (location_id, location_id),
            )
            daily_count, telemetry_count = cursor.fetchone()
            if daily_count or telemetry_count:
                raise ValueError(
                    "This solar location has historical monitoring data and cannot be deleted. "
                    "The current schema has no inactive flag; preserve it rather than removing history."
                )
            cursor.execute("DELETE FROM public.solar_locations WHERE location_id = %s", (location_id,))
            if cursor.rowcount != 1:
                raise ValueError("Solar location was not found.")
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        raise
    finally:
        conn.close()


def add_location(
    current_user: dict[str, Any],
    location_code: str,
    location_name: str,
    plant_id: int,
) -> int:
    """Create a platform location without altering historical records."""
    _require_admin(current_user)
    location_code, location_name, plant_id = _validate_location_fields(
        location_code, location_name, plant_id
    )
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO platform.locations (location_code, location_name, plant_id, is_active)
                VALUES (%s, %s, %s, TRUE)
                RETURNING location_id
                """,
                (location_code, location_name, plant_id),
            )
            location_id = int(cursor.fetchone()[0])
        conn.commit()
        return location_id
    except psycopg2.errors.UniqueViolation as exc:
        conn.rollback()
        raise ValueError("That location code already exists.") from exc
    except psycopg2.errors.ForeignKeyViolation as exc:
        conn.rollback()
        raise ValueError("The selected plant does not exist.") from exc
    finally:
        conn.close()


def update_location(
    current_user: dict[str, Any],
    location_id: int,
    location_code: str,
    location_name: str,
    plant_id: int,
) -> None:
    """Update editable location fields while preserving the primary key."""
    _require_admin(current_user)
    location_code, location_name, plant_id = _validate_location_fields(
        location_code, location_name, plant_id
    )
    try:
        location_id = int(location_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid location ID.") from exc

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE platform.locations
                SET location_code = %s, location_name = %s, plant_id = %s
                WHERE location_id = %s
                """,
                (location_code, location_name, plant_id, location_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Location was not found.")
        conn.commit()
    except psycopg2.errors.UniqueViolation as exc:
        conn.rollback()
        raise ValueError("That location code already exists.") from exc
    except psycopg2.errors.ForeignKeyViolation as exc:
        conn.rollback()
        raise ValueError("The selected plant does not exist.") from exc
    finally:
        conn.close()


def _set_location_active(current_user: dict[str, Any], location_id: int, active: bool) -> None:
    _require_admin(current_user)
    try:
        location_id = int(location_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid location ID.") from exc

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE platform.locations SET is_active = %s WHERE location_id = %s",
                (active, location_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Location was not found.")
        conn.commit()
    finally:
        conn.close()


def activate_location(current_user: dict[str, Any], location_id: int) -> None:
    _set_location_active(current_user, location_id, True)


def deactivate_location(current_user: dict[str, Any], location_id: int) -> None:
    _set_location_active(current_user, location_id, False)


def _as_int(value: Any, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"A valid {field_name} is required.") from exc


def create_user(
    current_user: dict[str, Any],
    employee_id: str,
    username: str,
    full_name: str,
    email: str,
    password: str,
    user_type_id: int,
    plant_id: int,
    location_id: int,
    application_ids: list[int],
) -> int:
    """Create a user and its access mappings using the existing platform schema."""
    _require_admin(current_user)
    employee_id = str(employee_id or "").strip()
    username = str(username or "").strip()
    full_name = str(full_name or "").strip()
    email = str(email or "").strip()
    if not employee_id:
        raise ValueError("Employee ID is required.")
    if not username:
        raise ValueError("Username is required.")
    if not full_name:
        raise ValueError("Full name is required.")
    if not email or "@" not in email:
        raise ValueError("A valid email address is required.")
    if len(str(password or "")) < 8:
        raise ValueError("Password must contain at least 8 characters.")

    user_type_id = _as_int(user_type_id, "user type")
    plant_id = _as_int(plant_id, "plant")
    location_id = _as_int(location_id, "location")
    application_ids = sorted({_as_int(value, "application") for value in application_ids})
    if not application_ids:
        raise ValueError("Assign at least one application to the user.")

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO platform.users
                    (employee_id, username, full_name, email, password_hash,
                     user_type_id, plant_id, location_id, is_active)
                VALUES
                    (%s, %s, %s, %s, crypt(%s, gen_salt('bf')), %s, %s, %s, TRUE)
                RETURNING user_id
                """,
                (employee_id, username, full_name, email, password, user_type_id, plant_id, location_id),
            )
            user_id = int(cursor.fetchone()[0])
            for index, application_id in enumerate(application_ids):
                cursor.execute(
                    """
                    INSERT INTO platform.user_applications (user_id, application_id, is_default)
                    VALUES (%s, %s, %s)
                    """,
                    (user_id, application_id, index == 0),
                )
        conn.commit()
        return user_id
    except psycopg2.errors.UniqueViolation as exc:
        conn.rollback()
        raise ValueError("That username or application assignment already exists.") from exc
    except psycopg2.errors.ForeignKeyViolation as exc:
        conn.rollback()
        raise ValueError("One of the selected user, plant, location, or application values no longer exists.") from exc
    finally:
        conn.close()


def update_user(
    current_user: dict[str, Any],
    user_id: int,
    employee_id: str,
    username: str,
    full_name: str,
    email: str,
    user_type_id: int,
    plant_id: int,
    location_id: int,
) -> None:
    """Update editable identity and assignment fields without changing the password."""
    _require_admin(current_user)
    user_id = _as_int(user_id, "user")
    employee_id = str(employee_id or "").strip()
    username = str(username or "").strip()
    full_name = str(full_name or "").strip()
    email = str(email or "").strip()
    if not employee_id or not username or not full_name:
        raise ValueError("Employee ID, username, and full name are required.")
    if not email or "@" not in email:
        raise ValueError("A valid email address is required.")

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE platform.users
                SET employee_id = %s, username = %s, full_name = %s, email = %s,
                    user_type_id = %s, plant_id = %s, location_id = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s
                """,
                (employee_id, username, full_name, email, _as_int(user_type_id, "user type"),
                 _as_int(plant_id, "plant"), _as_int(location_id, "location"), user_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("User was not found.")
        conn.commit()
    except psycopg2.errors.UniqueViolation as exc:
        conn.rollback()
        raise ValueError("That employee ID, username, or email already exists.") from exc
    except psycopg2.errors.ForeignKeyViolation as exc:
        conn.rollback()
        raise ValueError("One of the selected user, plant, or location values no longer exists.") from exc
    finally:
        conn.close()


def set_user_active(current_user: dict[str, Any], user_id: int, active: bool) -> None:
    """Activate or deactivate a user without deleting authentication history."""
    _require_admin(current_user)
    user_id = _as_int(user_id, "user")
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE platform.users
                SET is_active = %s, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s
                """,
                (bool(active), user_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("User was not found.")
        conn.commit()
    finally:
        conn.close()


def reset_user_password(current_user: dict[str, Any], user_id: int, password: str) -> None:
    """Replace a user's password using PostgreSQL crypt, never storing plaintext."""
    _require_admin(current_user)
    user_id = _as_int(user_id, "user")
    password = str(password or "")
    if len(password) < 8:
        raise ValueError("Password must contain at least 8 characters.")
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE platform.users
                SET password_hash = crypt(%s, gen_salt('bf')),
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s
                """,
                (password, user_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("User was not found.")
        conn.commit()
    finally:
        conn.close()


def replace_user_applications(
    current_user: dict[str, Any], user_id: int, application_ids: list[int]
) -> None:
    """Replace a user's application access without changing the user identity."""
    _require_admin(current_user)
    user_id = _as_int(user_id, "user")
    application_ids = sorted({_as_int(value, "application") for value in application_ids})
    if not application_ids:
        raise ValueError("Assign at least one application to the user.")

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM platform.users WHERE user_id = %s", (user_id,))
            if cursor.fetchone() is None:
                raise ValueError("User was not found.")
            cursor.execute(
                "SELECT application_id FROM platform.applications WHERE application_id = ANY(%s)",
                (application_ids,),
            )
            if len(cursor.fetchall()) != len(application_ids):
                raise ValueError("One or more selected applications were not found.")
            cursor.execute(
                "DELETE FROM platform.user_applications WHERE user_id = %s", (user_id,)
            )
            for index, application_id in enumerate(application_ids):
                cursor.execute(
                    """
                    INSERT INTO platform.user_applications (user_id, application_id, is_default)
                    VALUES (%s, %s, %s)
                    """,
                    (user_id, application_id, index == 0),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_admin_snapshot() -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "plants": pd.DataFrame(),
        "locations": pd.DataFrame(),
        "users": pd.DataFrame(),
        "user_types": pd.DataFrame(),
        "applications": pd.DataFrame(),
        "access": pd.DataFrame(),
        "database_error": None,
    }

    queries = {
        "plants": """
            SELECT plant_id AS id, plant_name AS name
            FROM platform.plants
            ORDER BY plant_name
        """,
        "locations": """
            SELECT l.location_id AS id, l.location_code AS code,
                   l.location_name AS name, l.plant_id,
                   p.plant_name AS plant, l.is_active AS active,
                   l.created_at
            FROM platform.locations l
            LEFT JOIN platform.plants p ON p.plant_id = l.plant_id
            ORDER BY l.location_name
        """,
        "users": """
             SELECT u.user_id AS id, u.employee_id, u.username, u.full_name AS name,
                 u.email,
                   ut.type_code AS user_type, p.plant_name AS plant,
                 l.location_name AS location, u.user_type_id, u.plant_id,
                 u.location_id, u.is_active AS active, u.created_at, u.updated_at
            FROM platform.users u
            JOIN platform.user_types ut ON ut.user_type_id = u.user_type_id
            LEFT JOIN platform.plants p ON p.plant_id = u.plant_id
            LEFT JOIN platform.locations l ON l.location_id = u.location_id
            ORDER BY u.username
        """,
        "user_types": """
            SELECT user_type_id AS id, type_code AS code
            FROM platform.user_types
            ORDER BY type_code
        """,
        "applications": """
            SELECT application_id AS id, application_name AS name,
                   application_code AS code, base_route AS route,
                   is_active AS enabled
            FROM platform.applications
            ORDER BY application_name
        """,
        "access": """
            SELECT u.username, a.application_code AS code,
                   a.application_name AS application, ua.is_default
            FROM platform.user_applications ua
            JOIN platform.users u ON u.user_id = ua.user_id
            JOIN platform.applications a ON a.application_id = ua.application_id
            ORDER BY u.username, a.application_name
        """,
    }

    try:
        for key, query in queries.items():
            snapshot[key] = _query_df(query)
    except Exception as exc:
        snapshot["database_error"] = str(exc)

    if snapshot["locations"].empty:
        try:
            snapshot["locations"] = _query_df(
                """
                SELECT location_id AS id, location_name AS name,
                       plant_name AS plant, TRUE AS active
                FROM solar_locations
                ORDER BY location_name
                """
            )
        except Exception:
            pass

    return snapshot


def get_login_options() -> dict[str, list[str]]:
    """Return login choices from the existing platform master tables."""
    options = {"plants": [], "locations": [], "user_types": []}
    try:
        options["plants"] = _query_df(
            "SELECT plant_name AS name FROM platform.plants ORDER BY plant_name"
        )["name"].dropna().astype(str).tolist()
        options["locations"] = _query_df(
            "SELECT location_name AS name FROM platform.locations WHERE is_active = TRUE ORDER BY location_name"
        )["name"].dropna().astype(str).tolist()
        options["user_types"] = _query_df(
            "SELECT type_code AS code FROM platform.user_types ORDER BY type_code"
        )["code"].dropna().astype(str).tolist()
    except Exception:
        pass
    return options


def get_platform_counts(snapshot: dict[str, Any]) -> dict[str, int]:
    return {
        "plants": len(snapshot["plants"]),
        "locations": len(snapshot["locations"]),
        "users": len(snapshot["users"]),
        "applications": len(snapshot["applications"]),
        "access": len(snapshot["access"]),
    }


def get_settings() -> dict[str, str]:
    try:
        rows = _query_rows(
            "SELECT config_key, config_value FROM admin_config ORDER BY config_key"
        )
        return {str(key): str(value) for key, value in rows}
    except Exception:
        return {}


def save_setting(key: str, value: Any) -> None:
    set_config(key, value, "Updated from Admin Control Center")


def database_is_online() -> bool:
    conn = get_connection()
    conn.close()
    return True
