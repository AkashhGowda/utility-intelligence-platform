from services.db import get_connection


def get_login_options():
    """Load login choices from the platform master tables."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT plant_name FROM platform.plants ORDER BY plant_name"
            )
            plants = [row[0] for row in cur.fetchall()]
            cur.execute(
                "SELECT location_name FROM platform.locations WHERE is_active = TRUE ORDER BY location_name"
            )
            locations = [row[0] for row in cur.fetchall()]
            cur.execute(
                "SELECT type_code FROM platform.user_types ORDER BY type_code"
            )
            user_types = [row[0] for row in cur.fetchall()]
        return {"plants": plants, "locations": locations, "user_types": user_types}
    finally:
        conn.close()


def authenticate_user(username, password, plant_name, location_name, user_type):
    conn = get_connection()

    try:
        cur = conn.cursor()

        query = """
            SELECT
                u.user_id,
                u.username,
                u.full_name,
                ut.type_code AS user_type,
                p.plant_name,
                l.location_name,
                u.password_hash,

                (
                    u.password_hash = crypt(%s, u.password_hash)
                ) AS password_valid

            FROM platform.users u

            JOIN platform.user_types ut
                ON u.user_type_id = ut.user_type_id

            LEFT JOIN platform.plants p
                ON u.plant_id = p.plant_id

            LEFT JOIN platform.locations l
                ON u.location_id = l.location_id

            WHERE u.username = %s
              AND u.is_active = TRUE
              AND p.plant_name = %s
              AND l.location_name = %s
              AND ut.type_code = %s;
        """

        cur.execute(
            query,
            (
                password,
                username,
                plant_name,
                location_name,
                user_type
            )
        )

        row = cur.fetchone()

        if not row:
            return None

        if not row[7]:
            return None

        return {
            "user_id": row[0],
            "username": row[1],
            "full_name": row[2],
            "user_type": row[3],
            "plant_name": row[4],
            "location_name": row[5]
        }

    finally:
        conn.close()


def get_user_applications(username):
    conn = get_connection()

    try:
        cur = conn.cursor()

        query = """
            SELECT
                u.user_id,
                u.username,
                u.full_name,
                ut.type_code AS user_type,
                p.plant_name,
                l.location_name,
                a.application_code,
                a.application_name,
                a.base_route,
                ua.is_default
            FROM platform.users u
            JOIN platform.user_types ut
                ON u.user_type_id = ut.user_type_id
            LEFT JOIN platform.plants p
                ON u.plant_id = p.plant_id
            LEFT JOIN platform.locations l
                ON u.location_id = l.location_id
            JOIN platform.user_applications ua
                ON u.user_id = ua.user_id
            JOIN platform.applications a
                ON ua.application_id = a.application_id
            WHERE u.username = %s
              AND u.is_active = TRUE
              AND a.is_active = TRUE
            ORDER BY ua.is_default DESC;
        """

        cur.execute(query, (username,))
        return cur.fetchall()

    finally:
        conn.close()
