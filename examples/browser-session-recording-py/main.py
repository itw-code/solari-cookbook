"""Session recording — capture a run and download the replay.

Recording is OPT-IN PER SESSION (`recording=True` at create time). There is no
account-level switch: a session created without the flag records nothing, and
its replay endpoint will 404 forever.

The replay is rrweb NDJSON (gzipped) — a DOM-level recording, not a video, so
it stays small and you can diff or grep it.
"""

import asyncio
import os

from solari_browser import Solari
from solari_browser.errors import SolariError


async def main() -> None:
    solari = Solari(api_key=os.environ["SOLARI_API_KEY"])

    browser = await solari.launch(recording=True)
    session_id = browser.id
    try:
        page = await browser.new_page()
        await page.goto("https://example.com")
        await page.locator("h1").inner_text()
        # Give rrweb a moment to flush the events it batched.
        await asyncio.sleep(2)
    finally:
        await browser.close()

    # The upload happens asynchronously AFTER the session is released, so the
    # first poll usually 404s even on a perfectly good recording. Retry before
    # concluding there is no replay.
    for attempt in range(1, 11):
        await asyncio.sleep(3)
        try:
            blob = await solari.sessions.download_replay(session_id)
        except SolariError as err:
            if err.status == 404:
                print(f"  attempt {attempt}: not uploaded yet")
                continue
            raise
        # The object is stored gzipped, but the HTTP client honours
        # Content-Encoding and hands back decompressed bytes — so this is
        # already plain NDJSON. Don't gzip.decompress() it.
        events = blob.decode().splitlines()
        print(f"replay: {len(blob)} bytes, {len(events)} rrweb events")
        print("first event:", events[0][:90], "...")
        return

    print("no replay after ~30s — was the session created with recording=True?")


if __name__ == "__main__":
    asyncio.run(main())
