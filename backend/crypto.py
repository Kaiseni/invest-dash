"""Primitives de chiffrement.

- scrypt dérive du mot de passe 64 octets : 32 pour vérifier le mot de passe (stockés), 32 = clé de chiffrement de clé (JAMAIS stockée).
- Chaque utilisateur possède une clé de données aléatoire (DEK, 256 bits). Elle n'est stockée que CHIFFRÉE :
  une fois par son mot de passe, une fois par sa clé de récupération.
- Les données sont chiffrées en AES-256-GCM avec la DEK (chiffrement authentifié : toute modification est détectée).
"""
import base64
import hashlib
import json
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_N, _R, _P = 2 ** 15, 8, 1  # ~32 Mo de mémoire par dérivation


def derive(secret: str, salt: bytes):
    out = hashlib.scrypt(secret.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, maxmem=128 * 1024 * 1024, dklen=64)
    return out[:32], out[32:]  # (preuve d'authentification, clé de chiffrement de clé)


def new_key() -> bytes:
    return os.urandom(32)


def new_salt() -> bytes:
    return os.urandom(16)


def seal(key: bytes, data: bytes, aad: bytes = b"") -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, data, aad)


def unseal(key: bytes, blob: bytes, aad: bytes = b"") -> bytes:
    return AESGCM(key).decrypt(blob[:12], blob[12:], aad)  # lève InvalidTag si clé fausse ou données modifiées


def seal_json(key: bytes, obj, aad: bytes = b"") -> bytes:
    return seal(key, json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), aad)


def unseal_json(key: bytes, blob: bytes, aad: bytes = b""):
    return json.loads(unseal(key, blob, aad).decode("utf-8"))


def new_recovery_key() -> str:
    """160 bits d'aléa, affichés en groupes de 4 caractères (à imprimer / mettre dans un gestionnaire de mots de passe)."""
    raw = base64.b32encode(secrets.token_bytes(20)).decode("ascii")
    return "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))


def normalize_recovery_key(value: str) -> str:
    return (value or "").upper().replace("-", "").replace(" ", "").strip()


def new_invite_code() -> str:
    raw = base64.b32encode(secrets.token_bytes(10)).decode("ascii")
    return "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))


def hash_code(code: str) -> str:
    return hashlib.sha256(normalize_recovery_key(code).encode("utf-8")).hexdigest()
