"""Logique métier partagée entre plusieurs routes."""
import yfinance as yf

from .gap import estimate_gap
from .prices import fetch_price_boursorama, get_yf_session
from .utils import clean_float


def fetch_ticker_data(ticker, buy_price, qty):
    """Récupère les données de l'actif, incluant l'écart estimé avec le marché américain et le graph du jour."""
    session = get_yf_session()
    dates, prices = [], []
    stock = None

    # Historique graphique ciblé sur la journée en cours (1d, intervalle 15m)
    try:
        stock = yf.Ticker(ticker, session=session)
        hist = stock.history(period="1d", interval="15m")
        if hist is None or hist.empty or len(hist) < 2:
            hist = stock.history(period="5d")
            
        if hist is not None and not hist.empty and 'Close' in hist.columns:
            hist = hist.dropna(subset=['Close'])
            dates = hist.index.strftime('%Y-%m-%d %H:%M').tolist()
            prices = [clean_float(p, 4) for p in hist['Close'].tolist()]
    except Exception as e:
        print(f"Avertissement historique Yahoo pour {ticker}: {e}")

    # Prix courant : Boursorama (ou fallback sur le prix d'achat)
    bourso_price = fetch_price_boursorama(ticker)
    if bourso_price and bourso_price > 0:
        current_close = clean_float(bourso_price, 4)
    else:
        current_close = clean_float(buy_price, 4)
        print(f"[{ticker.upper()}] Boursorama indisponible, fallback sur prix d'achat.")

    # Métadonnées complémentaires via yfinance (info)
    open_price = prev_close = day_high = day_low = current_close
    summary = "Aucun objectif de gestion ou description disponible."
    name = ticker.upper()

    try:
        if stock:
            info = stock.info or {}
            open_price = clean_float(info.get('regularMarketOpen') or current_close, 4)
            prev_close = clean_float(info.get('previousClose') or current_close, 4)
            day_high = clean_float(info.get('regularMarketDayHigh') or current_close, 4)
            day_low = clean_float(info.get('regularMarketDayLow') or current_close, 4)
            summary = info.get('longBusinessSummary') or summary
            name = str(info.get('shortName') or ticker).upper()
    except Exception:
        pass

    # Calculs financiers – tout en 4 décimales
    qty_clean = clean_float(qty, 4)
    buy_price_clean = clean_float(buy_price, 4)
    invested_value = clean_float(buy_price_clean * qty_clean, 4)
    total_value = clean_float(current_close * qty_clean, 4)
    gain_loss = clean_float(total_value - invested_value, 4)
    gain_loss_pct = clean_float((gain_loss / invested_value) * 100, 4) if invested_value > 0 else 0.0

    # ÉCART ESTIMÉ À L'OUVERTURE (US + Europe + Asie, converti en EUR) -> voir section 7
    proxy_name, estimated_gap_pct, estimated_gap_eur, estimated_price = estimate_gap(ticker, current_close)

    return {
        "ticker": ticker.upper(),
        "name": name,
        "currency_symbol": "€",
        "current_price": current_close,
        "open_price": open_price,
        "prev_close": prev_close,
        "day_high": day_high,
        "day_low": day_low,
        "summary": str(summary),
        "qty": qty_clean,
        "buy_price": buy_price_clean,
        "invested_value": invested_value,
        "total_value": total_value,
        "gain_loss": gain_loss,
        "gain_loss_pct": gain_loss_pct,
        "dates": dates,
        "prices": prices,
        "proxy_name": proxy_name,
        "estimated_gap_pct": estimated_gap_pct,
        "estimated_gap_eur": estimated_gap_eur,
        "estimated_price": estimated_price
    }


def cash_state(store):
    """Liquidité calculée à partir des données (déchiffrées) de l'utilisateur : une seule définition, utilisée partout.
    disponible = total viré - coût d'achat des lignes + plus-values réalisées - cash bloqué par les ordres."""
    settings = store.settings()
    pru_sum = sum(a["buy_price"] * a["qty"] for _, a in store.rows("asset"))
    realized = sum(s.get("realized_gl", 0.0) for _, s in store.rows("sold"))
    locked = sum(p["qty"] * p["limit_price"] for _, p in store.rows("pending"))
    deposited = float(settings.get("total_deposited", 0.0))
    other_fees = float(settings.get("other_fees", 0.0))  # frais déjà payés non rattachés à une ligne (ex. courtage d'une ancienne opération)
    raw = round(deposited - pru_sum + realized - locked - other_fees, 4)
    return {
        "deposited": deposited,
        "other_fees": other_fees,
        "pru_sum": pru_sum,
        "realized": realized,
        "locked": round(locked, 4),
        "available_raw": raw,
        "available": max(0.0, raw),  # sécurité anti-négatif (le brut reste exposé pour détecter une saisie incohérente)
    }
