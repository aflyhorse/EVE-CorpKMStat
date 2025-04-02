"""
Initialize the Flask application and its extensions.
"""
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

# Create Flask app first
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///../instance/database.db"

# Initialize SQLAlchemy
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Only expose db and app at module level
__all__ = ['db', 'app']

# Import CLI commands after all initializations
import kmstat.cli  # noqa: F401, E402
