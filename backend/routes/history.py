import pandas as pd
import yfinance as yf
from flask import Blueprint, g, jsonify, request

from ..prices import get_yf_session

bp = Blueprint("history", __name__)


@bp.route('/api/history', methods=['GET'])
def get_history():
    ticker = request.args.get('ticker')
    period = request.args.get('period', '1mo')
    interval = "5m" if period == "1d" else "15m" if period == "5d" else "1d"
        
    try:
        hist = yf.Ticker(ticker, session=get_yf_session()).history(period=period, interval=interval)
        if hist is None or hist.empty:
            return jsonify({"error": "Pas de données"}), 404
            
        date_format = '%d %b %H:%M' if interval != "1d" else '%Y-%m-%d'
        return jsonify({
            "dates": hist.index.strftime(date_format).tolist(), 
            "prices": hist['Close'].round(4).tolist()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@bp.route('/api/portfolio_history', methods=['GET'])
def get_portfolio_history():
    """Valeur des titres actuellement détenus (quantités actuelles x cours historiques).
    NB : ne contient PAS la liquidité, elle est ajoutée côté front pour rester cohérente avec le patrimoine affiché."""
    period = request.args.get('period', '1mo')
    interval = "5m" if period == "1d" else "15m" if period == "5d" else "1d"

    rows = [(a['ticker'], a['qty']) for _, a in g.store.rows('asset')]

    if not rows:
        return jsonify({"dates": [], "totals": []})

    try:
        session = get_yf_session()
        qty_dict = dict(rows)
        series = {}

        for ticker in qty_dict:
            hist = yf.Ticker(ticker, session=session).history(period=period, interval=interval)
            if hist is None or hist.empty or 'Close' not in hist.columns:
                continue
            close = hist['Close'].dropna()
            close = close[close > 0]
            if close.empty:
                continue

            # Fuseaux horaires homogènes entre tickers (sinon l'alignement des dates est faux)
            idx = close.index
            if idx.tz is not None:
                idx = idx.tz_convert('Europe/Paris')
            if interval == "1d":
                idx = idx.tz_localize(None).normalize() if idx.tz is not None else idx.normalize()
            close.index = idx
            close = close[~close.index.duplicated(keep='last')]
            series[ticker] = close

        if not series:
            return jsonify({"error": "Pas de données"}), 404

        # Union de TOUTES les dates (et non la série la plus longue) puis propagation des cours manquants
        df = pd.DataFrame(series).sort_index().ffill().bfill()
        totals = sum(df[t] * qty_dict[t] for t in df.columns)

        date_format = '%d %b %H:%M' if interval in ["5m", "15m"] else '%Y-%m-%d'
        return jsonify({
            "dates": df.index.strftime(date_format).tolist(),
            "totals": [round(float(t), 2) for t in totals]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400
