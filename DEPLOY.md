> **Docker :** pour un déploiement plus simple, voir la section « Lancer avec Docker » du `README.md` (dans un LXC, Docker demande l'option *nesting*). Ce document décrit l'installation directe sur un conteneur LXC.

# Déploiement sur un conteneur LXC (Debian 12 / Ubuntu 22.04+)

Utilisez un conteneur **Debian ou Ubuntu** (pas Alpine : `curl_cffi` n'a pas de paquet précompilé pour musl).
Ressources suffisantes : 1 cœur, 512 Mo à 1 Go de RAM. Le conteneur doit avoir accès à Internet (Boursorama, Yahoo, Google News, JustETF).

## 0. Transférer le zip dans le conteneur

Par défaut, SSH refuse la connexion en `root` : on passe par un utilisateur normal (ici `dashuser`).

**Dans le conteneur** (console Proxmox, ou `pct enter <ID>` depuis l'hôte), une seule fois :
```bash
apt update && apt install -y openssh-server sudo unzip
adduser dashuser                      # s'il n'existe pas déjà
usermod -aG sudo dashuser             # pour pouvoir installer et copier dans /opt
systemctl enable --now ssh
ip -4 addr                            # relever l'adresse IP du conteneur
```

**Depuis votre PC** (dans le dossier qui contient le zip) :
```bash
scp invest-dash.zip dashuser@IP_DU_CONTENEUR:~/
```
On envoie dans le dossier personnel (`~`), car `dashuser` n'a pas le droit d'écrire directement dans `/opt`. Si scp répond `subsystem request failed`, ajoutez `-O` : `scp -O invest-dash.zip ...`.

**Dans le conteneur**, connecté en `dashuser` :
```bash
sudo unzip ~/invest-dash.zip -d /opt          # crée /opt/invest-dash
```
Puis continuez avec les étapes ci-dessous (en préfixant les commandes d'administration par `sudo`). Sans SSH, deux alternatives : `pct push` depuis l'hôte Proxmox, ou `python3 -m http.server` sur votre PC puis `wget` dans le conteneur.

---

## 1. Installation

(Le zip a déjà été décompressé dans `/opt/invest-dash` à l'étape 0.)

```bash
sudo apt update && sudo apt install -y python3 python3-venv sqlite3
sudo adduser --system --group --home /opt/invest-dash invest     # compte de service, sans connexion
cd /opt/invest-dash
sudo python3 -m venv .venv && sudo .venv/bin/pip install -r requirements.txt
sudo chown -R invest:invest /opt/invest-dash
sudo cp deploy/invest-dash.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now invest-dash
systemctl status invest-dash                        # journalctl -u invest-dash -f pour les logs
curl http://127.0.0.1:5000/api/budget               # doit répondre {"budget": ...}
```

## nginx
- Même conteneur : installer nginx, copier `deploy/nginx.conf` dans `/etc/nginx/sites-available/`, l'activer (lien dans `sites-enabled/`), `nginx -t && systemctl reload nginx`.
- Conteneur séparé : dans `invest-dash.service`, remplacer `127.0.0.1:5000` par `0.0.0.0:5000`, puis limiter le port 5000 à l'IP du conteneur nginx (pare-feu Proxmox), et mettre cette IP dans `proxy_pass`.
- L'application doit être servie à la **racine** d'un nom de domaine (pas sous `/bourse/`).
- HTTPS recommandé si l'accès sort du réseau local (certbot, Nginx Proxy Manager…).

## Sauvegarde
La base est `data/portfolio.db` (mode WAL : ne pas copier le fichier seul pendant que l'appli tourne). Sauvegarde à chaud :

```bash
sqlite3 /opt/invest-dash/data/portfolio.db ".backup '/root/portfolio-$(date +%F).db'"
```
Une sauvegarde Proxmox du conteneur (vzdump) couvre aussi le dossier `data/`.

## Mise à jour

Remplacer les fichiers **sauf le dossier `data/`** (il contient votre base), puis `sudo .venv/bin/pip install -r requirements.txt` et `sudo systemctl restart invest-dash`.

### Passage de la version sans comptes à la version avec comptes (une seule fois)
1. **Sauvegarde** de l'ancienne base (elle est en clair) : `sudo sqlite3 /opt/invest-dash/data/portfolio.db ".backup '/root/portfolio-avant-comptes.db'"`
2. Mettre à jour les fichiers (sans toucher à `data/`), installer les dépendances (`cryptography` est nouvelle), redémarrer.
3. Ouvrir le site : la page de connexion s'affiche. Onglet **Créer un compte** : ce **premier compte devient l'administrateur** et reprend automatiquement vos données existantes, qui sont alors **chiffrées**. Les anciennes tables en clair sont supprimées et le fichier est réécrit.
4. **Notez la clé de récupération** affichée à ce moment-là (elle ne sera plus jamais montrée).
5. Vérifiez vos chiffres, puis **supprimez la sauvegarde en clair** (`/root/portfolio-avant-comptes.db`) ou rangez-la dans un endroit chiffré : elle contient toujours vos données lisibles.

## HTTPS (indispensable : les mots de passe passent par le réseau)
Certificat auto-signé pour un usage local (le navigateur affichera un avertissement la première fois ; importez le certificat dans le navigateur pour l'éviter) :
```bash
sudo mkdir -p /etc/nginx/ssl
sudo openssl req -x509 -nodes -newkey rsa:2048 -days 825 -keyout /etc/nginx/ssl/invest-dash.key -out /etc/nginx/ssl/invest-dash.crt \
  -subj "/CN=invest-dash.home.arpa" -addext "subjectAltName=DNS:invest-dash.home.arpa"
sudo chmod 600 /etc/nginx/ssl/invest-dash.key
```
Pensez à autoriser le port **443** dans le pare-feu Proxmox du conteneur (en plus du 80 pour la redirection).

## Ajouter des utilisateurs
Deux façons, combinables : un **code commun** (variable `SIGNUP_CODE`, à ajouter dans le fichier `.service` avec une ligne `Environment=SIGNUP_CODE=...`) que vous donnez aux personnes autorisées, ou des **invitations à usage unique**.

Connecté en administrateur : **Mon compte → Administration → Créer un code d'invitation**. Transmettez le code (valable 7 jours, usage unique) : la personne crée son compte sur la page de connexion et choisit elle-même son mot de passe. Vous ne pouvez jamais lire ses données.

## Sessions et redémarrage
Les clés de chiffrement des utilisateurs connectés ne vivent qu'en mémoire : un redémarrage du service déconnecte tout le monde (il suffit de se reconnecter). Durée d'inactivité : 60 min (`SESSION_IDLE_MIN`), durée maximale : 12 h (`SESSION_MAX_HOURS`).
