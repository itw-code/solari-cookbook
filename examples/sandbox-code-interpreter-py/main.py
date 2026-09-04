"""Code interpreter — a stateful Python kernel inside a sandbox.

`run_code` executes in a persistent kernel, so variables and imports survive
between calls. That's what makes it useful for an LLM agent loop: the model
writes a line, sees the output, and builds on it — exactly like a notebook.
"""

import asyncio
import os

from solari_sandbox import SandboxClient

BASE_URL = "https://api.getsolari.com"


async def main() -> None:
    # The standalone SandboxClient requires base_url (only the umbrella
    # SolariClient in @solarisdk/sdk defaults it).
    async with SandboxClient(
        api_key=os.environ["SOLARI_API_KEY"],
        base_url=BASE_URL,
    ) as client:
        sandbox = await client.create(template="base", timeout_ms=5 * 60_000)
        print("sandbox:", sandbox.sandboxId)

        try:
            await sandbox.connect()

            # A context is the kernel. Reuse the id to keep state across calls;
            # omit it and each call starts fresh.
            ctx = await sandbox.create_code_context("python")

            await sandbox.run_code("import math\nradius = 7", context_id=ctx)

            # `radius` and `math` are still defined here — different call,
            # same kernel.
            result = await sandbox.run_code(
                "area = math.pi * radius ** 2\nprint(f'area = {area:.2f}')\narea",
                context_id=ctx,
            )

            if result.error:
                print("error:", result.error)
                return

            # There is no top-level `.stdout`. Output arrives as a list of
            # items: type "stdout"/"stderr" for streams, "result" for the
            # value of the final expression (plus png/svg/html for rich media).
            for item in result.results:
                label = getattr(item, "type", "result")
                text = getattr(item, "text", None)
                if text:
                    print(f"  [{label}] {text.strip()}")
        finally:
            # Destroys the VM. Without this it lingers until the idle timeout.
            await sandbox.kill()


if __name__ == "__main__":
    asyncio.run(main())
