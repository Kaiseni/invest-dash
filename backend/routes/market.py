import datetime
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime

import cloudscraper
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup
from flask import Blueprint, g, jsonify

from ..prices import get_live_price, get_yf_session
from ..utils import clean_float

bp = Blueprint("market", __name__)


@bp.route('/api/news', methods=['GET'])
def get_news():
    rows = [(t,) for t in sorted({a['ticker'] for _, a in g.store.rows('asset')})]

    TICKER_INDEX_MAP = {
        "WORLD": ["WORLD", "WPEA", "CW8", "DCAM", "VWCE", "URTH", "IWDA"], 
        "NASDAQ": ["NASDAQ", "PNAS", "LQQ", "QQQ", "UST", "EQQQ"],
        "EMERGING": ["EMERGING", "EMERGENT", "PAEEM", "PAASI", "ASIA", "EMIM"], 
        "SP500": ["S&P", "SP500", "ESE", "PSP5", "CSPX", "SXR8", "VUSA", "VUAA", "CSSPX", "500"], 
        "CAC40": ["CAC", "CAC40"]
    }
    INDEX_COMPANIES = {
        "WORLD": ["Apple", "Nvidia", "Microsoft"], "NASDAQ": ["Apple", "Nvidia", "Microsoft"],
        "EMERGING": ["TSMC", "Tencent", "Samsung"], "SP500": ["Apple", "Nvidia", "Microsoft"], "CAC40": ["LVMH", "TotalEnergies", "Sanofi"]
    }
    INDEX_QUERIES = {
        "WORLD": '"MSCI World" OR "Bourse mondiale"', "NASDAQ": '"Nasdaq" OR "Tech américaine"',
        "EMERGING": '"Marchés émergents" OR "Chine bourse"', "SP500": '"S&P 500" OR "Wall Street"', "CAC40": '"CAC 40" OR "Bourse de Paris"'
    }

    active_indices = set()
    ticker_badge = {}
    for (ticker,) in rows:
        t_up = ticker.upper()
        for idx, keywords in TICKER_INDEX_MAP.items():
            if any(k in t_up for k in keywords):
                active_indices.add(idx)
                ticker_badge.setdefault(idx, []).append(ticker)
                break

    search_jobs = []
    for idx in active_indices:
        badge = " & ".join(ticker_badge.get(idx, [idx]))
        if idx in INDEX_QUERIES:
            search_jobs.append({"query": INDEX_QUERIES[idx], "badge": badge, "ticker": ticker_badge.get(idx, [""])[0], "max_articles": 3})
        for company in INDEX_COMPANIES.get(idx, []):
            search_jobs.append({"query": f'"{company}" (bourse OR action OR résultats)', "badge": company, "ticker": ticker_badge.get(idx, [""])[0], "max_articles": 1})

    pos_words = ['hausse', 'bondit', 'record', 'progresse', 'bénéfice', 'croissance', 'rebond', 'succès']
    neg_words = ['baisse', 'chute', 'plonge', 'crainte', 'recul', 'alerte', 'effondre', 'perte', 'correction']

    def run_job(job):
        candidates = []
        try:
            query = urllib.parse.quote(f"{job['query']} when:7d")
            url = f"https://news.google.com/rss/search?q={query}&hl=fr&gl=FR&ceid=FR:fr"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            root = ET.fromstring(urllib.request.urlopen(req, timeout=5).read())
            for item in root.findall('.//item')[:10]:
                link_el, title_el = item.find('link'), item.find('title')
                if link_el is None or title_el is None or not link_el.text or not title_el.text:
                    continue
                title = title_el.text
                title_lower = title.lower()
                sentiment = "neu"
                if any(w in title_lower for w in pos_words):
                    sentiment = "pos"
                elif any(w in title_lower for w in neg_words):
                    sentiment = "neg"
                source_el, date_el = item.find('source'), item.find('pubDate')
                candidates.append({
                    "ticker": job["ticker"], "display_badge": job["badge"],
                    "title": title, "link": link_el.text, "sentiment": sentiment,
                    "publisher": source_el.text if source_el is not None and source_el.text else "Actu",
                    "time_str": date_el.text if date_el is not None and date_el.text else ""
                })
        except Exception:
            pass
        return candidates

    with ThreadPoolExecutor(max_workers=6) as pool:
        job_results = list(pool.map(run_job, search_jobs))

    all_news, seen_links = [], set()
    for job, candidates in zip(search_jobs, job_results):
        count = 0
        for art in candidates:
            if count >= job["max_articles"]:
                break
            if art["link"] in seen_links:
                continue
            seen_links.add(art["link"])
            all_news.append(art)
            count += 1

    def _date_key(article):
        try:
            return parsedate_to_datetime(article["time_str"])
        except Exception:
            return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

    all_news.sort(key=_date_key, reverse=True)
    return jsonify(all_news[:20])


@bp.route('/api/holdings', methods=['GET'])
def get_holdings():
    rows = [(a['ticker'], a['buy_price'], a['qty']) for _, a in g.store.rows('asset')]

    session = get_yf_session()
    PROXY_ISINS = {
        "WORLD": "IE00B4L5Y983",    
        "NASDAQ": "IE00B53SZB19",   
        "EMERGING": "IE00BKM4GZ66", 
        "SP500": "IE00B5BMR087",    
        "CAC40": "FR0007052782"     
    }

    FALLBACK_HOLDINGS = {
        "WORLD": [
            {"name": "Apple Inc.", "percent": 4.85}, {"name": "Nvidia Corp.", "percent": 4.62},
            {"name": "Microsoft Corp.", "percent": 4.38}, {"name": "Amazon.com Inc.", "percent": 2.65},
            {"name": "Meta Platforms", "percent": 1.85}, {"name": "Alphabet Inc. (A)", "percent": 1.45},
            {"name": "Alphabet Inc. (C)", "percent": 1.25}, {"name": "Broadcom Inc.", "percent": 1.15},
            {"name": "Tesla Inc.", "percent": 1.05}, {"name": "Eli Lilly & Co.", "percent": 0.98}
        ],
        "NASDAQ": [
            {"name": "Apple Inc.", "percent": 8.95}, {"name": "Nvidia Corp.", "percent": 8.45},
            {"name": "Microsoft Corp.", "percent": 8.10}, {"name": "Broadcom Inc.", "percent": 5.20},
            {"name": "Amazon.com Inc.", "percent": 5.05}, {"name": "Meta Platforms", "percent": 4.85},
            {"name": "Tesla Inc.", "percent": 3.40}, {"name": "Costco Wholesale", "percent": 2.75},
            {"name": "Alphabet Inc. (A)", "percent": 2.65}, {"name": "Alphabet Inc. (C)", "percent": 2.55}
        ],
        "EMERGING": [
            {"name": "TSMC (Taiwan Semi.)", "percent": 9.80}, {"name": "Tencent Holdings", "percent": 4.25},
            {"name": "Samsung Electronics", "percent": 3.10}, {"name": "Alibaba Group", "percent": 2.45},
            {"name": "Reliance Industries", "percent": 1.35}, {"name": "Meituan", "percent": 1.25},
            {"name": "HDFC Bank", "percent": 1.10}, {"name": "PDD Holdings", "percent": 1.05},
            {"name": "ICICI Bank", "percent": 0.98}, {"name": "Infosys Ltd.", "percent": 0.90}
        ],
        "SP500": [
            {"name": "Apple Inc.", "percent": 7.10}, {"name": "Nvidia Corp.", "percent": 6.80},
            {"name": "Microsoft Corp.", "percent": 6.50}, {"name": "Amazon.com Inc.", "percent": 3.80},
            {"name": "Meta Platforms", "percent": 2.50}, {"name": "Alphabet Inc. (A)", "percent": 2.10},
            {"name": "Berkshire Hathaway", "percent": 1.70}, {"name": "Broadcom Inc.", "percent": 1.65},
            {"name": "Eli Lilly & Co.", "percent": 1.40}, {"name": "Tesla Inc.", "percent": 1.35}
        ],
        "CAC40": [
            {"name": "LVMH", "percent": 10.50}, {"name": "TotalEnergies", "percent": 8.80},
            {"name": "Schneider Electric", "percent": 8.20}, {"name": "Sanofi", "percent": 6.90},
            {"name": "Air Liquide", "percent": 6.10}, {"name": "Airbus", "percent": 5.40},
            {"name": "L'Oréal", "percent": 5.10}, {"name": "Hermès International", "percent": 4.80},
            {"name": "BNP Paribas", "percent": 4.20}, {"name": "AXA", "percent": 3.90}
        ]
    }

    # Dictionnaire de correspondances Nom d'entreprise -> Ticker pour la performance en direct
    HOLDINGS_TICKER_MAP = {
        "Apple": "AAPL", "Nvidia": "NVDA", "Microsoft": "MSFT", "Amazon": "AMZN",
        "Meta": "META", "Alphabet": "GOOGL", "Broadcom": "AVGO", "Tesla": "TSLA",
        "Eli Lilly": "LLY", "TSMC": "TSM", "Tencent": "TCEHY", "Samsung": "SMSN.IL",
        "Alibaba": "BABA", "ASML": "ASML", "LVMH": "MC.PA", "TotalEnergies": "TTE.PA",
        "Schneider": "SU.PA", "Sanofi": "SAN.PA", "Air Liquide": "AI.PA",
        "Airbus": "AIR.PA", "L'Oréal": "OR.PA", "Hermès": "RMS.PA", "AMD": "AMD",
        "Costco": "COST", "Berkshire": "BRK-B", "Reliance": "RELIANCE.NS",
        "HDFC": "HDFCBANK.NS", "Infosys": "INFY", "Meituan": "3690.HK"
    }

    try:
        scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
    except Exception:
        scraper = None

    scraped_cache = {}
    results = []

    for ticker, buy_price, qty in rows:
        t_up = ticker.upper()
        name = t_up
        current_price = clean_float(buy_price, 4)

        # Même source de prix que le tableau de bord (avant : Yahoo ici, Boursorama ailleurs -> petits écarts)
        current_price = get_live_price(ticker, fallback=current_price)
        try:
            name = (yf.Ticker(ticker, session=session).info or {}).get('shortName', t_up).upper()
        except Exception:
            pass

        total_value = current_price * clean_float(qty, 4)
        
        proxy_key = None
        if any(k in name or k in t_up for k in ["WORLD", "WPEA", "CW8", "DCAM"]):
            proxy_key = "WORLD"
        elif any(k in name or k in t_up for k in ["NASDAQ", "PNAS", "LQQ"]):
            proxy_key = "NASDAQ"
        elif any(k in name or k in t_up for k in ["EMERGING", "EMERGENT", "PAEEM", "PAASI", "ASIA"]):
            proxy_key = "EMERGING"
        elif any(k in name or k in t_up for k in ["S&P", "SP500", "PSP5", "ESE"]):
            proxy_key = "SP500"
        elif "CAC" in name:
            proxy_key = "CAC40"

        raw_holdings = []
        if proxy_key:
            if proxy_key in scraped_cache:
                raw_holdings = scraped_cache[proxy_key]
            else:
                if scraper and proxy_key in PROXY_ISINS:
                    url = f"https://www.justetf.com/fr/etf-profile.html?isin={PROXY_ISINS[proxy_key]}"
                    try:
                        response = scraper.get(url, timeout=4)
                        if response.status_code == 200:
                            soup = BeautifulSoup(response.text, 'html.parser')
                            for table in soup.find_all('table'):
                                temp_holdings = []
                                rows_tr = (table.find('tbody') or table).find_all('tr')
                                for tr in rows_tr:
                                    cols = tr.find_all(['td', 'th'])
                                    if len(cols) >= 2:
                                        c_name = cols[0].text.strip()
                                        c_pct = clean_float(cols[-1].text.replace('%', ''), 2, default=-1.0)
                                        if 0 < c_pct <= 100 and c_name.lower() not in ['total', 'autres', 'other']:
                                            temp_holdings.append({"name": c_name, "percent": c_pct})
                                if len(temp_holdings) >= 3:
                                    raw_holdings = temp_holdings
                                    break
                    except Exception:
                        print(f"JustETF bloqué ou lent pour {proxy_key}, bascule sur les données de secours.")
                
                if not raw_holdings and proxy_key in FALLBACK_HOLDINGS:
                    raw_holdings = FALLBACK_HOLDINGS[proxy_key]
                
                scraped_cache[proxy_key] = raw_holdings

        holdings_list = []
        for h in raw_holdings[:10]:
            holdings_list.append({
                "name": h["name"],
                "percent": h["percent"],
                "value": round((h["percent"] / 100.0) * total_value, 2)
            })

        holdings_list.sort(key=lambda x: x['percent'], reverse=True)
        results.append({
            "ticker": ticker,
            "name": name,
            "total_value": round(total_value, 4),
            "holdings": holdings_list
        })

    # --- NOUVEAU : Récupération des performances en direct des sous-jacents ---
    unique_tickers_map = {}
    for res in results:
        for h in res["holdings"]:
            for key_name, tkr in HOLDINGS_TICKER_MAP.items():
                if key_name.lower() in h["name"].lower():
                    unique_tickers_map[h["name"]] = tkr
                    break

    tickers_to_fetch = list(set(unique_tickers_map.values()))
    live_perfs = {}
    
    if tickers_to_fetch:
        try:
            # Téléchargement groupé optimisé
            df = yf.download(tickers_to_fetch, period="5d", interval="1d", session=session, progress=False)
            if 'Close' in df.columns:
                close_df = df['Close']
                if len(tickers_to_fetch) == 1 and isinstance(close_df, pd.Series):
                    close_df = close_df.to_frame(name=tickers_to_fetch[0])
                
                for tkr in tickers_to_fetch:
                    if tkr in close_df.columns:
                        series = close_df[tkr].dropna()
                        if len(series) >= 2:
                            prev_price = float(series.iloc[-2])
                            curr_price = float(series.iloc[-1])
                            if prev_price > 0:
                                live_perfs[tkr] = round(((curr_price - prev_price) / prev_price) * 100, 2)
                        elif len(series) == 1:
                            live_perfs[tkr] = 0.0
        except Exception as e:
            print(f"Erreur lors de la récupération des performances en direct : {e}")

    # Injection de la performance (en %) dans les résultats
    for res in results:
        for h in res["holdings"]:
            tkr = unique_tickers_map.get(h["name"])
            h["live_perf"] = live_perfs.get(tkr, 0.0)

    return jsonify(results)
