import csv
from concurrent.futures import ThreadPoolExecutor
from io import StringIO

import datetime
import re

from flask import Blueprint, Response, g, jsonify, request

from ..config import SELL_COMMISSION_RATE
from ..prices import get_live_price
from ..services import cash_state, fetch_ticker_data
from ..utils import clean_float, to_int
from ..lots import get_lots, next_id, rebuild, shrink
bp = Blueprint("portfolio", __name__)


def _norm_ticker(value):
    """Ticker TAPÉ par l'utilisateur (création d'une ligne ou d'un ordre).
    - symbole complet déjà saisi (SAP.DE, ASML.AS, BTC-USD, ^FCHI…) : on ne touche à rien ;
    - « AAPL. » (point final) : action sans suffixe, par exemple cotée aux États-Unis -> AAPL ;
    - sinon (WPEA, TTE, DCAM…) : on ajoute .PA, comme avant."""
    ticker = (value or "").strip().upper()
    if ticker.endswith("."):
        return ticker[:-1]
    if ticker and not re.search(r"[.\-=^]", ticker):
        ticker += ".PA"
    return ticker


def _clean_ticker(value):
    """Ticker DÉJÀ ENREGISTRÉ (suppression, vente) : tel quel, sans jamais ajouter de suffixe."""
    return (value or "").strip().upper()

@bp.route('/api/export', methods=['GET'])
def export_csv():
    """Exporte les positions actuelles et l'historique des ventes en CSV."""
    store = g.store
    assets = [(a["ticker"], a["buy_price"], a["qty"]) for _, a in store.rows("asset")]
    sales = [(s.get("sold_date"), s["ticker"], s["qty"], s["buy_price"], s["sell_price"], s["realized_gl"]) for _, s in store.rows("sold")]

    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['--- POSITIONS ACTUELLES ---'])
    cw.writerow(['Ticker', 'Prix Achat', 'Quantite'])
    cw.writerows(assets)
    cw.writerow([])
    cw.writerow(['--- HISTORIQUE DES VENTES ---'])
    cw.writerow(['Date', 'Ticker', 'Quantite', 'Prix Achat', 'Prix Vente', 'Plus-Value Realisee'])
    cw.writerows(sales)
    return Response(si.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=portfolio_export.csv"})


@bp.route('/api/portfolio', methods=['GET'])
def get_portfolio():
    store = g.store
    asset_rows = store.rows("asset")
    rows = [(a["ticker"], a["buy_price"], a["qty"]) for _, a in asset_rows]
    lots_by_ticker = {a["ticker"]: get_lots(a) for _, a in asset_rows}
    cash = cash_state(store)
    pending_rows = [(rid, p["ticker"], p["qty"], p["limit_price"]) for rid, p in store.rows("pending")]

    # Récupération des cours en parallèle (avant : un ticker après l'autre, plusieurs secondes cumulées)
    def _load(row):
        ticker, buy_price, qty = row
        try:
            return fetch_ticker_data(ticker, buy_price, qty)
        except Exception as e:
            print(f"Erreur avec {ticker}: {e}")
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = [r for r in pool.map(_load, rows) if r]
        for r in results:
            r["lots"] = lots_by_ticker.get(r["ticker"], [])

    total_current_value = sum(r["total_value"] for r in results)

    pending_orders_list = []
    for pid, t, q, p in pending_rows:
        pending_orders_list.append({"id": pid, "ticker": t, "qty": q, "limit_price": p, "locked_cash": round(q * p, 4)})

    available_cash = round(cash["available"], 4)
    locked_cash = cash["locked"]
    current_total_wealth = total_current_value + available_cash + locked_cash

    # Base de calcul de la performance = ce que vous avez réellement viré sur le PEA.
    effective_invested = cash["deposited"]
    gain_loss_amount = current_total_wealth - effective_invested
    gain_loss_pct = (gain_loss_amount / effective_invested * 100) if effective_invested > 0 else 0.0

    summary = {
        "total_invested": round(effective_invested, 4),
        "manual_invested": 0.0,
        "pru_invested_sum": round(cash["pru_sum"], 4),
        "total_assets_value": round(total_current_value, 4),
        "total_wealth": round(current_total_wealth, 4),
        "available_cash": available_cash,
        "cash_inconsistent": cash["available_raw"] < 0,  # True si total viré < achats + ordres : vérifier les saisies
        "locked_cash": locked_cash,
        "total_deposited": cash["deposited"],
        "other_fees": cash["other_fees"],
        "gain_loss_amount": round(gain_loss_amount, 4),
        "gain_loss_pct": round(gain_loss_pct, 4),
        "total_realized_gl": round(cash["realized"], 4),
        "pending_orders": pending_orders_list
    }
    return jsonify({"assets": results, "summary": summary})


def _setting_route(setting_key, json_key):
    if request.method == 'POST':
        val = clean_float((request.get_json(silent=True) or {}).get(json_key, 0.0), 2)
        g.store.set_setting(setting_key, val)
        return jsonify({"success": True})
    return jsonify({json_key: g.store.settings().get(setting_key, 0.0)})


@bp.route('/api/budget', methods=['GET', 'POST'])
def route_budget():
    return _setting_route('monthly_budget', 'budget')


@bp.route('/api/deposited', methods=['GET', 'POST'])
def route_deposited():
    return _setting_route('total_deposited', 'deposited')


@bp.route('/api/fees', methods=['GET', 'POST'])
def route_fees():
    return _setting_route('other_fees', 'fees')


# ---------------------------------------------------------------- répartition cible (choisie par l'utilisateur)
_TICKER_RE = re.compile(r"^[A-Z0-9.\-^=]{1,15}$")


def _validate_targets(raw):
    if not isinstance(raw, list) or not (1 <= len(raw) <= 12):
        return None, "Entre 1 et 12 lignes de répartition."
    clean, total = [], 0.0
    for item in raw:
        label = str((item or {}).get("label") or "").strip()[:30]
        tickers = [_norm_ticker(t) for t in ((item or {}).get("tickers") or []) if str(t).strip()]
        buy = _norm_ticker((item or {}).get("buy") or (tickers[0] if tickers else ""))
        try:
            pct = round(float((item or {}).get("pct")), 2)
        except (TypeError, ValueError):
            return None, "Pourcentage invalide."
        if not label or not tickers or any(not _TICKER_RE.match(t) for t in tickers):
            return None, "Chaque ligne a besoin d'un nom et d'au moins un ticker valide."
        if buy not in tickers:
            tickers.append(buy)
        if not (0 < pct <= 100):
            return None, "Chaque pourcentage doit être entre 0 et 100."
        total += pct
        clean.append({"label": label, "tickers": tickers, "buy": buy, "pct": pct})
    if abs(total - 100.0) > 0.01:
        return None, f"Le total doit faire 100 % (actuellement {total:g} %)."
    return clean, None


@bp.route('/api/targets', methods=['GET', 'POST'])
def route_targets():
    if request.method == 'POST':
        clean, err = _validate_targets((request.get_json(silent=True) or {}).get("targets"))
        if err:
            return jsonify({"error": err}), 400
        g.store.set_setting("targets", clean)
        return jsonify({"success": True, "targets": clean})
    return jsonify({"targets": g.store.settings().get("targets", [])})


@bp.route('/api/quote', methods=['GET'])
def route_quote():
    """Prix courant d'un ticker (pour planifier l'achat d'un ETF que l'on ne détient pas encore)."""
    ticker = _norm_ticker(request.args.get("ticker"))
    if not _TICKER_RE.match(ticker):
        return jsonify({"error": "Ticker invalide"}), 400
    price = get_live_price(ticker)
    return jsonify({"ticker": ticker, "price": price or None})


# ---------------------------------------------------------------- ordres en attente
@bp.route('/api/pending', methods=['POST'])
def add_pending():
    data = request.get_json(silent=True) or {}
    ticker = _norm_ticker(data.get('ticker'))
    qty = clean_float(data.get('qty', 0), 4)
    price = clean_float(data.get('limit_price', 0), 4)
    if not ticker or qty <= 0 or price <= 0:
        return jsonify({"error": "Données invalides"}), 400
    g.store.add("pending", {"ticker": ticker, "qty": qty, "limit_price": price})
    return jsonify({"success": True})


@bp.route('/api/pending/delete', methods=['POST'])
def delete_pending():
    rid = to_int((request.get_json(silent=True) or {}).get('id'))
    if rid is not None:
        g.store.delete("pending", rid)
    return jsonify({"success": True})

# ---------------------------------------------------------------- positions
@bp.route('/api/add', methods=['POST'])
def add_asset():
    import yfinance as yf
    from ..prices import get_yf_session
    
    data = request.get_json(silent=True) or {}
    ticker = _norm_ticker(data.get('ticker'))
    raw_buy_price = clean_float(data.get('buy_price', 0), 4)
    qty = clean_float(data.get('qty', 1), 4)
    fees = clean_float(data.get('fees', 0), 2)  # frais de courtage de l'ordre (facultatif)

    if not ticker:
        return jsonify({"error": "Ticker requis"}), 400
    if qty <= 0 or raw_buy_price <= 0:
        return jsonify({"error": "Quantité et prix d'achat doivent être supérieurs à 0"}), 400
    if fees < 0:
        return jsonify({"error": "Les frais ne peuvent pas être négatifs"}), 400

    # DÉTECTION DE DEVISE ET CONVERSION
    final_buy_price_eur = raw_buy_price
    currency = "EUR"
    try:
        info = yf.Ticker(ticker, session=get_yf_session()).info
        asset_currency = info.get('currency', 'EUR').upper()
        
        if asset_currency != "EUR":
            currency = asset_currency
            fx_ticker = f"{asset_currency}EUR=X"
            fx_info = yf.Ticker(fx_ticker, session=get_yf_session()).history(period="1d")
            
            if not fx_info.empty:
                exchange_rate = float(fx_info['Close'].iloc[-1])
                final_buy_price_eur = round(raw_buy_price * exchange_rate, 4)
    except Exception as e:
        print(f"[Erreur Devise] Impossible de vérifier la devise pour {ticker} : {e}")
        final_buy_price_eur = raw_buy_price

    # Calcul du PRU final en euros
        # Chaque achat devient une entrée (lot) ; la quantité et le PRU de la ligne sont recalculés
    lot_price = final_buy_price_eur + fees / qty
    new_lot = {"date": datetime.date.today().isoformat(), "qty": qty, "price": round(lot_price, 4),
               "raw_price": final_buy_price_eur, "fees": fees, "cash_paid": 0.0}
    rid, existing = g.store.find_asset(ticker)
    if existing:
        lots = get_lots(existing)
        new_lot["id"] = next_id(lots)
        g.store.update("asset", rid, rebuild(existing, lots + [new_lot], 4, 4))
    else:
        new_lot["id"] = 1
        g.store.add("asset", rebuild({"ticker": ticker}, [new_lot], 4, 4))
        
    msg = f"Actif ajouté avec succès."
    if currency != "EUR":
        msg = f"Actif ajouté. Prix converti : {raw_buy_price} {currency} ➔ {final_buy_price_eur} €"
        
    return jsonify({"success": True, "message": msg})


@bp.route('/api/delete', methods=['POST'])
def delete_asset():
    ticker = _clean_ticker((request.get_json(silent=True) or {}).get('ticker'))
    if not ticker:
        return jsonify({"error": "Ticker requis"}), 400
    rid, _ = g.store.find_asset(ticker)
    if rid:
        g.store.delete("asset", rid)
    return jsonify({"success": True})


@bp.route('/api/sell', methods=['POST'])
def sell_asset():
    """Vente partielle ou totale. Commission automatique (0,50 % du brut) : elle réduit le net reçu ET la plus-value réalisée."""
    data = request.get_json(silent=True) or {}
    ticker = _clean_ticker(data.get('ticker'))
    sell_qty = clean_float(data.get('qty', 0), 4)
    sell_price = clean_float(data.get('sell_price', 0), 4)
    if not ticker or sell_qty <= 0 or sell_price <= 0:
        return jsonify({"error": "Ticker, quantité et prix de vente requis"}), 400

    rid, asset = g.store.find_asset(ticker)
    if not asset:
        return jsonify({"error": f"Actif {ticker} introuvable"}), 404
    current_qty, buy_price = asset["qty"], asset["buy_price"]
    if sell_qty > current_qty:
        return jsonify({"error": f"Quantité insuffisante ({current_qty} disponibles)"}), 400

    gross = round(sell_price * sell_qty, 2)
    commission = round(gross * SELL_COMMISSION_RATE, 2)
    net = round(gross - commission, 2)
    realized_gl = round((sell_price - buy_price) * sell_qty - commission, 4)
    g.store.add("sold", {"ticker": ticker, "qty": sell_qty, "buy_price": buy_price, "sell_price": sell_price,
                         "gross": gross, "commission": commission, "net": net,
                         "realized_gl": realized_gl, "sold_date": datetime.date.today().isoformat()})
    remaining = round(current_qty - sell_qty, 4)
    if remaining <= 0:
        g.store.delete("asset", rid)
    else:
        g.store.update("asset", rid, rebuild(asset, shrink(get_lots(asset), remaining, 4), 4, 4))

    sign = "+" if realized_gl >= 0 else ""
    return jsonify({
        "success": True, "realized_gl": realized_gl, "commission": commission, "net": net,
        "message": f"Vente de {sell_qty} parts de {ticker} à {sell_price} € : brut {gross} € − commission {commission} € = {net} € ajoutés aux liquidités → PV réalisée : {sign}{realized_gl} €"
    })


@bp.route('/api/sold', methods=['GET'])
def get_sold():
    """Historique des ventes (brut, commission, net) et total des plus-values réalisées."""
    sales = []
    for rid, s in g.store.rows("sold"):
        gross = s.get("gross", round(s["sell_price"] * s["qty"], 2))
        commission = s.get("commission", s.get("fees", 0.0))  # anciennes ventes : pas de commission enregistrée
        sales.append({"id": rid, "ticker": s["ticker"], "qty": s["qty"], "buy_price": s["buy_price"],
                      "sell_price": s["sell_price"], "gross": gross, "commission": commission,
                      "net": s.get("net", round(gross - commission, 2)),
                      "realized_gl": s["realized_gl"], "sold_date": s.get("sold_date")})
    sales.sort(key=lambda x: (x["sold_date"] or "", x["id"]), reverse=True)
    return jsonify({"sales": sales, "total_realized_gl": round(sum(s["realized_gl"] for s in sales), 4),
                    "total_commission": round(sum(s["commission"] for s in sales), 2), "commission_rate": SELL_COMMISSION_RATE})

@bp.route('/api/sold/delete', methods=['POST'])
def delete_sale():
    """Annule une vente saisie par erreur.
    restore=true  : remet les parts dans le portefeuille (au prix de revient d'origine) et supprime la ligne -> retour EXACT à l'état d'avant la vente ;
    restore=false : supprime seulement la ligne d'historique (les parts ne sont pas remises)."""
    data = request.get_json(silent=True) or {}
    try:
        sale_id = int(data.get('id'))
    except (TypeError, ValueError):
        return jsonify({"error": "Vente introuvable"}), 404
    restore = bool(data.get('restore', True))
    sale = next((s for rid, s in g.store.rows("sold") if rid == sale_id), None)
    if sale is None:
        return jsonify({"error": "Vente introuvable"}), 404

    if restore:
        lot = {"date": None, "qty": sale["qty"], "price": sale["buy_price"], "raw_price": sale["buy_price"],
               "fees": 0.0, "cash_paid": 0.0}
        rid, existing = g.store.find_asset(sale["ticker"])
        if existing:
            lots = get_lots(existing)
            lot["id"] = next_id(lots)
            g.store.update("asset", rid, rebuild(existing, lots + [lot], 4, 4))
        else:
            lot["id"] = 1
            g.store.add("asset", rebuild({"ticker": sale["ticker"]}, [lot], 4, 4))
    g.store.delete("sold", sale_id)
    message = (f"Vente annulée : {sale['qty']} parts de {sale['ticker']} remises dans le portefeuille." if restore
               else "Ligne supprimée de l'historique (les parts n'ont pas été remises).")
    return jsonify({"success": True, "restored": restore, "message": message})

@bp.route('/api/lots/delete', methods=['POST'])
def delete_lot():
    """Supprime UNE entrée d'achat ; quantité et PRU de la ligne sont recalculés (la ligne disparaît si c'était la dernière)."""
    data = request.get_json(silent=True) or {}
    rid, asset = g.store.find_asset(_clean_ticker(data.get('ticker')))
    if not asset:
        return jsonify({"error": "Actif introuvable"}), 404
    lots = get_lots(asset)
    remaining = [l for l in lots if l["id"] != to_int(data.get('lot_id'))]
    if len(remaining) == len(lots):
        return jsonify({"error": "Entrée introuvable"}), 404
    if remaining:
        g.store.update("asset", rid, rebuild(asset, remaining, 4, 4))
    else:
        g.store.delete("asset", rid)
    return jsonify({"success": True, "position_deleted": not remaining})