# Session recording + replay (Python)

Capture a session as an rrweb replay and download it.

Recording is opt-in per session (`recording=True` at create time) — there is no account-level switch, and a session created without it will 404 forever. The upload happens asynchronously after release, so poll for a few seconds before concluding there is no replay.

## Run

```bash
cd examples/browser-session-recording-py
pip install -r requirements.txt
export SOLARI_API_KEY=slr_live_...   # https://console.getsolari.com
python main.py
```

Source: [`main.py`](main.py)
