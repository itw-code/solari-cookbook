"""Call one browser tool of scripts/appeal_tool_server.py and print its result.

For an agent that has a shell but no function calling of its own (a Claude Code subagent):
  python scripts/appeal_tool.py EPISODE TOOL '{"json": "args"}'
TOOL is one of read_page, click, type, key, evaluate; `python scripts/appeal_tool.py --tools`
prints their schemas.
"""

import json
import sys
import urllib.request

URL = "http://127.0.0.1:8765"


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(URL + path, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=200) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    if sys.argv[1:] == ["--tools"]:
        with urllib.request.urlopen(URL + "/tools", timeout=30) as resp:
            print(json.dumps(json.loads(resp.read()), indent=1))
        return 0
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    ep, name = sys.argv[1], sys.argv[2]
    args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
    out = post("/tool", {"ep": ep, "name": name, "args": args})
    sys.stdout.reconfigure(encoding="utf-8")
    print(out.get("result", out.get("error")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
