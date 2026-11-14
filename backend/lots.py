"""Entrées d'achat (lots) d'une position. `qty` et `buy_price` de la position sont toujours recalculés à partir des lots :
le reste du code (liquidité, graphiques, simulateur) continue de les lire comme avant."""


def get_lots(pos):
    lots = pos.get("lots")
    if lots:
        return [dict(l) for l in lots]
    if pos.get("qty", 0) > 0:  # position créée avant les lots : une seule entrée « ancienne saisie »
        return [{"id": 1, "date": None, "qty": pos["qty"], "price": pos["buy_price"], "raw_price": pos["buy_price"],
                 "fees": pos.get("fees_paid", 0.0), "cash_paid": 0.0}]
    return []


def next_id(lots):
    return max((l["id"] for l in lots), default=0) + 1


def rebuild(pos, lots, qty_digits, price_digits):
    qty = round(sum(l["qty"] for l in lots), qty_digits)
    cost = sum(l["qty"] * l["price"] for l in lots)
    out = dict(pos)
    out.update(lots=lots, qty=qty, buy_price=round(cost / qty, price_digits) if qty > 0 else 0.0,
               fees_paid=round(sum(l.get("fees", 0.0) for l in lots), 2))
    return out


def shrink(lots, new_total, qty_digits):
    """Vente partielle : chaque lot diminue dans la même proportion, donc le PRU ne change pas."""
    old_total = sum(l["qty"] for l in lots)
    if old_total <= 0:
        return []
    ratio = new_total / old_total
    out = []
    for l in lots:
        n = dict(l)
        n["qty"] = round(l["qty"] * ratio, qty_digits)
        for k in ("fees", "cash_paid"):
            n[k] = round(l.get(k, 0.0) * ratio, 2)
        out.append(n)
    out[-1]["qty"] = round(out[-1]["qty"] + (new_total - sum(l["qty"] for l in out)), qty_digits)  # l'arrondi va au dernier lot
    return [l for l in out if l["qty"] > 0]