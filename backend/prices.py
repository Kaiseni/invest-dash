"""Sources de prix : Boursorama (référence), Yahoo Finance, Google Finance."""
import threading
import time

import requests
import yfinance as yf
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

from .utils import clean_float

_local = threading.local()


def get_yf_session():
    """Session furtive anti-bot, une par thread (réutilisée, au lieu d'en recréer une à chaque appel)."""
    sess = getattr(_local, "session", None)
    if sess is not None:
        return sess
    for browser in ["chrome", "edge", "safari"]:
        try:
            sess = cffi_requests.Session(impersonate=browser)
            break
        except Exception:
            continue
    if sess is None:
        sess = requests.Session()
        sess.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        })
    _local.session = sess
    return sess


# ---------------------------------------------------------------- sources
def fetch_price_yahoo(stock, hist):
    """Source 1 : Yahoo Finance"""
    try:
        if hist is not None and not hist.empty and 'Close' in hist.columns:
            price = clean_float(hist['Close'].iloc[-1], 4, default=0.0)
            if price > 0:
                return price
        if stock is not None:
            info = stock.info or {}
            price = clean_float(info.get('regularMarketPrice') or info.get('previousClose'), 4, default=0.0)
            return price if price > 0 else None
    except Exception:
        pass
    return None


def fetch_price_google(ticker):
    """Source 2 : Google Finance (Conversion automatique des tickers .PA vers EPA)"""
    try:
        if ticker.upper().endswith('.PA'):
            g_ticker = f"{ticker[:-3].upper()}:EPA"
        elif ticker.upper().endswith('.DE'):
            g_ticker = f"{ticker[:-3].upper()}:ETR"
        else:
            g_ticker = f"{ticker.upper()}:NASDAQ"

        url = f"https://www.google.com/finance/quote/{g_ticker}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36"}
        resp = requests.get(url, headers=headers, timeout=4)
        
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            price_div = soup.find('div', class_='YMlKec fxKbKc')
            if price_div:
                price = clean_float(price_div.text, 4, default=0.0)
                return price if price > 0 else None
    except Exception:
        pass
    return None


def _scrape_boursorama(ticker):
    """Source Boursorama : recherche le ticker et extrait le cours précis (4 décimales) dans la faceplate."""
    clean_sym = ticker.split('.')[0].upper()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
    
    # 1. Tentative via redirection automatique recherche
    urls_to_try = [
        f"https://www.boursorama.com/recherche/?query={clean_sym}",
        f"https://www.boursorama.com/bourse/trackers/cours/1rT{clean_sym}/",
        f"https://www.boursorama.com/bourse/actions/cours/1rP{clean_sym}/"
    ]
    
    for url in urls_to_try:
        try:
            resp = requests.get(url, headers=headers, timeout=5, allow_redirects=True)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                # Cible prioritaire : le bloc principal du cours (c-faceplate__price)
                faceplate = soup.find('div', class_='c-faceplate__price')
                if faceplate:
                    span = faceplate.find('span', class_='c-instrument--last')
                    if span:
                        price = clean_float(span.text, 4, default=0.0)
                        if price > 0:
                            return price
                
                # Cible secondaire : premier span c-instrument--last du corps
                main_content = soup.find('main') or soup.find('div', class_='l-main') or soup
                span = main_content.find('span', class_='c-instrument--last')
                if span:
                    price = clean_float(span.text, 4, default=0.0)
                    if price > 0:
                        return price
        except Exception:
            continue
            
    return None


# Cache court : évite de re-scraper Boursorama à chaque rafraîchissement / chaque route.
_PRICE_CACHE = {}
_PRICE_TTL = 45  # secondes


def fetch_price_boursorama(ticker):
    key = ticker.upper()
    hit = _PRICE_CACHE.get(key)
    if hit and time.time() - hit[0] < _PRICE_TTL:
        return hit[1]
    price = _scrape_boursorama(ticker)
    if price:
        _PRICE_CACHE[key] = (time.time(), price)
    return price


def get_live_price(ticker, fallback=0.0):
    """Prix courant avec la même source que le tableau de bord : Boursorama, puis Yahoo, puis Google."""
    price = fetch_price_boursorama(ticker)
    if price:
        return price
    try:
        hist = yf.Ticker(ticker, session=get_yf_session()).history(period="5d")
        if hist is not None and not hist.empty:
            closes = hist["Close"].dropna()
            if not closes.empty and float(closes.iloc[-1]) > 0:
                return float(closes.iloc[-1])
    except Exception:
        pass
    return fetch_price_google(ticker) or fallback
