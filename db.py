import os
import sqlite3

DATABASE_FILE = "cutting_selection.db"

def get_connection():
    """
    cutting_selection.db に接続してConnectionを返す
    """
    db_path = os.path.join(os.path.dirname(__file__), DATABASE_FILE)
    conn = sqlite3.connect(db_path)
    return conn
