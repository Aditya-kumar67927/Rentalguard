"""Development entry point: ``python run.py``.

Production uses gunicorn: ``gunicorn "app:create_app('production')"``.
"""
import os

from dotenv import load_dotenv

load_dotenv()

from app import create_app  # noqa: E402

app = create_app(os.environ.get("APP_ENV", "development"))

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")),
            debug=app.config.get("DEBUG", False), use_reloader=False)
