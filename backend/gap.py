"""Écart estimé à l'ouverture (sous-jacents US/Europe/Asie en EUR) + suivi automatique estimation vs ouverture réelle."""
import datetime
import json
import os
import threading
import time
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

try:
    import fcntl  # Linux : verrou pour ne lancer la boucle de suivi qu'une fois (gunicorn multi-workers)
except ImportError:
    fcntl = None

from .config import ROOT_DIR
from .db import get_db_connection
from .prices import fetch_price_boursorama, get_yf_session

# ==========================================================
# RÉGLAGES (à ajuster)
# ==========================================================
PARIS = ZoneInfo("Europe/Paris")
# Modèles dynamiques par indice : (Mots-clés, Libellé affiché, [(symbole Yahoo, poids, devise locale PAR EUR ou None)], levier par défaut)
GAP_MODELS = {
    "WORLD": (
        ["WORLD", "MONDE", "GLOBE", "CW8", "WPEA", "DCAM"],
        "MSCI World (US+Europe+Asie)",
        [("ES=F", 0.75, "EURUSD=X"), ("^STOXX50E", 0.17, None), ("^N225", 0.08, "EURJPY=X")],
        1
    ),
    "NASDAQ": (
        ["NASDAQ", "NDX", "LQQ", "PNAS"],
        "Nasdaq-100 (US)",
        [("NQ=F", 1.0, "EURUSD=X")],
        1
    ),
    "SP500": (
        ["S&P", "SP500", "500", "S&P500", "S AND P", "PSP5", "CSPX", "VUSA"],
        "S&P 500 (US)",
        [("ES=F", 1.0, "EURUSD=X")],
        1
    ),
    "EMERGING": (
        ["EMERG", "ASIE EMERGENTE", "EMERGING", "PAASI", "PAEEM"],
        "Marchés Émergents",
        [("^HSI", 0.33, "EURHKD=X"), ("^TWII", 0.27, "EURTWD=X"), ("^BSESN", 0.23, "EURINR=X"), ("^KS11", 0.17, "EURKRW=X")],
        1
    )
}

# Corrections (k = amplitude, b = décalage en points de %). À remplir avec /api/gap/tuning quand il dit APPLIQUER.
GAP_CALIB = {}
# Tickers suivis par le scheduler (aucune donnée utilisateur). Surchargeable : GAP_TICKERS="WPEA.PA,PNAS.PA,..."
GAP_TICKERS = [t.strip().upper() for t in os.environ.get("GAP_TICKERS", "WPEA.PA,DCAM.PA,PNAS.PA,PAASI.PA").split(",") if t.strip()]
SNAPSHOT_EVENING = (22, 5)   # 22h05 Paris, dimanche à jeudi
SNAPSHOT_MORNING = (8, 50)   # 8h50 Paris, lundi à vendredi

# INTERNE
_GAP_LOCK = {}
_GAP_CACHE = {}
_LAST_GAP_PARTS = {}
_GAP_LAST_TRY = {}


def _now():
    return datetime.datetime.now(PARIS)


_GAP_FETCH_LOCK = threading.Lock()


def _gap_series(symbol):
    """Prix 'Close' à la minute sur 5 jours (UTC), en cache 60 s (verrou : pas de doublons entre threads)."""
    hit = _GAP_CACHE.get(symbol)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    with _GAP_FETCH_LOCK:
        hit = _GAP_CACHE.get(symbol)
        if hit and time.time() - hit[0] < 60:
            return hit[1]
        h = yf.Ticker(symbol, session=get_yf_session()).history(period="5d", interval="1m", prepost=True)
        s = h["Close"].dropna()
        s.index = s.index.tz_convert("UTC")
        s = s.sort_index()
        _GAP_CACHE[symbol] = (time.time(), s)
        return s

_NAME_CACHE = {}

def _etf_full_name(ticker):
    key = ticker.upper()
    if key in _NAME_CACHE:
        return _NAME_CACHE[key]
    try:
        info = yf.Ticker(ticker, session=get_yf_session()).info or {}
        full = f"{info.get('shortName', '')} {info.get('longName', '')} {info.get('longBusinessSummary', '')} {key}".upper()
    except Exception:
        return key  # on ne met pas l'échec en cache
    _NAME_CACHE[key] = full
    return full

def estimate_gap(ticker, etf_price, calibrate=True):
    """Retourne (libellé, écart_%, écart_€, prix_estimé).
    Écart = variation (en EUR) des sous-jacents US/Europe/Asie depuis la clôture de Paris."""
    
    etf_name_full = _etf_full_name(ticker)

    matched_model_key = None
    for key, (keywords, label, comps, lev) in GAP_MODELS.items():
        if any(keyword in etf_name_full for keyword in keywords):
            matched_model_key = key
            if any(lev_word in etf_name_full for lev_word in ["X2", "2X", "LEVERAGE", "DAILY 2X"]):
                lev = 2 
            break

    if not matched_model_key:
        return "", 0.0, 0.0, etf_price

    keywords, label, comps, final_lev = GAP_MODELS[matched_model_key]

    try:
        last = _gap_series(ticker).index[-1].tz_convert(PARIS)
        close = last.replace(hour=17, minute=35, second=0, microsecond=0).tz_convert("UTC")
        ref = min(close, pd.Timestamp.now(tz="UTC"))     # clôture de Paris, ou maintenant si la séance est en cours
    except Exception as e:
        print(f"[gap] historique {ticker} indisponible : {e}")
        return label, 0.0, 0.0, etf_price

    gap = used = 0.0
    parts = {}
    for sym, w, fx in comps:
        try:
            s = _gap_series(sym)
            p_ref = s.asof(ref)
            if pd.isna(p_ref):
                raise ValueError("pas de prix à l'heure de référence")
            r = s.iloc[-1] / p_ref
            if fx:                                       # conversion en EUR
                f = _gap_series(fx)
                r *= f.asof(ref) / f.iloc[-1]
            gap += w * (r - 1)
            used += w
            parts[sym] = round(float((r - 1) * 100), 4)
        except Exception as e:
            print(f"[gap] {sym} ignoré : {e}")
    _LAST_GAP_PARTS[ticker.upper()] = parts
    if used == 0:
        return label, 0.0, 0.0, etf_price

    gap = float(gap / used * final_lev)
    if calibrate:
        k, b = GAP_CALIB.get(matched_model_key, (1.0, 0.0))
        gap = gap * k + b / 100
    return label, round(gap * 100, 4), round(etf_price * gap, 4), round(etf_price * (1 + gap), 4)


def log_gap_snapshot(slot):
    """Enregistre l'estimation BRUTE du moment pour la prochaine ouverture ('soir' ou 'pre')."""
    now = _now()
    d = now.date() if now.hour < 9 else now.date() + datetime.timedelta(days=1)
    while d.weekday() >= 5:                              # saute le week-end
        d += datetime.timedelta(days=1)
    with get_db_connection() as conn:
        tickers = GAP_TICKERS
        for tk in tickers:
            if conn.execute("SELECT 1 FROM gap_log WHERE trade_date=? AND ticker=? AND slot=?",
                            (d.isoformat(), tk, slot)).fetchone():
                continue                                 # déjà enregistré
            try:
                ref = fetch_price_boursorama(tk) or float(_gap_series(tk).iloc[-1])
                label, pct, eur, est = estimate_gap(tk, ref, calibrate=False)
                if not label:
                    continue                             # ETF sans modèle
                conn.execute("INSERT OR IGNORE INTO gap_log "
                             "(trade_date, ticker, slot, snap_ts, ref_price, est_gap_pct, est_price, parts) "
                             "VALUES (?,?,?,?,?,?,?,?)",
                             (d.isoformat(), tk, slot, now.isoformat(), ref, pct, est,
                              json.dumps(_LAST_GAP_PARTS.get(tk.upper(), {}))))
            except Exception as e:
                print(f"[gap] snapshot {tk} : {e}")


def log_open_prices():
    """Relève le vrai prix d'ouverture (1re cotation >= 9h00) pour les lignes encore vides."""
    now = _now()
    today = now.date().isoformat()
    with get_db_connection() as conn:
        todo = {}
        for d, tk in conn.execute("SELECT DISTINCT trade_date, ticker FROM gap_log WHERE open_price IS NULL").fetchall():
            if d < today or (d == today and now.time() >= datetime.time(9, 6)):
                todo.setdefault(tk, []).append(d)
        for tk, dates in todo.items():
            if time.time() - _GAP_LAST_TRY.get(tk, 0) < 600:     # pas plus d'un essai / 10 min
                continue
            _GAP_LAST_TRY[tk] = time.time()
            try:
                h = yf.Ticker(tk, session=get_yf_session()).history(period="7d", interval="1m")
                h.index = h.index.tz_convert(PARIS)
            except Exception as e:
                print(f"[gap] ouverture {tk} : {e}")
                continue
            for d in dates:
                day = h[h.index.date == datetime.date.fromisoformat(d)]
                day = day[day.index.time >= datetime.time(9, 0)]
                if day.empty:
                    continue
                upto = day[day.index.time <= datetime.time(9, 5)]
                p0905 = float(upto["Close"].iloc[-1]) if not upto.empty else None
                conn.execute("UPDATE gap_log SET open_price=?, open_ts=?, p0905=? WHERE trade_date=? AND ticker=?",
                             (float(day["Open"].iloc[0]), day.index[0].isoformat(), p0905, d, tk))


def _gap_scheduler():
    """Boucle de fond : snapshot soir/matin, puis relevé des ouvertures."""
    while True:
        try:
            now = _now()
            m, wd = now.hour * 60 + now.minute, now.weekday()
            e0 = SNAPSHOT_EVENING[0] * 60 + SNAPSHOT_EVENING[1]
            m0 = SNAPSHOT_MORNING[0] * 60 + SNAPSHOT_MORNING[1]
            if wd in (6, 0, 1, 2, 3) and e0 <= m < e0 + 55:
                log_gap_snapshot("soir")
            if wd < 5 and m0 <= m < 9 * 60:
                log_gap_snapshot("pre")
            log_open_prices()
        except Exception as e:
            print(f"[gap] scheduler : {e}")
        time.sleep(60)


def _start_scheduler():
    """Lance la boucle une seule fois, même avec plusieurs workers gunicorn (verrou fichier)."""
    if fcntl:
        try:
            fh = open(os.path.join(ROOT_DIR, "data", ".gap_scheduler.lock"), "w")
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _GAP_LOCK["fh"] = fh
        except OSError:
            return False
    threading.Thread(target=_gap_scheduler, daemon=True, name="gap-scheduler").start()
    return True