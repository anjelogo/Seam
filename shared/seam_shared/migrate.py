import logging
from pathlib import Path

import psycopg

from seam_shared.db import url

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
log = logging.getLogger("seam.migrate")


def main() -> None:
    with psycopg.connect(url(), autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(hashtext('seam.migrate'))")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        done = {version for (version,) in conn.execute("SELECT version FROM schema_migrations")}
        pending = [p for p in sorted(MIGRATIONS.glob("*.sql")) if p.stem not in done]
        for path in pending:
            with conn.transaction():
                conn.execute(path.read_text())
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,))
            log.info("applied %s", path.name)
        log.info("up to date: %d applied now, %d before", len(pending), len(done))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    main()
