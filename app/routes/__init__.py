from flask import Flask


def register_blueprints(app: Flask) -> None:
    from app.routes.analysis import bp as analysis_bp
    from app.routes.auth import bp as auth_bp
    from app.routes.dashboard import bp as dashboard_bp
    from app.routes.listings import bp as listings_bp
    from app.routes.pages import bp as pages_bp

    for bp in (pages_bp, auth_bp, listings_bp, analysis_bp, dashboard_bp):
        app.register_blueprint(bp)
