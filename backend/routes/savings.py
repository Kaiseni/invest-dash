from flask import Blueprint, g, jsonify, request

from ..utils import clean_float,to_int

bp = Blueprint("savings", __name__)


@bp.route('/api/savings', methods=['GET', 'POST'])
def handle_savings():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        bank = (data.get('bank') or 'Banque').strip()
        name = (data.get('name') or 'Livret').strip()
        g.store.add("saving", {
            "bank": bank, "name": name,
            "balance": clean_float(data.get('balance', 0), 2),
            "rate": clean_float(data.get('rate', 1.7), 2),
            "earned_interest": clean_float(data.get('earned_interest', 0.0), 2)})
        return jsonify({"success": True})

    savings_list = []
    for rid, s in g.store.rows("saving"):
        bal, rt = s["balance"], s["rate"]
        annual_interest = round(bal * (rt / 100.0), 2)
        savings_list.append({
            "id": rid, "bank": s["bank"], "name": s["name"], "balance": bal, "rate": rt,
            "earned_interest": s.get("earned_interest") or 0.0,
            "annual_interest": annual_interest,
            "monthly_interest": round(annual_interest / 12.0, 2)})
    savings_list.sort(key=lambda x: x["balance"], reverse=True)
    return jsonify(savings_list)


@bp.route('/api/savings/update', methods=['POST'])
def update_saving():
    """Route pour modifier un livret existant."""
    data = request.get_json(silent=True) or {}
    saving_id = data.get('id')
    bank = (data.get('bank') or '').strip()
    name = (data.get('name') or '').strip()
    if not saving_id:
        return jsonify({"error": "ID requis"}), 400
    if not bank or not name:
        return jsonify({"error": "Banque et nom requis"}), 400
    if not any(rid == saving_id for rid, _ in g.store.rows("saving")):
        return jsonify({"error": "Livret introuvable"}), 404
    g.store.update("saving", saving_id, {
        "bank": bank, "name": name,
        "balance": clean_float(data.get('balance'), 2),
        "rate": clean_float(data.get('rate'), 2),
        "earned_interest": clean_float(data.get('earned_interest', 0.0), 2)})
    return jsonify({"success": True})


@bp.route('/api/savings/delete', methods=['POST'])
def delete_saving():
    rid = to_int((request.get_json(silent=True) or {}).get('id'))
    if rid is not None:
        g.store.delete("saving", rid)
    return jsonify({"success": True})
