import os
import sqlite3
from contextlib import contextmanager

from .config import DB_PATH


@contextmanager
def get_db_connection():
    """Ouvre une connexion, valide (commit) en sortie, annule en cas d'erreur, et FERME toujours la connexion
    (avant, `with sqlite3.connect()` ne fermait jamais la connexion)."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_db_connection() as conn:
        conn.execute("PRAGMA journal_mode=WAL")  # lectures/écritures concurrentes (requêtes + boucle de suivi)
        c = conn.cursor()
        # --- Comptes. Aucune donnée financière ici : seulement l'identifiant et des clés (elles-mêmes chiffrées).
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            is_admin INTEGER NOT NULL DEFAULT 0,
            salt BLOB NOT NULL, auth_hash BLOB NOT NULL, wrapped_dek BLOB NOT NULL,
            rec_salt BLOB NOT NULL, wrapped_dek_rec BLOB NOT NULL,
            created_at TEXT NOT NULL, last_login TEXT)''')
        # --- Données de chaque utilisateur : un enregistrement = un blob chiffré (AES-GCM) avec SA clé.
        c.execute('''CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind TEXT NOT NULL, blob BLOB NOT NULL, created_at TEXT NOT NULL)''')
        c.execute("CREATE INDEX IF NOT EXISTS idx_records_user_kind ON records(user_id, kind)")
        c.execute('''CREATE TABLE IF NOT EXISTS invites (
            code_hash TEXT PRIMARY KEY, created_by INTEGER, expires_at TEXT NOT NULL, used_by INTEGER)''')
        # --- Données de marché communes (aucune donnée personnelle)
        c.execute('''CREATE TABLE IF NOT EXISTS cache_store (key TEXT PRIMARY KEY, value TEXT, timestamp REAL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS gap_log (
            trade_date TEXT, ticker TEXT, slot TEXT, snap_ts TEXT,
            ref_price REAL, est_gap_pct REAL, est_price REAL, parts TEXT,
            open_price REAL, open_ts TEXT, p0905 REAL,
            PRIMARY KEY (trade_date, ticker, slot))''')
        conn.commit()
