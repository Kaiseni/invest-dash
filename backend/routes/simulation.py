import datetime

import numpy as np
import pandas as pd
import yfinance as yf
from flask import Blueprint, g, jsonify, request

from ..prices import get_yf_session
from ..services import cash_state

bp = Blueprint("simulation", __name__)


@bp.route('/api/simulation', methods=['POST'])
def run_simulation():
    data = request.json or {}
    years = int(data.get('years', 10))
    years = max(1, min(years, 100))
    monthly = max(0.0, float(data.get('monthly', 0) or 0))
    annual_contrib = monthly * 12 

    try:
        store = g.store
        # 1. ETF (risqué)
        rows = [(a['ticker'], a['qty']) for _, a in store.rows('asset')]
        # 2. Livrets et cash (sécurisé)
        savings_rows = [(sv['balance'], sv['rate']) for _, sv in store.rows('saving')]
        # Liquidité = disponible + bloquée par les ordres en attente
        cs = cash_state(store)
        cash = float(cs["available"] + cs["locked"])
            
        if not rows and not savings_rows and cash == 0 and monthly == 0:
            return jsonify({"error": "Votre patrimoine est vide."}), 400

        # --- PARTIE 1 : Actifs Risqués (Mouvement Brownien sur les ETF) ---
        total_risky_value = 0.0
        if rows:
            tickers_db = [r[0] for r in rows]
            qty_map = {r[0]: r[1] for r in rows}

            session = get_yf_session()
            df = yf.download(tickers_db, period="5y", interval="1d", session=session, progress=False)
            
            if 'Close' in df.columns:
                df = df['Close']
            if len(tickers_db) == 1 and isinstance(df, pd.Series):
                df = df.to_frame(name=tickers_db[0])
                
            df = df.dropna(how='all', axis=1)
            valid_tickers = list(df.columns)

            current_prices = []
            clean_qtys = []
            for t in valid_tickers:
                series = df[t].dropna()
                if not series.empty:
                    current_prices.append(float(series.iloc[-1]))
                    clean_qtys.append(qty_map.get(t, 0))
                else:
                    current_prices.append(0.0)
                    clean_qtys.append(0.0)

            total_risky_value = sum(q * p for q, p in zip(clean_qtys, current_prices))
            
            if total_risky_value > 0:
                weights = np.array([(q * p) / total_risky_value for q, p in zip(clean_qtys, current_prices)])
                returns = df[valid_tickers].pct_change().dropna(how='all')
                cov_matrix = (returns.cov() * 252).fillna(0)
                port_mu = 0.08 # Plafonné pour éviter un délire statistique sur 100 ans
                port_sigma = np.sqrt(np.dot(weights.T, np.dot(cov_matrix.values, weights)))
                port_sigma = max(port_sigma, 0.05)
            else:
                port_mu, port_sigma = 0.0, 0.0
        else:
            port_mu, port_sigma = 0.0, 0.0
        
        if total_risky_value == 0 and monthly > 0:   # rien en bourse encore : hypothèses par défaut
            port_mu, port_sigma = 0.08, 0.15

        # Moteur probabiliste sur 1000 scénarios
        num_simulations = 1000
        sim_paths = np.zeros((years + 1, num_simulations))
        sim_paths[0] = total_risky_value

        if total_risky_value > 0 or annual_contrib > 0:
            Z = np.random.standard_normal((years, num_simulations))
            growth = np.exp((port_mu - 0.5 * port_sigma ** 2) + port_sigma * Z)
            for y in range(1, years + 1):
                # le versement de l'année est investi, puis l'ensemble évolue
                sim_paths[y] = (sim_paths[y - 1] + annual_contrib) * growth[y - 1]

        # --- PARTIE 2 : Actifs Sécurisés (Capitalisation des Livrets + Cash) ---
        # On ajoute mathématiquement la capitalisation à TOUS les scénarios pour chaque année
        for y in range(years + 1):
            safe_value_y = cash
            for bal, rate in savings_rows:
                # Formule des intérêts composés : Solde * (1 + Taux)^Années
                safe_value_y += bal * ((1 + (rate / 100.0)) ** y)
            
            # On additionne la valeur sécurisée capitalisée à la valeur boursière simulée
            sim_paths[y, :] += safe_value_y

        # --- EXTRACTION DES STATISTIQUES ---
        percentile_10 = np.percentile(sim_paths, 10, axis=1).tolist()
        percentile_50 = np.percentile(sim_paths, 50, axis=1).tolist()
        percentile_90 = np.percentile(sim_paths, 90, axis=1).tolist()

        current_year = datetime.datetime.now().year
        labels = [str(current_year + y) for y in range(years + 1)]

        median_path = np.array(percentile_50)
        roll_max = np.maximum.accumulate(median_path)
        # np.where évite la division par zéro si le patrimoine démarre à 0
        drawdowns = np.where(roll_max > 0, (median_path - roll_max) / roll_max, 0)
        max_drawdown = abs(drawdowns.min()) * 100

        sharpe = (port_mu - 0.03) / port_sigma if port_sigma > 0 else 0.0

        initial_total = total_risky_value + cash + sum(b for b, _ in savings_rows)
        contributed = [round(initial_total + annual_contrib * y, 2) for y in range(years + 1)]

        return jsonify({
            "labels": labels,
            "median": [round(x, 2) for x in percentile_50],
            "optimistic": [round(x, 2) for x in percentile_90],
            "pessimistic": [round(x, 2) for x in percentile_10],
            "contributed": contributed,
            "mu": round(port_mu * 100, 2),
            "sigma": round(port_sigma * 100, 2),
            "max_drawdown": round(max_drawdown, 2),
            "sharpe": round(sharpe, 2)
        })

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 400
