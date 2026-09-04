"""Browser quickstart — launch a cloud browser, open a page, read it, close.

`launch()` creates a session and connects a Playwright-compatible browser to it
in one call. Everything after that is ordinary Playwright: the browser just
happens to be running on Solari's infrastructure rather than your laptop.
"""

import asyncio
import os

from solari_browser import Solari


async def main() -> None:
    solari = Solari(api_key=os.environ["SOLARI_API_KEY"])

    # `browser.close()` also RELEASES the session. Closing the browser alone
    # would leave the slot held until the plan deadline, so use try/finally.
    browser = await solari.launch()
    try:
        page = await browser.new_page()
        await page.goto("https://example.com")

        print("title  :", await page.title())
        print("h1     :", await page.locator("h1").inner_text())
        print("session:", browser.id)
    finally:
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
