"""Configuration centrale (chemins, hôte/port). Surchargeable par variables d'environnement."""
import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")
DB_PATH = os.environ.get("DB_PATH", os.path.join(ROOT_DIR, "data", "portfolio.db"))

# 127.0.0.1 = accessible uniquement depuis cette machine. Mettre HOST=0.0.0.0 pour ouvrir au réseau local.
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "5000"))

# Commission prélevée par le courtier à chaque REVENTE (0,50 % du montant brut, quel que soit l'ordre).
SELL_COMMISSION_RATE = float(os.environ.get("SELL_COMMISSION_RATE", "0.005"))
