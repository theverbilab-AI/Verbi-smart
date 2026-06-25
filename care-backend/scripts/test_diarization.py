"""
Manual diarization check.

Runs the new Sarvam batch diarization on a real recording and prints the
speaker turns so we can compare raw STT vs. diarized vs. displayed labels.

Usage:
    python scripts/test_diarization.py "C:\\path\\to\\recording.wav"
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from diarization import diarize_audio  # noqa: E402
from speaker_attribution import summarize_attribution  # noqa: E402

DEFAULT = r"C:\Users\SIDDHANTH REMMA\Downloads\1899703-RITIKA.wav.wav"


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    print(f"=== Diarizing: {path} ===\n", flush=True)
    turns = diarize_audio(path)
    if not turns:
        print("\nRESULT: diarize_audio returned None (would fall back to legacy pipeline).")
        return

    agent = sum(1 for t in turns if t["speaker"] == "Agent")
    cust = sum(1 for t in turns if t["speaker"] == "Customer")
    print(f"\n=== {len(turns)} turns | Agent={agent} Customer={cust} ===\n")
    for i, t in enumerate(turns):
        print(f"[{i:02d}] {t['speaker']:8s} (conf {t['confidence']}) :: {t['text'][:110]}")

    summary = summarize_attribution(turns)
    print("\n=== Attribution summary ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
