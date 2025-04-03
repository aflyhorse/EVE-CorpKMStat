"""
Initialize the Flask application and its extensions.
"""

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_bootstrap import Bootstrap5
from kmstat.utils import detect_color

# Create Flask app first
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///../instance/database.db"
app.config["SECRET_KEY"] = "dev"  # Change this in production

# Initialize extensions
bootstrap = Bootstrap5(app)

# Initialize SQLAlchemy
db = SQLAlchemy(app)
migrate = Migrate(app, db)


# Register Jinja2 filters
app.jinja_env.filters['detect_color'] = detect_color

# Only expose db and app at module level
__all__ = ["db", "app"]

# Import other modules after all initializations
from kmstat import views, cli  # noqa: F401, E402
