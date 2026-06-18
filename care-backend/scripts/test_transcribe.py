"""Quick STT smoke test — run from care-backend: python scripts/test_transcribe.py [wav_path]"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from processor import transcribe  # noqa: E402

def main():
    wav = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\SIDDHANTH REMMA\Downloads\addadef1-cb9b-4e54-90c4-94a3b81135f6.wav"
    if not os.path.exists(wav):
        import sqlite3

        conn = sqlite3.connect("care.db")
        row = conn.execute(
            "SELECT file_path FROM calls WHERE call_id='CALL-5F44CBD4'"
        ).fetchone()
        if row and row[0] and os.path.exists(row[0]):
            wav = row[0]
    print("Using:", wav)
    if not wav or not os.path.exists(wav):
        print("Audio file not found")
        sys.exit(1)
    agent, labelled = transcribe(wav)
    print("AGENT_LEN", len(agent or ""))
    print("LABELLED_LEN", len(labelled or ""))
    print("FIRST_400:", (labelled or "")[:400])
    print("LAST_400:", (labelled or "")[-400:])

if __name__ == "__main__":
    main()
