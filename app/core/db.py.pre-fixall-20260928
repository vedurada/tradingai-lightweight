import sqlite3, os
DB_PATH = '/opt/tradingai/database/tradingai.db'
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn
