"""
db_copy.py — copy the whole app database to another one (``python manage.py db copy --to URL``).

The usual move is SQLite → Postgres when a pilot outgrows a single file. The target gets the
schema from the migrations (never the demo seed), then every row of every table, parents before
children, in one transaction: if anything fails nothing is kept. Tables the app creates at run
time (the local vector store's ``rag_chunks`` / ``rag_collections``) are created from the
source's columns. Row counts are compared at the end.

Rows are copied as they are, so secrets stay encrypted with the same master key — the server
that uses the new database needs the same ``PIPESETS_MASTER_KEY`` (or KMS / Vault setting).
Uploaded files live in the data directory, not the database, and are not copied.
"""

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

from sqlalchemy import Boolean, Column, MetaData, Table, create_engine, func, inspect, select, text
from sqlalchemy.engine import Connection, Engine, make_url

import db

SKIP_TABLES = {"alembic_version"}
BATCH = 500


class CopyError(RuntimeError):
    pass


@dataclass
class CopyReport:
    rows: Dict[str, int] = field(default_factory=dict)        # table -> rows copied
    created: List[str] = field(default_factory=list)          # tables created from the source's columns
    orphans: Dict[str, int] = field(default_factory=dict)     # table -> rows skipped (parent missing)

    @property
    def total(self) -> int:
        return sum(self.rows.values())


def _safe(url: str) -> str:
    return make_url(url).render_as_string(hide_password=True)


def _app_tables(engine: Engine) -> List[str]:
    return [t for t in inspect(engine).get_table_names() if t not in SKIP_TABLES]


def _portable(table: Table) -> Table:
    """The table's columns and primary key for another database: Postgres reflects defaults as
    ``'{}'::text``, which SQLite can't read, so a literal default loses its cast."""
    cols = []
    for c in table.columns:
        default = None
        if c.server_default is not None:
            arg = getattr(c.server_default, "arg", None)
            raw = "" if arg is None else str(getattr(arg, "text", arg))
            default = text(re.sub(r"::[\w ]+(\[\])?$", "", raw)) if raw else None
        cols.append(Column(c.name, c.type, primary_key=c.primary_key, nullable=c.nullable,
                           server_default=default))
    return Table(table.name, MetaData(), *cols)


def _row_counts(conn: Connection, meta: MetaData, tables) -> Dict[str, int]:
    return {t: conn.execute(select(func.count()).select_from(meta.tables[t])).scalar() for t in tables}


def _orphan_filter(conn: Connection, table, src_meta: MetaData) -> Tuple[Optional[object], int]:
    """A WHERE clause keeping only rows whose foreign keys point at existing parents (SQLite
    doesn't enforce them, Postgres does), and how many rows it drops."""
    from sqlalchemy import and_, exists, or_

    conditions = []
    for fk in table.foreign_key_constraints:
        parent = src_meta.tables.get(fk.referred_table.name)
        if parent is None:
            continue
        cols = [table.c[c.name] for c in fk.columns if c.name in table.c]
        refs = [parent.c[e.column.name] for e in fk.elements if e.column.name in parent.c]
        if len(cols) != len(refs) or not cols:
            continue
        match = exists().where(and_(*(r == c for r, c in zip(refs, cols))))
        conditions.append(or_(*(c.is_(None) for c in cols), match))
    if not conditions:
        return None, 0
    keep = and_(*conditions)
    total = conn.execute(select(func.count()).select_from(table)).scalar()
    kept = conn.execute(select(func.count()).select_from(table).where(keep)).scalar()
    return keep, total - kept


def copy_database(source_url: str, target_url: str, *, overwrite: bool = False,
                  skip_orphans: bool = False, progress: Callable[[str], None] = lambda _: None) -> CopyReport:
    if make_url(source_url) == make_url(target_url):
        raise CopyError("Source and target are the same database.")
    src = create_engine(source_url)
    dst = create_engine(target_url, pool_pre_ping=True)
    try:
        status = db.schema_status(src)
        if status["pending"]:
            raise CopyError(f"The source database is at {status['current'] or 'no revision'}, not "
                            f"{status['head']}: run `python manage.py db setup` against it first.")

        existing = _app_tables(dst)
        if existing:
            dst_meta = MetaData()
            dst_meta.reflect(bind=dst, only=existing)
            with dst.connect() as conn:
                filled = {t: n for t, n in _row_counts(conn, dst_meta, existing).items() if n}
            if filled and not overwrite:
                names = ", ".join(f"{t} ({n})" for t, n in sorted(filled.items())[:6])
                raise CopyError(f"The target already has data: {names}{' …' if len(filled) > 6 else ''}. "
                                f"Use an empty database, or --overwrite to replace it.")

        progress(f"Creating the schema in {_safe(target_url)}")
        from alembic import command
        cfg = db._alembic_config()
        with db.migration_connection(dst) as conn, conn.begin():
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")

        src_meta = MetaData()
        src_meta.reflect(bind=src, only=_app_tables(src))
        report = CopyReport()
        missing = [t for t in src_meta.sorted_tables if t.name not in set(_app_tables(dst))]
        for t in missing:
            _portable(t).create(bind=dst)   # e.g. rag_chunks: made at run time, not by a migration
            report.created.append(t.name)
        dst_meta = MetaData()
        dst_meta.reflect(bind=dst, only=_app_tables(dst))

        order = [t for t in dst_meta.sorted_tables if t.name in src_meta.tables]
        with src.connect() as read, dst.begin() as write:
            # The migrations leave seed-free tables, but --overwrite may meet data: children first
            for t in reversed(dst_meta.sorted_tables):
                write.execute(t.delete())
            for target in order:
                source = src_meta.tables[target.name]
                cols = [c.name for c in target.columns if c.name in source.c]
                booleans: Set[str] = {c.name for c in target.columns if isinstance(c.type, Boolean)}
                keep, dropped = _orphan_filter(read, source, src_meta)
                if dropped:
                    if not skip_orphans:
                        raise CopyError(f"{dropped} row(s) in {target.name} point at rows that no longer exist "
                                        f"(SQLite doesn't enforce foreign keys; the target does). "
                                        f"Rerun with --skip-orphans to leave them out.")
                    report.orphans[target.name] = dropped
                query = select(*(source.c[c] for c in cols))
                if keep is not None and dropped:
                    query = query.where(keep)
                result = read.execution_options(stream_results=True).execute(query)
                copied = 0
                while True:
                    batch = result.fetchmany(BATCH)
                    if not batch:
                        break
                    rows = [{c: (bool(v) if c in booleans and v is not None else v) for c, v in zip(cols, r)}
                            for r in batch]
                    write.execute(target.insert(), rows)
                    copied += len(rows)
                report.rows[target.name] = copied
                if copied:
                    progress(f"  {target.name}: {copied}")

            got = _row_counts(write, dst_meta, [t.name for t in order])
            wrong = {t: (report.rows[t], n) for t, n in got.items() if n != report.rows[t]}
            if wrong:
                raise CopyError(f"Row counts differ after the copy (copied, found): {wrong}")
        return report
    finally:
        src.dispose()
        dst.dispose()
