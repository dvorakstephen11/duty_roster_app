import os
import sqlite3
from flask import g, current_app

DATABASE = 'duty_roster.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

def query_db(query, args=(), one=False):
    """Helper for parameterized SQL queries, avoiding manual DB repetition."""
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def init_db():
    with current_app.app_context():
        db = get_db()
        with current_app.open_resource('schema.sql', mode='r') as f:
            db.executescript(f.read())
        db.commit()

def close_db(e=None):
    """Close the database connection."""
    db = g.pop('_database', None)
    if db is not None:
        db.close()

def init_app(app):
    """Register database functions with the Flask app."""
    app.teardown_appcontext(close_db) 