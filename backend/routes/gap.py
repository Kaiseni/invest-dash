import os
from functools import wraps

import numpy as np
from flask import Blueprint, jsonify, request

from ..db import get_db_connection
from ..gap import GAP_MODELS

bp = Blueprint("gap", __name__)


def _guard(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        token = os.environ.get("GAP_TOKEN")
        if token and request.args.get("token") != token:
            return jsonify({"error": "accès refusé"}), 403
        return fn(*a, **kw)
    return wrapper


@bp.route('/api/gap/rows', methods=['GET'])
@_guard
def gap_rows():
    with get_db_connection() as conn:
        rows = conn.execute("SELECT trade_date, ticker, slot, ref_price, est_gap_pct, est_price, open_price, p0905 "
                            "FROM gap_log ORDER BY trade_date DESC, ticker, slot LIMIT 40").fetchall()
    cols = ["date", "ticker", "creneau", "prix_ref", "ecart_estime_pct", "prix_estime", "prix_ouverture", "prix_0905"]
    return jsonify([dict(zip(cols, r)) for r in rows])


@bp.route('/api/gap/report', methods=['GET'])
@_guard
def gap_report():
    """Erreur de l'estimation brute vs erreur si on n'estimait rien (écart = 0)."""
    with get_db_connection() as conn:
        rows = conn.execute("SELECT ticker, slot, ref_price, est_gap_pct, open_price FROM gap_log "
                            "WHERE open_price IS NOT NULL AND ref_price > 0").fetchall()
    acc = {}
    for tk, slot, ref, est, op in rows:
        actual = (op / ref - 1) * 100
        acc.setdefault(f"{tk}|{slot}", []).append((est - actual, actual))
    out = {}
    for k, v in acc.items():
        e, a = np.array([x[0] for x in v]), np.array([x[1] for x in v])
        out[k] = {"n": len(e),
                  "biais_pct": round(float(e.mean()), 3),
                  "mae_pct": round(float(np.abs(e).mean()), 3),
                  "rmse_pct": round(float(np.sqrt((e ** 2).mean())), 3),
                  "mae_sans_estimation_pct": round(float(np.abs(a).mean()), 3),
                  "part_dans_0.2pct": round(float((np.abs(e) <= 0.2).mean() * 100))}
    return jsonify(out)


def _fit_calib(e, a):
    """k (amplitude) et b (décalage, points de %) tels que réel ≈ k·estimation + b, avec garde-fous."""
    n = len(e)
    if n < 5 or float((e ** 2).sum()) == 0:
        return 1.0, 0.0
    k = float((e * a).sum() / (e ** 2).sum())
    se_k = float(np.sqrt(((a - k * e) ** 2).sum() / max(n - 1, 1) / (e ** 2).sum()))
    if abs(k - 1) < 2 * se_k:
        k = 1.0
    k = float(np.clip(k, 0.3, 1.5))
    res = a - k * e
    b = float(res.mean())
    if abs(b) < 2 * float(res.std(ddof=1)) / np.sqrt(n):
        b = 0.0
    return round(k, 2), round(b, 2)


def _loo_mae(e, a):
    """Erreur moyenne d'un calibrage testé hors échantillon (un jour laissé de côté à chaque fois)."""
    errs = []
    for i in range(len(e)):
        m = np.arange(len(e)) != i
        k, b = _fit_calib(e[m], a[m])
        errs.append(abs(a[i] - (k * e[i] + b)))
    return float(np.mean(errs))


@bp.route('/api/gap/tuning', methods=['GET'])
@_guard
def gap_tuning():
    """Dit quoi mettre dans GAP_CALIB (créneau 8h50, estimations brutes)."""
    with get_db_connection() as conn:
        rows = conn.execute("SELECT trade_date, ticker, ref_price, est_gap_pct, open_price, p0905 FROM gap_log "
                            "WHERE slot='pre' AND open_price IS NOT NULL AND ref_price > 0 ORDER BY trade_date").fetchall()
    by_tk = {}
    for d, tk, ref, est, op, p5 in rows:
        by_tk.setdefault(tk, []).append((d, est, (op / ref - 1) * 100, (p5 / ref - 1) * 100 if p5 else None))
    out = {}
    for tk, v in by_tk.items():
        key = next((k for k, (kws, *_) in GAP_MODELS.items() if any(w in tk.upper() for w in kws)), None)
        e = np.array([x[1] for x in v])
        a = np.array([x[2] for x in v])
        n = len(v)
        mae_raw, mae_zero = float(np.abs(a - e).mean()), float(np.abs(a).mean())
        k, b = _fit_calib(e, a)
        info = {"jours_mesures": n, "erreur_brute_pct": round(mae_raw, 3),
                "erreur_sans_estimation_pct": round(mae_zero, 3)}
        if n < 15:
            info["decision"] = f"Pas assez de données ({n}/15 jours) : ne changez rien."
        elif mae_raw >= mae_zero:
            info["decision"] = "Le modèle ne fait pas mieux que 'rien estimer' : revoyez poids/symboles avant de calibrer."
        elif (k, b) == (1.0, 0.0):
            info["decision"] = "Aucune correction nécessaire : l'estimation est sans biais net."
        else:
            loo = _loo_mae(e, a)
            info["erreur_apres_calibrage_pct"] = round(loo, 3)
            if loo < 0.9 * mae_raw:
                info["decision"] = "APPLIQUER"
                info["modifier"] = f'GAP_CALIB["{key}"] = ({k}, {b})   # (amplitude k, décalage b en points de %)'
            else:
                info["decision"] = "Calibrage trop peu utile (<10 % de gain hors échantillon) : ne changez rien."
        p = [x for x in v if x[3] is not None]
        if len(p) >= 10:
            mo = float(np.mean([abs(x[2] - x[1]) for x in p]))
            m5 = float(np.mean([abs(x[3] - x[1]) for x in p]))
            info["prix_le_mieux_estime"] = "ouverture (9h00)" if mo <= m5 else "prix de 9h05"
        info["pires_jours"] = [{"date": x[0], "erreur_pct": round(x[1] - x[2], 2)}
                               for x in sorted(v, key=lambda x: -abs(x[1] - x[2]))[:3]]
        out[tk] = info
    return jsonify(out)
