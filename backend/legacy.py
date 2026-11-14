"""Reprise des données d'une ancienne installation (base sans comptes) dans le PREMIER compte créé."""
import sqlite3

from .config import DB_PATH

LEGACY_TABLES = ("assets", "pending_orders", "sold_assets", "savings", "settings")

# Répartition qui était codée en dur avant : reprise telle quelle pour ne pas changer le comportement.
DEFAULT_TARGETS = [
    {"label": "Monde", "tickers": ["DCAM.PA", "WPEA.PA"], "buy": "DCAM.PA", "pct": 65},
    {"label": "Nasdaq", "tickers": ["PNAS.PA"], "buy": "PNAS.PA", "pct": 20},
    {"label": "Asie émergente", "tickers": ["PAASI.PA"], "buy": "PAASI.PA", "pct": 15},
]


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def has_legacy(conn):
    present = _tables(conn)
    if "assets" not in present:
        return False
    return any(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in LEGACY_TABLES if t in present)


def import_into(conn, store):
    """Copie (en les chiffrant) les anciennes données dans le magasin de l'utilisateur. Retourne True si quelque chose a été repris."""
    if not has_legacy(conn):
        return False
    present = _tables(conn)
    for ticker, buy_price, qty in conn.execute("SELECT ticker, buy_price, qty FROM assets"):
        store.add("asset", {"ticker": ticker, "buy_price": buy_price, "qty": qty})
    if "pending_orders" in present:
        for ticker, qty, limit_price in conn.execute("SELECT ticker, qty, limit_price FROM pending_orders"):
            store.add("pending", {"ticker": ticker, "qty": qty, "limit_price": limit_price})
    if "sold_assets" in present:
        for ticker, qty, bp, sp, gl, date in conn.execute("SELECT ticker, qty, buy_price, sell_price, realized_gl, sold_date FROM sold_assets"):
            store.add("sold", {"ticker": ticker, "qty": qty, "buy_price": bp, "sell_price": sp, "realized_gl": gl, "sold_date": date})
    if "savings" in present:
        for bank, name, balance, rate, earned in conn.execute("SELECT bank, name, balance, rate, earned_interest FROM savings"):
            store.add("saving", {"bank": bank, "name": name, "balance": balance, "rate": rate, "earned_interest": earned or 0.0})
    settings = {}
    if "settings" in present:
        legacy = dict(conn.execute("SELECT key, value FROM settings").fetchall())
        for key in ("monthly_budget", "total_deposited"):
            if key in legacy:
                settings[key] = legacy[key]
    held = {a[0] for a in conn.execute("SELECT ticker FROM assets")}
    if any(t in held for g in DEFAULT_TARGETS for t in g["tickers"]):
        settings["targets"] = DEFAULT_TARGETS
    store.add("settings", settings)
    return True


def purge():
    """Supprime les anciennes tables EN CLAIR et réécrit le fichier (VACUUM + secure_delete) : plus aucune trace lisible.
    À appeler APRÈS la validation de l'import."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.execute("PRAGMA secure_delete=ON")
        for table in LEGACY_TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
        conn.execute("VACUUM")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
