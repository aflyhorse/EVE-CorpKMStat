"""
Initialize the Flask application and its extensions.
"""

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_bootstrap import Bootstrap5
from flask_login import LoginManager
from kmstat.utils import detect_color, get_last_day_of_month


# Create Flask app first
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///../instance/database.db"
app.config["SECRET_KEY"] = "dev"  # Change this in production

# Initialize extensions
bootstrap = Bootstrap5(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "请先登录以访问此页面。"

# Initialize SQLAlchemy
db = SQLAlchemy(app)
migrate = Migrate(app, db)


@login_manager.user_loader
def load_user(user_id):
    from kmstat.models import User

    return User.query.get(int(user_id))


# Register Jinja2 filters
def register_filters(app):
    app.jinja_env.filters["detect_color"] = detect_color
    app.jinja_env.globals["get_last_day_of_month"] = get_last_day_of_month


register_filters(app)

# Only expose db and app at module level
__all__ = ["db", "app"]

# Import other modules after all initializations
from kmstat import views, cli, auth  # noqa: F401, E402
