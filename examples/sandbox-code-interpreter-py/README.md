# Code interpreter (Python)

A stateful Python kernel inside a sandbox: variables and imports persist between `run_code` calls, like a notebook. This is the shape of an LLM agent's execution loop.

Output arrives as a list of result items (`stdout`/`stderr`/`result`), not a single `.stdout` string.

## Run

```bash
cd examples/sandbox-code-interpreter-py
pip install -r requirements.txt
export SOLARI_API_KEY=slr_live_...   # https://console.getsolari.com
python main.py
```

Source: [`main.py`](main.py)
