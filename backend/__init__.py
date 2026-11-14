import os

from flask import Flask, send_from_directory

from .config import FRONTEND_DIR
from .db import init_db


def create_app():
    # L'interface est servie par Flask lui-même : ouvrir http://IP:5000 ou le nom derrière nginx (même origine, cookies sécurisés).
    app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024  # 1 Mo : largement suffisant, évite les envois abusifs

    if os.environ.get("TRUST_PROXY") == "1":  # derrière nginx : vraie adresse IP et https vus par l'application
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    init_db()

    from . import auth
    from .routes import portfolio, history, market, simulation, savings, alt, gap as gap_routes
    auth.init_app(app)
    for module in (auth, portfolio, history, market, simulation, savings, alt, gap_routes):
        app.register_blueprint(module.bp)

    @app.route("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    # Boucle de suivi de l'écart à l'ouverture (GAP_SCHEDULER=0 pour la désactiver) : données de marché, aucune donnée personnelle
    if os.environ.get("GAP_SCHEDULER", "1") != "0" and not app.config.get("TESTING"):
        from .gap import _start_scheduler
        _start_scheduler()

    return app
