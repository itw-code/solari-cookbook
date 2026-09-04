"""Desktop computer-use — screenshot, click, and type on a real Linux GUI.

A desktop is a sandbox with a screen: same microVM, plus X11 and a VNC stream.
This is the loop a computer-use agent runs — look at the screen, decide, act —
except here the "decide" step is hardcoded so you can see the mechanics.

`streamUrl` can be embedded in any VNC viewer to watch it happen live.
"""

import asyncio
import os
import pathlib

from solari_desktop import DesktopClient

BASE_URL = "https://api.getsolari.com"


async def main() -> None:
    async with DesktopClient(
        api_key=os.environ["SOLARI_API_KEY"],
        base_url=BASE_URL,
    ) as client:
        desktop = await client.create(
            template="default",
            resolution="1280x720",
            # Rolling idle window — resets on each action, auto-pauses after.
            timeout_ms=10 * 60_000,
        )
        print("session:", desktop.sessionId)
        print("watch  :", desktop.streamUrl)

        try:
            await desktop.connect()

            # Wait for X11 to be up before driving the GUI.
            for _ in range(30):
                health = await desktop.health()
                if getattr(health, "ready", False):
                    break
                await asyncio.sleep(1)

            width, height = 1280, 720

            # Open an app by name and give it a moment to map its window. The
            # `default` template ships mousepad, thunar, Chrome, VS Code and
            # LibreOffice — `open()` fails if the binary isn't in the image, so
            # check with `exec("command", args=["-v", name])` if unsure.
            pid = await desktop.open("mousepad")
            print("opened mousepad, pid", pid)
            await asyncio.sleep(4)

            # Click INSIDE the editor's text area before typing. Mousepad opens
            # in the top-left quadrant, so screen-centre (640, 360) is already
            # past its right edge — clicking there focuses whatever is behind
            # it and your keystrokes go to the wrong window, silently. Nothing
            # errors; you just get an empty document. Always confirm with a
            # screenshot rather than trusting that a click landed.
            await desktop.mouse.click(320, 300, humanize=True)
            await desktop.keyboard.type("hello from a Solari desktop")
            await asyncio.sleep(2)

            shot = await desktop.screenshot(format="png")
            out = pathlib.Path("screenshot.png")
            out.write_bytes(shot)
            print(f"screenshot: {out} ({len(shot)} bytes)")
        finally:
            # close() drops only the local channel; destroy() ends the session.
            await desktop.close()
            await client.destroy(desktop.sessionId)


if __name__ == "__main__":
    asyncio.run(main())
