"""Consistent read-only snapshot of the live database.

The source database is opened with a read-only SQLite URI and copied with the
SQLite backup API, which yields a transactionally consistent image even while the
live service is writing. The source file and its WAL are never written to.
"""
from __future__ import annotations

import datetime
import hashlib
import os
import sqlite3


def sha256_file(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def file_metadata(path: str) -> dict:
    st = os.stat(path)
    return {
        'path': path,
        'size_bytes': st.st_size,
        'mtime': datetime.datetime.fromtimestamp(
            st.st_mtime, datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        ).isoformat(),
    }


def create_snapshot(src_db: str, out_path: str) -> dict:
    """Copy `src_db` into `out_path` using the SQLite backup API.

    The source connection is read-only; the destination is a new file. Returns
    metadata for the manifest.
    """
    if os.path.exists(out_path):
        raise FileExistsError(f'snapshot already exists: {out_path}')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    src_meta = file_metadata(src_db)
    src = sqlite3.connect(f'file:{src_db}?mode=ro', uri=True, timeout=60)
    try:
        dst = sqlite3.connect(out_path, timeout=60)
        try:
            src.backup(dst)
            dst.commit()
        finally:
            dst.close()
    finally:
        src.close()
    out_meta = file_metadata(out_path)
    return {
        'snapshot_path': out_path,
        'snapshot_sha256': sha256_file(out_path),
        'snapshot_size_bytes': out_meta['size_bytes'],
        'snapshot_created_at': datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        ).isoformat(),
        'source': src_meta,
        'source_sha256_at_snapshot': sha256_file(src_db),
        'method': 'sqlite3 Connection.backup from a mode=ro source (consistent image)',
    }


def snapshot_meta(snapshot_path: str, src_db: str) -> dict:
    """Metadata for an existing snapshot (used when the study is re-run)."""
    out = file_metadata(snapshot_path)
    src = file_metadata(src_db)
    return {
        'snapshot_path': snapshot_path,
        'snapshot_sha256': sha256_file(snapshot_path),
        'snapshot_size_bytes': out['size_bytes'],
        'snapshot_created_at': out['mtime'],
        'source': src,
        'source_sha256_at_snapshot': sha256_file(src_db),
        'method': 'reused existing snapshot (not re-copied)',
    }


def snapshot_sessions(db_path: str, instruments=('NIFTY', 'BANKNIFTY')) -> dict:
    """Session list per instrument inside the snapshot (for the manifest)."""
    conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=30)
    try:
        out = {}
        for inst in instruments:
            rows = conn.execute(
                'SELECT DISTINCT substr(timestamp,1,10) AS d FROM market_candles_5m '
                'WHERE instrument_id=? ORDER BY 1', (inst,)).fetchall()
            out[inst] = [r[0] for r in rows]
        return out
    finally:
        conn.close()
