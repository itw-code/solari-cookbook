# Desktop computer-use (Python)

Screenshot, click, and type on a real Linux GUI — the loop a computer-use agent runs, with the 'decide' step hardcoded. `streamUrl` can be embedded in any VNC viewer to watch it live.

If `create` hangs or returns a capacity error, the desktop pool has no warm hosts; sandboxes and browsers are unaffected.

## Run

```bash
cd examples/desktop-computer-use-py
pip install -r requirements.txt
export SOLARI_API_KEY=slr_live_...   # https://console.getsolari.com
python main.py
```

Source: [`main.py`](main.py)
