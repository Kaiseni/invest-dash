"""Accès aux données d'UN utilisateur : tout est chiffré/déchiffré ici avec sa clé de données (DEK)."""
import datetime
from contextlib import contextmanager

from .crypto import seal_json, unseal_json
from .db import get_db_connection

KINDS = ("asset", "pending", "sold", "saving", "alt", "altsold", "settings")


class Store:
    def __init__(self, user_id, dek, conn=None):
        self.user_id = user_id
        self._dek = dek
        self._conn = conn

    @contextmanager
    def _db(self):
        if self._conn is not None:
            yield self._conn
        else:
            with get_db_connection() as conn:
                yield conn

    def _aad(self, kind):
        # lie le blob à son propriétaire ET à son type : impossible de le déplacer chez un autre utilisateur
        return f"{self.user_id}:{kind}".encode()

    def rows(self, kind):
        """[(id, dict), ...] dans l'ordre de création."""
        with self._db() as conn:
            found = conn.execute("SELECT id, blob FROM records WHERE user_id=? AND kind=? ORDER BY id", (self.user_id, kind)).fetchall()
        return [(rid, unseal_json(self._dek, blob, self._aad(kind))) for rid, blob in found]

    def add(self, kind, obj):
        with self._db() as conn:
            cur = conn.execute("INSERT INTO records (user_id, kind, blob, created_at) VALUES (?,?,?,?)",
                               (self.user_id, kind, seal_json(self._dek, obj, self._aad(kind)),
                                datetime.datetime.now(datetime.timezone.utc).isoformat()))
            return cur.lastrowid

    def update(self, kind, rid, obj):
        with self._db() as conn:
            conn.execute("UPDATE records SET blob=? WHERE id=? AND user_id=? AND kind=?",
                         (seal_json(self._dek, obj, self._aad(kind)), rid, self.user_id, kind))

    def delete(self, kind, rid):
        with self._db() as conn:
            cur = conn.execute("DELETE FROM records WHERE id=? AND user_id=? AND kind=?", (rid, self.user_id, kind))
            return cur.rowcount > 0

    # ---- réglages (un seul enregistrement par utilisateur)
    def settings(self):
        rows = self.rows("settings")
        return rows[0][1] if rows else {}

    def set_setting(self, key, value):
        rows = self.rows("settings")
        if rows:
            data = rows[0][1]; data[key] = value
            self.update("settings", rows[0][0], data)
        else:
            self.add("settings", {key: value})

    # ---- accès pratiques
    def assets(self):
        return [dict(a, id=rid) for rid, a in self.rows("asset")]

    def find_asset(self, ticker):
        for rid, a in self.rows("asset"):
            if a["ticker"] == ticker:
                return rid, a
        return None, None
