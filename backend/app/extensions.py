from flask import Flask
from flask_bcrypt import Bcrypt
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from pymongo import MongoClient
from pymongo.database import Database

jwt = JWTManager()
bcrypt = Bcrypt()
cors = CORS()


class _Mongo:
    """Thin wrapper holding the active MongoClient and default Database."""

    client: MongoClient | None = None
    db: Database | None = None

    def init_app(self, app: Flask) -> None:
        self.client = MongoClient(app.config["MONGO_URI"])
        self.db = self.client.get_default_database()


mongo = _Mongo()
