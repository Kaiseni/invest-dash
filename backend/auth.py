"""Comptes, sessions, protection des routes, droits RGPD (export, effacement)."""
import datetime
import hmac
import json
import os
import re
import secrets
import threading
import time
from functools import wraps

from cryptography.exceptions import InvalidTag
from flask import Blueprint, Response, g, jsonify, request

from . import legacy
from .crypto import (derive, hash_code, new_invite_code, new_key, new_recovery_key, new_salt,
                     normalize_recovery_key, seal, unseal)
from .db import get_db_connection
from .store import KINDS, Store

bp = Blueprint("auth", __name__)

COOKIE = "sid"
CSRF_VALUE = "invest-dash"
IDLE_SECONDS = int(os.environ.get("SESSION_IDLE_MIN", "60")) * 60
MAX_SECONDS = int(os.environ.get("SESSION_MAX_HOURS", "12")) * 3600
PUBLIC_PATHS = {"/api/auth/status", "/api/auth/login", "/api/auth/signup", "/api/auth/recover"}
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
DUMMY_SALT = b"\x00" * 16


def _common_code():
    """Code d'inscription COMMUN (variable d'environnement SIGNUP_CODE) : à donner aux personnes autorisées à créer un compte."""
    return os.environ.get("SIGNUP_CODE", "").strip()


def _common_code_ok(given):
    code = _common_code()
    return bool(code) and hmac.compare_digest(code.encode(), (given or "").strip().encode())


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ---------------------------------------------------------------------------- sessions (en mémoire uniquement)
# La clé de données de l'utilisateur n'existe en clair QUE ici, le temps de sa session. Redémarrage = déconnexion de tous.
_sessions = {}
_lock = threading.Lock()


def _create_session(user_id, username, is_admin, dek):
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _lock:
        _sessions[token] = {"user_id": user_id, "username": username, "is_admin": bool(is_admin),
                            "dek": dek, "created": now, "last": now}
    return token


def _session_from_request():
    token = request.cookies.get(COOKIE)
    if not token:
        return None, None
    now = time.time()
    with _lock:
        for t in [t for t, s in _sessions.items() if now - s["last"] > IDLE_SECONDS or now - s["created"] > MAX_SECONDS]:
            del _sessions[t]
        sess = _sessions.get(token)
        if sess:
            sess["last"] = now
    return token, sess


def _drop_user_sessions(user_id, keep=None):
    with _lock:
        for t in [t for t, s in _sessions.items() if s["user_id"] == user_id and t != keep]:
            del _sessions[t]


def _attach_cookie(resp, token):
    mode = os.environ.get("COOKIE_SECURE", "auto")
    secure = request.is_secure if mode == "auto" else mode == "1"
    resp.set_cookie(COOKIE, token, httponly=True, samesite="Strict", secure=secure, path="/")
    return resp


# ---------------------------------------------------------------------------- limitation des tentatives
_fails = {}
MAX_FAILS, WINDOW, LOCK = 5, 900, 900


def _locked_for(key):
    rec = _fails.get(key)
    return max(0, int(rec[2] - time.time())) if rec else 0


def _register_fail(key):
    now = time.time()
    count, start, _ = _fails.get(key, (0, now, 0))
    if now - start > WINDOW:
        count, start = 0, now
    count += 1
    _fails[key] = (count, start, now + LOCK if count >= MAX_FAILS else 0)


def _rate_keys(username):
    ip = request.remote_addr or "?"
    return (f"{ip}|{(username or '').lower()}", f"ip|{ip}")


def _check_rate(username):
    wait = max(_locked_for(k) for k in _rate_keys(username))
    if wait:
        return jsonify({"error": f"Trop de tentatives. Réessayez dans {wait // 60 + 1} min."}), 429
    return None


def _fail(username):
    keys = _rate_keys(username)
    _register_fail(keys[0])
    # limite globale par adresse un peu plus large (20 échecs) pour freiner l'énumération de comptes
    count = _fails.get(keys[1], (0, time.time(), 0))[0]
    if count + 1 >= 20:
        _fails[keys[1]] = (count + 1, time.time(), time.time() + LOCK)
    else:
        _register_fail(keys[1])


def _clear_fail(username):
    _fails.pop(_rate_keys(username)[0], None)


# ---------------------------------------------------------------------------- utilitaires
def _validate_new_credentials(username, password):
    if not USERNAME_RE.match(username or ""):
        return "Identifiant : 3 à 32 caractères (lettres, chiffres, . _ -)."
    if len(password or "") < 10:
        return "Mot de passe : 10 caractères minimum."
    if len(password) > 256:
        return "Mot de passe trop long."
    if password.lower() == username.lower():
        return "Le mot de passe ne doit pas être identique à l'identifiant."
    return None


def _user_row(conn, username):
    return conn.execute("SELECT id, username, is_admin, salt, auth_hash, wrapped_dek, rec_salt, wrapped_dek_rec "
                        "FROM users WHERE username=?", (username,)).fetchone()


def _check_password(row, password):
    """Retourne la clé de chiffrement de clé (KEK) si le mot de passe est bon, sinon None. Même durée si le compte n'existe pas."""
    auth, kek = derive(password or "", row[3] if row else DUMMY_SALT)
    if row and hmac.compare_digest(auth, row[4]):
        return kek
    return None


def _wrap_for_password(dek, password):
    salt = new_salt()
    auth, kek = derive(password, salt)
    return salt, auth, seal(kek, dek, b"dek")


def login_required_admin(fn):
    @wraps(fn)
    def inner(*a, **kw):
        if not g.user["is_admin"]:
            return jsonify({"error": "Réservé à l'administrateur."}), 403
        return fn(*a, **kw)
    return inner


# ---------------------------------------------------------------------------- routes publiques
@bp.route("/api/auth/status", methods=["GET"])
def status():
    with get_db_connection() as conn:
        n_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    _, sess = _session_from_request()
    return jsonify({"needs_setup": n_users == 0, "authenticated": bool(sess),
                    "signup_code_required": n_users > 0 or bool(_common_code()),
                    "common_code_active": bool(_common_code()),
                    "username": sess["username"] if sess else None,
                    "is_admin": bool(sess and sess["is_admin"]), "idle_minutes": IDLE_SECONDS // 60})


@bp.route("/api/auth/signup", methods=["POST"])
def signup():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    invite = data.get("invite") or ""
    err = _validate_new_credentials(username, password)
    if err:
        return jsonify({"error": err}), 400
    limited = _check_rate(username)
    if limited:
        return limited

    dek = new_key()
    salt, auth, wrapped = _wrap_for_password(dek, password)
    recovery = new_recovery_key()
    rec_salt = new_salt()
    wrapped_rec = seal(derive(normalize_recovery_key(recovery), rec_salt)[1], dek, b"dek")

    imported = False
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")  # un seul « premier compte » possible, même avec deux requêtes simultanées
        n_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        invite_used = False
        # Qui peut créer un compte ? Le code commun (SIGNUP_CODE) OU une invitation à usage unique ; sans code commun,
        # seul le tout premier compte (administrateur) est libre.
        if not _common_code_ok(invite) and (n_users > 0 or _common_code()):
            ok = n_users > 0 and conn.execute("SELECT 1 FROM invites WHERE code_hash=? AND used_by IS NULL AND expires_at > ?",
                                              (hash_code(invite), _now_iso())).fetchone()
            if not ok:
                _fail(username)
                return jsonify({"error": "Code d'inscription invalide ou expiré."}), 403
            invite_used = True
        if conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            return jsonify({"error": "Cet identifiant est déjà pris."}), 409
        cur = conn.execute("INSERT INTO users (username, is_admin, salt, auth_hash, wrapped_dek, rec_salt, wrapped_dek_rec, created_at, last_login) "
                           "VALUES (?,?,?,?,?,?,?,?,?)",
                           (username, 1 if n_users == 0 else 0, salt, auth, wrapped, rec_salt, wrapped_rec, _now_iso(), _now_iso()))
        uid = cur.lastrowid
        if invite_used:
            conn.execute("UPDATE invites SET used_by=? WHERE code_hash=?", (uid, hash_code(invite)))
        if n_users == 0:
            imported = legacy.import_into(conn, Store(uid, dek, conn))
    if imported:
        legacy.purge()  # efface les anciennes tables en clair

    token = _create_session(uid, username, n_users == 0, dek)
    resp = jsonify({"success": True, "recovery_key": recovery, "imported_legacy": imported, "is_admin": n_users == 0})
    return _attach_cookie(resp, token)


@bp.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    limited = _check_rate(username)
    if limited:
        return limited
    with get_db_connection() as conn:
        row = _user_row(conn, username)
        kek = _check_password(row, password)
        if not kek:
            _fail(username)
            return jsonify({"error": "Identifiant ou mot de passe incorrect."}), 401
        try:
            dek = unseal(kek, row[5], b"dek")
        except InvalidTag:
            return jsonify({"error": "Données du compte illisibles."}), 500
        conn.execute("UPDATE users SET last_login=? WHERE id=?", (_now_iso(), row[0]))
    _clear_fail(username)
    token = _create_session(row[0], row[1], row[2], dek)
    return _attach_cookie(jsonify({"success": True, "username": row[1], "is_admin": bool(row[2])}), token)


@bp.route("/api/auth/logout", methods=["POST"])
def logout():
    token, _ = _session_from_request()
    with _lock:
        _sessions.pop(token, None)
    resp = jsonify({"success": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


@bp.route("/api/auth/recover", methods=["POST"])
def recover():
    """Mot de passe oublié : la clé de récupération (donnée une seule fois à l'inscription) rouvre les données."""
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    new_password = data.get("new_password") or ""
    err = _validate_new_credentials(username, new_password)
    if err:
        return jsonify({"error": err}), 400
    limited = _check_rate(username)
    if limited:
        return limited
    with get_db_connection() as conn:
        row = _user_row(conn, username)
        dek = None
        if row:
            try:
                dek = unseal(derive(normalize_recovery_key(data.get("recovery_key")), row[6])[1], row[7], b"dek")
            except InvalidTag:
                dek = None
        else:
            derive("x", DUMMY_SALT)
        if not dek:
            _fail(username)
            return jsonify({"error": "Identifiant ou clé de récupération incorrect."}), 401
        salt, auth, wrapped = _wrap_for_password(dek, new_password)
        recovery = new_recovery_key()
        rec_salt = new_salt()
        wrapped_rec = seal(derive(normalize_recovery_key(recovery), rec_salt)[1], dek, b"dek")
        conn.execute("UPDATE users SET salt=?, auth_hash=?, wrapped_dek=?, rec_salt=?, wrapped_dek_rec=? WHERE id=?",
                     (salt, auth, wrapped, rec_salt, wrapped_rec, row[0]))
    _drop_user_sessions(row[0])
    _clear_fail(username)
    return jsonify({"success": True, "recovery_key": recovery})  # nouvelle clé : l'ancienne n'est plus valable


# ---------------------------------------------------------------------------- compte connecté
@bp.route("/api/auth/change-password", methods=["POST"])
def change_password():
    data = request.get_json(silent=True) or {}
    new_password = data.get("new_password") or ""
    err = _validate_new_credentials(g.user["username"], new_password)
    if err:
        return jsonify({"error": err}), 400
    limited = _check_rate(g.user["username"])
    if limited:
        return limited
    with get_db_connection() as conn:
        row = _user_row(conn, g.user["username"])
        if not _check_password(row, data.get("old_password") or ""):
            _fail(g.user["username"])
            return jsonify({"error": "Mot de passe actuel incorrect."}), 401
        salt, auth, wrapped = _wrap_for_password(g.dek, new_password)
        conn.execute("UPDATE users SET salt=?, auth_hash=?, wrapped_dek=? WHERE id=?", (salt, auth, wrapped, row[0]))
    _drop_user_sessions(g.user["id"], keep=g.token)
    return jsonify({"success": True})


@bp.route("/api/account/export", methods=["GET"])
def export_account():
    """RGPD art. 20 (portabilité) : toutes vos données, déchiffrées, dans un fichier JSON."""
    store = g.store
    content = {kind: [dict(obj, id=rid) for rid, obj in store.rows(kind)] for kind in KINDS if kind != "settings"}
    content["settings"] = store.settings()
    payload = {"exported_at": _now_iso(), "username": g.user["username"], "data": content}
    name = f"invest-dash-{g.user['username']}-{datetime.date.today().isoformat()}.json"
    return Response(json.dumps(payload, ensure_ascii=False, indent=2), mimetype="application/json",
                    headers={"Content-Disposition": f"attachment; filename={name}"})


@bp.route("/api/account", methods=["DELETE"])
def delete_account():
    """RGPD art. 17 (effacement) : supprime le compte et TOUTES ses données (après confirmation du mot de passe)."""
    data = request.get_json(silent=True) or {}
    with get_db_connection() as conn:
        row = _user_row(conn, g.user["username"])
        if not _check_password(row, data.get("password") or ""):
            return jsonify({"error": "Mot de passe incorrect."}), 401
        others = conn.execute("SELECT COUNT(*) FROM users WHERE id<>?", (row[0],)).fetchone()[0]
        if row[2] and others:
            return jsonify({"error": "Vous êtes l'administrateur : supprimez d'abord les autres comptes."}), 409
        conn.execute("DELETE FROM records WHERE user_id=?", (row[0],))
        conn.execute("DELETE FROM users WHERE id=?", (row[0],))
        conn.execute("UPDATE invites SET used_by=NULL WHERE used_by=?", (row[0],))
    _drop_user_sessions(row[0])
    resp = jsonify({"success": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


# ---------------------------------------------------------------------------- administration (aucun accès aux données des autres)
@bp.route("/api/admin/invite", methods=["POST"])
@login_required_admin
def create_invite():
    code = new_invite_code()
    expires = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7)).isoformat()
    with get_db_connection() as conn:
        conn.execute("INSERT INTO invites (code_hash, created_by, expires_at) VALUES (?,?,?)", (hash_code(code), g.user["id"], expires))
    return jsonify({"code": code, "expires_at": expires})  # affiché une seule fois : seul son empreinte est conservée


@bp.route("/api/admin/users", methods=["GET"])
@login_required_admin
def list_users():
    with get_db_connection() as conn:
        rows = conn.execute("SELECT id, username, is_admin, created_at, last_login FROM users ORDER BY id").fetchall()
    return jsonify([{"id": r[0], "username": r[1], "is_admin": bool(r[2]), "created_at": r[3], "last_login": r[4]} for r in rows])


@bp.route("/api/admin/users/<int:uid>", methods=["DELETE"])
@login_required_admin
def delete_user(uid):
    if uid == g.user["id"]:
        return jsonify({"error": "Utilisez « Supprimer mon compte » pour votre propre compte."}), 400
    with get_db_connection() as conn:
        conn.execute("DELETE FROM records WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM users WHERE id=?", (uid,))
        conn.execute("UPDATE invites SET used_by=NULL WHERE used_by=?", (uid,))
    _drop_user_sessions(uid)
    return jsonify({"success": True})


# ---------------------------------------------------------------------------- branchement sur l'application
def init_app(app):
    @app.before_request
    def _guard():
        path = request.path
        if not path.startswith("/api/"):
            return None
        # Anti-CSRF : en plus du cookie SameSite=Strict, toute requête qui modifie exige cet en-tête
        # (un site tiers ne peut pas l'ajouter sans autorisation du navigateur).
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("X-Requested-With") != CSRF_VALUE:
            return jsonify({"error": "Requête refusée."}), 403
        if path in PUBLIC_PATHS:
            return None
        token, sess = _session_from_request()
        if not sess:
            return jsonify({"error": "Authentification requise."}), 401
        g.token, g.dek = token, sess["dek"]
        g.user = {"id": sess["user_id"], "username": sess["username"], "is_admin": sess["is_admin"]}
        g.store = Store(sess["user_id"], sess["dek"])
        return None

    @app.after_request
    def _headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                                                   "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
                                                   "frame-ancestors 'none'")
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"  # aucune donnée personnelle dans un cache (navigateur, proxy)
        return resp
