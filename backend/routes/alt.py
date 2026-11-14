from concurrent.futures import ThreadPoolExecutor

import datetime

from flask import Blueprint, g, jsonify, request

from ..alt import COMMODITIES, CRYPTO_POPULAR, DEFAULT_CRYPTO, empty_history, get_quote, history_totals, valid_symbol
from ..utils import clean_float, to_int
from ..lots import get_lots, next_id, rebuild, shrink

bp = Blueprint("alt", __name__)


def _quotes(pairs):
    pairs = list(dict.fromkeys(pairs))
    with ThreadPoolExecutor(max_workers=6) as pool:
        return dict(zip(pairs, pool.map(lambda kv: get_quote(*kv), pairs)))


@bp.route('/api/alt/market', methods=['GET'])
def market_overview():
    """Cours du moment : principales cryptos + toutes les matières premières du catalogue."""
    pairs = [("crypto", s) for s in DEFAULT_CRYPTO] + [("commodity", s) for s in COMMODITIES]
    q = _quotes(pairs)
    return jsonify({"crypto": [q[("crypto", s)] for s in DEFAULT_CRYPTO],
                    "commodities": [q[("commodity", s)] for s in COMMODITIES],
                    "catalog": {"crypto": {k: v[0] for k, v in CRYPTO_POPULAR.items()},
                                "commodities": {k: dict(name=v["name"], unit=v["unit"], metal=v["metal"]) for k, v in COMMODITIES.items()}}})

def _alt_cash():
    """Liquidités disponibles = net de toutes les ventes + ajustements (achats payés avec les liquidités, apports, retraits)."""
    sales = sum(s.get("net", 0.0) for _, s in g.store.rows("altsold"))
    return round(sales + float(g.store.settings().get("alt_cash_adjust", 0.0)), 2)

@bp.route('/api/alt/quote', methods=['GET'])
def quote():
    kind = request.args.get("kind", "")
    symbol = (request.args.get("symbol") or "").strip().upper()
    if not valid_symbol(kind, symbol):
        return jsonify({"error": "Symbole inconnu"}), 400
    return jsonify(get_quote(kind, symbol))


@bp.route('/api/alt/holdings', methods=['GET'])
def holdings():
    rows = g.store.rows("alt")
    q = _quotes([(h["kind"], h["symbol"]) for _, h in rows])
    items, total_value, total_invested, total_usd = [], 0.0, 0.0, 0.0
    for rid, h in rows:
        quote_ = q[(h["kind"], h["symbol"])]
        grams = h.get("unit") == "g"
        price = quote_["price_per_g"] if grams else quote_["price"]
        price_usd = quote_["price_per_g_usd"] if grams else quote_["price_usd"]
        invested = h["qty"] * h["buy_price"]
        value = h["qty"] * price if price else None
        value_usd = h["qty"] * price_usd if price_usd else None
        items.append({"id": rid, **h, "lots": get_lots(h), "name": quote_["name"], "price": price, "price_usd": price_usd,
                      "invested": round(invested, 2),
                      "value": round(value, 2) if value is not None else None,
                      "value_usd": round(value_usd, 2) if value_usd is not None else None,
                      "pl": round(value - invested, 2) if value is not None else None,
                      "pl_pct": round((value / invested - 1) * 100, 2) if value is not None and invested else None,
                      "change_pct": quote_["change_pct"], "source": quote_["source"]})
        total_invested += invested
        if value is not None:
            total_value += value
        if value_usd is not None:
            total_usd += value_usd
    priced_invested = sum(i["invested"] for i in items if i["value"] is not None)
    cash = _alt_cash()
    return jsonify({"items": items, "total_value": round(total_value, 2), "total_value_usd": round(total_usd, 2),
                    "total_invested": round(total_invested, 2), "total_pl": round(total_value - priced_invested, 2),
                    "deposited": float(g.store.settings().get("alt_deposited", 0.0)),
                    "cash": max(cash, 0.0), "cash_inconsistent": cash < 0})

@bp.route('/api/alt/history', methods=['GET'])
def history():
    """Évolution de la valeur du portefeuille crypto/matières (quantités actuelles x cours passés)."""
    period = request.args.get("period", "1mo")
    if period not in ("1d", "5d", "1mo", "1y", "max"):
        return jsonify({"error": "Période invalide"}), 400
    rows = [h for _, h in g.store.rows("alt")]
    if not rows:
        return jsonify(empty_history(period) or {"dates": [], "totals": [], "missing": []})
    result = history_totals(rows, period)
    if not result:
        return jsonify({"error": "Pas de données"}), 404
    return jsonify(result)


@bp.route('/api/alt/add', methods=['POST'])
def add_holding():
    data = request.get_json(silent=True) or {}
    kind = data.get("kind")
    symbol = (data.get("symbol") or "").strip().upper()
    qty = clean_float(data.get("qty", 0), 8)
    buy_price = clean_float(data.get("buy_price", 0), 6)  # EUR par unité (ou par gramme si unité = g)
    fees = clean_float(data.get("fees", 0), 2)
    unit = data.get("unit") if data.get("unit") == "g" else "base"
    if not valid_symbol(kind, symbol):
        return jsonify({"error": "Symbole inconnu"}), 400
    if kind == "commodity" and unit == "g" and not COMMODITIES[symbol]["metal"]:
        return jsonify({"error": "Le gramme n'existe que pour les métaux précieux"}), 400
    if kind == "crypto":
        unit = "base"
    if qty <= 0 or buy_price <= 0 or fees < 0:
        return jsonify({"error": "Quantité et prix doivent être supérieurs à 0"}), 400
    cash_paid = 0.0
    if data.get("from_cash"):  # achat payé avec les liquidités issues des ventes
        cost = round(qty * buy_price + fees, 2)
        cash = _alt_cash()
        if cost > cash + 0.005:
            return jsonify({"error": f"Liquidités insuffisantes ({max(cash, 0):.2f} € disponibles pour {cost:.2f} € d'achat)"}), 400
        adjust = float(g.store.settings().get("alt_cash_adjust", 0.0))
        g.store.set_setting("alt_cash_adjust", round(adjust - cost, 2))
        cash_paid = cost
    lot_price = buy_price + fees / qty  # comme pour les ETF : les frais s'ajoutent au prix de revient
    new_lot = {"date": datetime.date.today().isoformat(), "qty": qty, "price": round(lot_price, 6),
               "raw_price": buy_price, "fees": fees, "cash_paid": cash_paid}
    for rid, h in g.store.rows("alt"):
        if h["kind"] == kind and h["symbol"] == symbol and h.get("unit", "base") == unit:
            lots = get_lots(h)
            new_lot["id"] = next_id(lots)
            g.store.update("alt", rid, rebuild(h, lots + [new_lot], 8, 6))
            return jsonify({"success": True})
    new_lot["id"] = 1
    g.store.add("alt", rebuild({"kind": kind, "symbol": symbol, "unit": unit}, [new_lot], 8, 6))
    return jsonify({"success": True})


@bp.route('/api/alt/delete', methods=['POST'])
def delete_holding():
    rid, h = _find_holding((request.get_json(silent=True) or {}).get('id'))
    if h:
        refund = sum(l.get("cash_paid", 0.0) for l in get_lots(h))
        if refund > 0:
            adjust = float(g.store.settings().get("alt_cash_adjust", 0.0))
            g.store.set_setting("alt_cash_adjust", round(adjust + refund, 2))
        g.store.delete("alt", rid)
    return jsonify({"success": True})

# ---------------------------------------------------------------- ventes (plus-values réalisées)
def _asset_name(kind, symbol):
    if kind == "crypto":
        return CRYPTO_POPULAR.get(symbol, (symbol, None))[0]
    return COMMODITIES.get(symbol, {}).get("name", symbol)


def _find_holding(hid):
    try:
        hid = int(hid)
    except (TypeError, ValueError):
        return None, None
    for rid, h in g.store.rows("alt"):
        if rid == hid:
            return rid, h
    return None, None


@bp.route('/api/alt/sell', methods=['POST'])
def sell_holding():
    """Vend tout ou partie d'une position. Prix et frais en EUR (le prix est par unité, ou par gramme si la position est en grammes)."""
    data = request.get_json(silent=True) or {}
    rid, h = _find_holding(data.get("id"))
    if not h:
        return jsonify({"error": "Position introuvable"}), 404
    qty = clean_float(data.get("qty", 0), 8)
    price = clean_float(data.get("sell_price", 0), 6)
    fees = clean_float(data.get("fees", 0), 2)
    if qty <= 0 or price <= 0 or fees < 0:
        return jsonify({"error": "Quantité et prix de vente doivent être supérieurs à 0"}), 400
    if qty > h["qty"] + 1e-9:
        return jsonify({"error": f"Quantité insuffisante ({h['qty']} disponibles)"}), 400

    gross = round(qty * price, 2)
    net = round(gross - fees, 2)
    realized = round((price - h["buy_price"]) * qty - fees, 2)
    g.store.add("altsold", {"kind": h["kind"], "symbol": h["symbol"], "name": _asset_name(h["kind"], h["symbol"]),
                            "unit": h.get("unit", "base"), "qty": qty, "buy_price": h["buy_price"], "sell_price": price,
                            "fees": fees, "gross": gross, "net": net, "realized_gl": realized,
                            "sold_date": datetime.date.today().isoformat()})
    remaining = round(h["qty"] - qty, 8)
    if remaining <= 1e-9:
        g.store.delete("alt", rid)
    else:
        g.store.update("alt", rid, rebuild(h, shrink(get_lots(h), remaining, 8), 8, 6))
    sign = "+" if realized >= 0 else ""
    return jsonify({"success": True, "realized_gl": realized, "net": net,
                    "message": f"Vente enregistrée : brut {gross} € − frais {fees} € = {net} € · plus-value réalisée {sign}{realized} €"})


@bp.route('/api/alt/sold', methods=['GET'])
def sold_history():
    sales = [dict(s, id=rid) for rid, s in g.store.rows("altsold")]
    sales.sort(key=lambda x: (x.get("sold_date") or "", x["id"]), reverse=True)
    return jsonify({"sales": sales, "total_realized_gl": round(sum(s["realized_gl"] for s in sales), 2),
                    "total_fees": round(sum(s.get("fees", 0.0) for s in sales), 2)})


@bp.route('/api/alt/sold/delete', methods=['POST'])
def delete_sold():
    """Annule une vente saisie par erreur : restore=true remet la quantité dans la position (retour à l'état d'avant), false supprime seulement la ligne."""
    data = request.get_json(silent=True) or {}
    try:
        sale_id = int(data.get("id"))
    except (TypeError, ValueError):
        return jsonify({"error": "Vente introuvable"}), 404
    sale = next((s for rid, s in g.store.rows("altsold") if rid == sale_id), None)
    if sale is None:
        return jsonify({"error": "Vente introuvable"}), 404
    restore = bool(data.get("restore", True))
    if restore:
        unit = sale.get("unit", "base")
        lot = {"date": None, "qty": sale["qty"], "price": sale["buy_price"], "raw_price": sale["buy_price"],
               "fees": 0.0, "cash_paid": 0.0}
        for rid, h in g.store.rows("alt"):
            if h["kind"] == sale["kind"] and h["symbol"] == sale["symbol"] and h.get("unit", "base") == unit:
                lots = get_lots(h)
                lot["id"] = next_id(lots)
                g.store.update("alt", rid, rebuild(h, lots + [lot], 8, 6))
                break
        else:
            lot["id"] = 1
            g.store.add("alt", rebuild({"kind": sale["kind"], "symbol": sale["symbol"], "unit": unit}, [lot], 8, 6))
    g.store.delete("altsold", sale_id)
    return jsonify({"success": True, "restored": restore})

@bp.route('/api/alt/cash', methods=['GET', 'POST'])
def alt_cash():
    """Liquidités du portefeuille crypto/matières. POST {amount} : apport (positif) ou retrait (négatif), en EUR."""
    if request.method == 'POST':
        amount = clean_float((request.get_json(silent=True) or {}).get("amount", 0), 2)
        if amount == 0:
            return jsonify({"error": "Montant invalide"}), 400
        if _alt_cash() + amount < -0.005:
            return jsonify({"error": "Liquidités insuffisantes pour ce retrait"}), 400
        adjust = float(g.store.settings().get("alt_cash_adjust", 0.0))
        g.store.set_setting("alt_cash_adjust", round(adjust + amount, 2))
    return jsonify({"cash": _alt_cash()})

@bp.route('/api/alt/deposited', methods=['GET', 'POST'])
def alt_deposited():
    """Total viré sur le wallet / compte crypto : base de calcul de la performance nette."""
    if request.method == 'POST':
        val = clean_float((request.get_json(silent=True) or {}).get("deposited", 0.0), 2)
        if val < 0:
            return jsonify({"error": "Le montant ne peut pas être négatif"}), 400
        g.store.set_setting("alt_deposited", val)
    return jsonify({"deposited": float(g.store.settings().get("alt_deposited", 0.0))})

@bp.route('/api/alt/lots/delete', methods=['POST'])
def delete_alt_lot():
    """Supprime UNE entrée d'achat ; si elle avait été payée avec les liquidités, elles sont remboursées."""
    data = request.get_json(silent=True) or {}
    rid, h = _find_holding(data.get("id"))
    if not h:
        return jsonify({"error": "Position introuvable"}), 404
    lots = get_lots(h)
    gone = next((l for l in lots if l["id"] == to_int(data.get("lot_id"))), None)
    if gone is None:
        return jsonify({"error": "Entrée introuvable"}), 404
    remaining = [l for l in lots if l is not gone and l["id"] != gone["id"]]
    refund = float(gone.get("cash_paid", 0.0))
    if refund > 0:
        adjust = float(g.store.settings().get("alt_cash_adjust", 0.0))
        g.store.set_setting("alt_cash_adjust", round(adjust + refund, 2))
    if remaining:
        g.store.update("alt", rid, rebuild(h, remaining, 8, 6))
    else:
        g.store.delete("alt", rid)
    return jsonify({"success": True, "refunded": refund, "position_deleted": not remaining})