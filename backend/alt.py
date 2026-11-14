"""Prix des cryptomonnaies et des matières premières (Yahoo Finance, repli CoinGecko pour les cryptos). Aucune clé d'API."""
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests
import yfinance as yf

from .prices import get_yf_session

# symbole -> (nom, identifiant CoinGecko)
CRYPTO_POPULAR = {
    "BTC": ("Bitcoin", "bitcoin"), "ETH": ("Ethereum", "ethereum"), "SOL": ("Solana", "solana"),
    "XRP": ("XRP", "ripple"), "BNB": ("BNB", "binancecoin"), "ADA": ("Cardano", "cardano"),
    "DOGE": ("Dogecoin", "dogecoin"), "LTC": ("Litecoin", "litecoin"), "DOT": ("Polkadot", "polkadot"),
    "LINK": ("Chainlink", "chainlink"), "AVAX": ("Avalanche", "avalanche-2"), "TRX": ("TRON", "tron"),
}

OZ_G = 31.1034768  # grammes dans une once troy
# code -> infos. Les prix Yahoo sont en USD : convertis en EUR avec EURUSD=X.
COMMODITIES = {
    "XAU": {"name": "Or", "yahoo": "GC=F", "unit": "once troy", "metal": True},
    "XAG": {"name": "Argent", "yahoo": "SI=F", "unit": "once troy", "metal": True},
    "XPT": {"name": "Platine", "yahoo": "PL=F", "unit": "once troy", "metal": True},
    "XPD": {"name": "Palladium", "yahoo": "PA=F", "unit": "once troy", "metal": True},
    "HG": {"name": "Cuivre", "yahoo": "HG=F", "unit": "livre (lb)", "metal": False},
    "BRENT": {"name": "Pétrole Brent", "yahoo": "BZ=F", "unit": "baril", "metal": False},
    "WTI": {"name": "Pétrole WTI", "yahoo": "CL=F", "unit": "baril", "metal": False},
    "NG": {"name": "Gaz naturel", "yahoo": "NG=F", "unit": "MMBtu", "metal": False},
}
DEFAULT_CRYPTO = ["BTC", "ETH", "SOL", "XRP", "BNB", "ADA", "DOGE", "LTC"]
CRYPTO_RE = re.compile(r"^[A-Z0-9]{2,10}$")

_CACHE = {}
_TTL = 30  # secondes : les cours sont rafraîchis au plus toutes les 30 s (partagé entre tous les utilisateurs)
_lock = threading.Lock()


def _yahoo_closes(symbol):
    hist = yf.Ticker(symbol, session=get_yf_session()).history(period="5d")
    if hist is None or hist.empty or "Close" not in hist.columns:
        return []
    return [float(x) for x in hist["Close"].dropna() if float(x) > 0]


def _yahoo_quote(symbol):
    """(dernier prix, clôture précédente) : cours quasi temps réel de Yahoo (fast_info), sinon dernières clôtures."""
    try:
        fi = yf.Ticker(symbol, session=get_yf_session()).fast_info
        last = float(fi["last_price"])
        prev = float(fi["previous_close"])
        if last > 0:
            return last, (prev if prev > 0 else None)
    except Exception:
        pass
    closes = _yahoo_closes(symbol)
    if closes:
        return closes[-1], (closes[-2] if len(closes) > 1 else None)
    return None

# ---------------------------------------------------------------- CoinGecko (secours, toute crypto)
_CG_IDS = {}        # symbole -> (id, nom) une fois résolu
_cg_backoff_until = 0.0


def _cg_get(path, params):
    """Appel CoinGecko avec pause automatique de 60 s si la limite de requêtes est atteinte (HTTP 429)."""
    global _cg_backoff_until
    if time.time() < _cg_backoff_until:
        return None
    r = requests.get("https://api.coingecko.com/api/v3" + path, params=params, timeout=8, headers={"Accept": "application/json"})
    if r.status_code == 429:
        _cg_backoff_until = time.time() + 60
        return None
    if r.status_code != 200:
        return None
    return r.json()


def _cg_resolve(symbol):
    """Retrouve l'identifiant CoinGecko d'un symbole (le mieux classé par capitalisation si plusieurs coins ont le même)."""
    if symbol in CRYPTO_POPULAR:
        return CRYPTO_POPULAR[symbol][1], CRYPTO_POPULAR[symbol][0]
    if symbol in _CG_IDS:
        return _CG_IDS[symbol]
    data = _cg_get("/search", {"query": symbol})
    candidates = [c for c in (data or {}).get("coins", []) if (c.get("symbol") or "").upper() == symbol]
    candidates.sort(key=lambda c: (c.get("market_cap_rank") is None, c.get("market_cap_rank") or 0))
    if not candidates:
        return None
    _CG_IDS[symbol] = (candidates[0]["id"], candidates[0].get("name") or symbol)
    return _CG_IDS[symbol]


def _coingecko(symbol):
    """(prix EUR, prix USD, variation 24 h en %, nom) ou None."""
    resolved = _cg_resolve(symbol)
    if not resolved:
        return None
    cid, name = resolved
    data = _cg_get("/simple/price", {"ids": cid, "vs_currencies": "usd,eur", "include_24hr_change": "true"})
    row = (data or {}).get(cid) or {}
    if not row.get("eur") or not row.get("usd"):
        return None
    change = row.get("usd_24h_change")
    return float(row["eur"]), float(row["usd"]), (round(change, 2) if change is not None else None), name


_CG_DAYS = {"1d": 1, "5d": 5, "1mo": 30, "1y": 365, "max": 365}  # la formule gratuite limite l'historique à 365 jours


def _cg_series(symbol, period):
    """Historique en EUR d'une crypto depuis CoinGecko (secours si Yahoo n'a pas la coin)."""
    resolved = _cg_resolve(symbol)
    if not resolved:
        return None
    data = _cg_get(f"/coins/{resolved[0]}/market_chart", {"vs_currency": "eur", "days": _CG_DAYS[period]})
    points = (data or {}).get("prices") or []
    if not points:
        return None
    idx = pd.to_datetime([p[0] for p in points], unit="ms", utc=True).tz_convert("Europe/Paris")
    s = pd.Series([float(p[1]) for p in points], index=idx)
    s = s[s > 0]
    if period not in ("1d", "5d"):
        s.index = s.index.tz_localize(None).normalize()
    return s[~s.index.duplicated(keep="last")]


# ---------------------------------------------------------------- cours instantanés
def _fetch(kind, symbol):
    if kind == "crypto":
        name = CRYPTO_POPULAR.get(symbol, (symbol, None))[0]
        out = {"kind": kind, "symbol": symbol, "name": name, "unit": "unité", "price": None, "price_usd": None,
               "price_per_g": None, "price_per_g_usd": None, "change_pct": None, "source": None}
        try:
            q = _yahoo_quote(f"{symbol}-USD")
            fx = _eurusd()
            if q and fx:
                out.update(price_usd=q[0], price=q[0] / fx, change_pct=_change(*q), source="Yahoo Finance (USD → EUR)")
                return out
        except Exception:
            pass
        try:
            res = _coingecko(symbol)
            if res:
                out.update(price=res[0], price_usd=res[1], change_pct=res[2], name=res[3], source="CoinGecko")
        except Exception:
            pass
        return out

    info = COMMODITIES[symbol]
    out = {"kind": kind, "symbol": symbol, "name": info["name"], "unit": info["unit"], "metal": info["metal"],
           "price": None, "price_usd": None, "price_per_g": None, "price_per_g_usd": None, "change_pct": None, "source": None}
    try:
        q = _yahoo_quote(info["yahoo"])
        fx = _eurusd()
        if q and fx:
            out.update(price_usd=q[0], price=q[0] / fx, change_pct=_change(*q), source="Yahoo Finance (contrat à terme, USD → EUR)")
            if info["metal"]:
                out["price_per_g_usd"] = q[0] / OZ_G
                out["price_per_g"] = q[0] / fx / OZ_G
    except Exception:
        pass
    return out

def _eurusd():
    hit = _CACHE.get(("fx", "EURUSD"))
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    rate = None
    try:
        q = _yahoo_quote("EURUSD=X")
        rate = q[0] if q else None
    except Exception:
        pass
    if rate:
        _CACHE[("fx", "EURUSD")] = (time.time(), rate)
    return rate


def _change(last, prev):
    return round((last / prev - 1) * 100, 2) if last and prev else None


def get_quote(kind, symbol):
    key = (kind, symbol)
    with _lock:
        hit = _CACHE.get(key)
        if hit and time.time() - hit[0] < _TTL:
            return hit[1]
    data = _fetch(kind, symbol)
    if data["price"]:  # on ne garde pas un échec en cache
        with _lock:
            _CACHE[key] = (time.time(), data)
    return data


def valid_symbol(kind, symbol):
    if kind == "crypto":
        return bool(CRYPTO_RE.match(symbol))
    return kind == "commodity" and symbol in COMMODITIES


# ---------------------------------------------------------------- historique du portefeuille
def _yahoo_series(symbol, period, interval):
    """Série des cours de clôture (index homogène : heure de Paris en intraday, jour en quotidien) ou None."""
    hist = yf.Ticker(symbol, session=get_yf_session()).history(period=period, interval=interval)
    if hist is None or hist.empty or "Close" not in hist.columns:
        return None
    close = hist["Close"].dropna()
    close = close[close > 0]
    if close.empty:
        return None
    idx = close.index
    if idx.tz is not None:
        idx = idx.tz_convert("Europe/Paris")
    if interval == "1d":
        idx = idx.tz_localize(None).normalize() if idx.tz is not None else idx.normalize()
    close.index = idx
    return close[~close.index.duplicated(keep="last")]

def history_totals(holdings, period):
    """Valeur passée du portefeuille = quantités ACTUELLES x cours historiques (même principe que la Synthèse)."""
    interval = "5m" if period == "1d" else "15m" if period == "5d" else "1d"
    keys = list(dict.fromkeys((h["kind"], h["symbol"]) for h in holdings))

    def yahoo_symbol(kind, symbol):
        return f"{symbol}-USD" if kind == "crypto" else COMMODITIES[symbol]["yahoo"]

    wanted = {yahoo_symbol(k, s) for k, s in keys} | {"EURUSD=X"}
    with ThreadPoolExecutor(max_workers=6) as pool:
        fetched = dict(zip(wanted, pool.map(lambda sym: _safe_series(sym, period, interval), wanted)))

    fx = fetched.get("EURUSD=X")
    eur_series, missing = {}, []
    for kind, symbol in keys:
        s = fetched.get(yahoo_symbol(kind, symbol))
        if s is not None and fx is not None:  # USD -> EUR avec le taux du même moment
            fx_aligned = fx.reindex(s.index.union(fx.index)).ffill().bfill().reindex(s.index)
            eur_series[(kind, symbol)] = s / fx_aligned
            continue
        if kind == "crypto":  # secours : historique CoinGecko (déjà en EUR)
            try:
                cg = _cg_series(symbol, period)
            except Exception:
                cg = None
            if cg is not None:
                eur_series[(kind, symbol)] = cg
                continue
        missing.append(symbol)

    parts = []
    for h in holdings:
        s = eur_series.get((h["kind"], h["symbol"]))
        if s is None:
            continue
        per_unit = 1 / OZ_G if h.get("unit") == "g" else 1.0
        parts.append((s * per_unit * h["qty"]).rename(f"{h['kind']}:{h['symbol']}:{h.get('unit', 'base')}"))
    if not parts:
        return None
    frame = pd.concat(parts, axis=1).sort_index().ffill().bfill()
    total = frame.sum(axis=1)
    fmt = "%d %b %H:%M" if interval in ("5m", "15m") else "%Y-%m-%d"
    return {"dates": total.index.strftime(fmt).tolist(), "totals": [round(float(v), 2) for v in total],
            "missing": sorted(set(missing))}

def _safe_series(symbol, period, interval):
    try:
        return _yahoo_series(symbol, period, interval)
    except Exception:
        return None

def empty_history(period):
    """Série à zéro (dates de marché) : sert quand il n'y a que des liquidités, pour tracer la courbe."""
    interval = "5m" if period == "1d" else "15m" if period == "5d" else "1d"
    s = _safe_series("EURUSD=X", period, interval)
    if s is None:
        return None
    fmt = "%d %b %H:%M" if interval in ("5m", "15m") else "%Y-%m-%d"
    return {"dates": s.index.strftime(fmt).tolist(), "totals": [0.0] * len(s), "missing": []}