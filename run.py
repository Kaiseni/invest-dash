from backend import create_app
from backend.config import HOST, PORT

app = create_app()  # `gunicorn run:app` fonctionne aussi

if __name__ == "__main__":
    app.run(host=HOST, port=PORT)
