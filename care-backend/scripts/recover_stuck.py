import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from database import init_db, update_call, get_call
from processor import recover_stuck_calls

if __name__ == "__main__":
    init_db()
    n = recover_stuck_calls(lambda cid, f: update_call(cid, f), max_age_minutes=1)
    import sqlite3

    conn = sqlite3.connect("care.db")
    rows = conn.execute(
        """
        SELECT id, filename, status, score FROM calls
        WHERE status IN ('scoring','transcribing','processing','queued')
        ORDER BY uploaded_at DESC LIMIT 10
        """
    ).fetchall()
    print("remaining stuck:", rows)
    print("recovered:", n)
