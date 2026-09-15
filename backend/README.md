# Tracking Console API

Run from the project root after installing `requirements.txt`:

```powershell
python -m uvicorn backend.app:app --reload --port 8000
```

The API deliberately starts each inference job as an isolated `infer.py` process. This keeps the existing CLI and its GPU/SQLite lifecycle intact while preventing `PersonMemory`, runtime databases, and output files from being shared between jobs.
