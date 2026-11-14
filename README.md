# Investment Dashboard

Suivi de PEA / livrets : Flask (API + interface) + SQLite + Chart.js.

## Lancer avec Docker (le plus simple)

```bash
cp .env.example .env          # puis éditez .env : choisissez SIGNUP_CODE (code commun d'inscription)
docker compose up -d --build
```
Ouvrir **http://127.0.0.1:5000**, créer le premier compte (il faut saisir le `SIGNUP_CODE` ; ce compte est l'administrateur). Les données (chiffrées) sont dans le volume `invest-data`.

- **HTTPS avec certificat local automatique :** mettre `TRUST_PROXY=1` dans `.env`, puis `docker compose --profile https up -d`. Le site est alors sur `https://invest-dash.home.arpa` (nom modifiable avec `SITE_ADDRESS`).
- **Ouvrir au réseau local sans proxy :** `BIND=0.0.0.0` dans `.env` (HTTP seulement, déconseillé : les mots de passe circuleraient en clair).
- **Mise à jour :** `git pull` ou remplacer les fichiers, puis `docker compose up -d --build` (le volume est conservé).
- **Sauvegarde :** `docker run --rm -v invest-dash_invest-data:/d -v "$PWD":/b alpine tar czf /b/sauvegarde-data.tgz -C /d .`  (le contenu reste chiffré par compte).
- **Reprendre une ancienne base sans comptes** (avant de créer le premier compte) :
  ```bash
  docker compose up -d
  docker cp ancienne-portfolio.db invest-dash:/app/data/portfolio.db
  docker compose exec -u root app chown app:app /app/data/portfolio.db
  docker compose restart app
  ```
- Changer `SIGNUP_CODE` : modifier `.env` puis `docker compose up -d` (les comptes existants ne sont pas touchés).

## Lancer sans Docker

```bash
python3 -m venv .venv && source .venv/bin/activate     # une seule fois
pip install -r requirements.txt                         # une seule fois
python run.py
```

Puis ouvrir **http://127.0.0.1:5000** (l'interface est servie par Flask : l'ouverture de `index.html` en fichier local ne fonctionne plus, à cause des comptes). Au premier lancement, la page de connexion propose de créer le premier compte (administrateur) : s'il existe déjà une ancienne base `data/portfolio.db`, ses données sont reprises et chiffrées.

Docker : `Dockerfile`, `docker-compose.yml`, `.env.example`, `deploy/Caddyfile`.

Confidentialité, chiffrement et droits RGPD : voir **PRIVACY.md**.

Déploiement sur LXC + nginx : voir **DEPLOY.md** (dossier `deploy/` : service systemd et configuration nginx).

## Arborescence

```
run.py                     point d'entrée (aussi : gunicorn run:app)
requirements.txt
data/portfolio.db          base SQLite (ignorée par git)
backend/
  __init__.py              create_app() : enregistre les routes, sert le front, lance le suivi d'écart
  config.py                chemins, HOST / PORT / DB_PATH (variables d'environnement)
  db.py                    connexion SQLite (fermée proprement) + création des tables
  auth.py                  comptes, sessions, anti-force-brute, anti-CSRF, export/suppression RGPD, invitations
  crypto.py                scrypt + AES-256-GCM, clés de données et clé de récupération
  store.py                 lecture/écriture chiffrées des données d'UN utilisateur
  legacy.py                reprise (chiffrée) d'une ancienne base sans comptes
  utils.py                 clean_float
  prices.py                sources de prix : Boursorama, Yahoo, Google (+ petit cache)
  alt.py                   cours crypto (Yahoo, repli CoinGecko) et matières premières (Yahoo, USD→EUR)
  gap.py                   écart estimé à l'ouverture + boucle de suivi + calibrage
  services.py              fetch_ticker_data, cash_state (calcul de la liquidité, un seul endroit)
  routes/
    portfolio.py           portefeuille, réglages, répartition cible, ordres en attente, achat/vente, export CSV
    history.py             historiques (actif, patrimoine)
    alt.py                 crypto et matières premières (positions + cours)
    market.py              actualités, composition des ETF
    simulation.py          Monte-Carlo
    savings.py             comptes sur livret
    gap.py                 /api/gap/rows | report | tuning
frontend/
  index.html  login.html
  style.css
  js/                      chargés dans cet ordre par index.html
    config.js              constantes + état global
    utils.js               esc() (anti-injection HTML), safeUrl(), postJSON()
    portfolio.js           chargement, en-tête, cartes, achat/vente, ordres en attente
    charts.js              graphique patrimoine, allocation, mini-courbes
    modal.js               fenêtre détail d'un actif
    planner.js             plan d'investissement mensuel
    api.js                 requêtes /api : cookie + en-tête anti-CSRF, retour à la connexion si session expirée
    login.js               page de connexion / inscription / mot de passe oublié
    account.js             mon compte, export, suppression, administration
    alt.js                 page Crypto & Matières premières
    navigation.js          changement de vue
    news.js  holdings.js  simulation.js  savings.js
    main.js                démarrage + rafraîchissement automatique
```

## Variables d'environnement (facultatives)

| Variable | Défaut | Rôle |
|---|---|---|
| `HOST` | `127.0.0.1` | `0.0.0.0` pour ouvrir au réseau local (aucune authentification !) |
| `PORT` | `5000` | |
| `DB_PATH` | `data/portfolio.db` | |
| `GAP_SCHEDULER` | `1` | `0` désactive la boucle de suivi de l'écart d'ouverture |
| `SIGNUP_CODE` | (vide) | code commun d'inscription (obligatoire avec Docker). Sans lui, seules les invitations à usage unique ouvrent un compte |
| `SELL_COMMISSION_RATE` | `0.005` | commission de revente (0,50 %) |
| `GAP_TOKEN` | (vide) | si défini, requis (`?token=`) en plus de la connexion pour `/api/gap/*` |
| `TRUST_PROXY` | (vide) | `1` derrière nginx (vraie IP et https) |
| `SESSION_IDLE_MIN` / `SESSION_MAX_HOURS` | `60` / `12` | durée d'inactivité / durée maximale d'une session |
| `COOKIE_SECURE` | `auto` | `1` pour imposer le cookie « Secure » |
