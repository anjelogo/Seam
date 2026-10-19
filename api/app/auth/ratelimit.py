import random
from datetime import timedelta

from psycopg import Connection

LIMIT = 10
WINDOW = timedelta(minutes=15)


def blocked(conn: Connection, keys: list[str]) -> bool:
    """Records one attempt per key unless any key is already at LIMIT within WINDOW."""
    if random.random() < 0.05:
        conn.execute("DELETE FROM login_attempts WHERE at < now() - interval '1 day'")
    row = conn.execute(
        "SELECT coalesce(max(n), 0) AS n FROM (SELECT count(*) AS n FROM login_attempts WHERE key = ANY(%s) AND at > now() - %s GROUP BY key) t",
        (keys, WINDOW),
    ).fetchone()
    if row["n"] >= LIMIT:
        return True
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO login_attempts (key) VALUES (%s)", [(k,) for k in keys])
    return False
