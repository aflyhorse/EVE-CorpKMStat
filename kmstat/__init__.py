"""
Initialize the Flask application and its extensions.
"""
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_bootstrap import Bootstrap5

# Create Flask app first
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///../instance/database.db"
app.config["SECRET_KEY"] = "dev"  # Change this in production

# Initialize extensions
bootstrap = Bootstrap5(app)

# Initialize SQLAlchemy
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Only expose db and app at module level
__all__ = ['db', 'app']

# Import views after all initializations
from kmstat import views  # noqa: F401, E402

# Import CLI commands after all initializations
import kmstat.cli  # noqa: F401, E402
