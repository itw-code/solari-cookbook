/**
 * Sandbox quickstart — run untrusted code in a fresh microVM.
 *
 * A sandbox is a full Linux VM that boots from a memory snapshot, so it's
 * usually ready in about a second. Nothing you run inside can touch your
 * machine or another customer's.
 */
import { SolariClient } from "@solarisdk/sdk"

// SolariClient defaults baseUrl to https://api.getsolari.com. (The standalone
// SandboxClient/DesktopClient packages require baseUrl explicitly.)
const pt = new SolariClient({ apiKey: process.env.SOLARI_API_KEY! })

const sandbox = await pt.sandboxes.create({
  template: "base",
  // Rolling IDLE window — it resets on every use, it is not a hard deadline.
  timeoutMs: 5 * 60_000,
})
console.log("sandbox:", sandbox.sandboxId)

try {
  // Opens the control channel. Needed for files/git/code; commands alone can
  // take a one-shot HTTP path without it.
  await sandbox.connect()

  // `cmd` is NOT shell-interpreted — argv goes in `args`. For pipes, globs or
  // redirection, run a shell explicitly: run("sh", { args: ["-c", "..."] }).
  const out = await sandbox.commands.run("python3", {
    args: ["-c", "print(sum(range(101)))"],
  })
  console.log("exit:", out.exitCode, "stdout:", out.stdout.trim())

  await sandbox.files.write("/tmp/hello.txt", "written from the SDK\n")
  console.log("file  :", (await sandbox.files.readText("/tmp/hello.txt")).trim())
  console.log("ls    :", (await sandbox.files.list("/tmp")).map((e) => e.name).join(" "))
} finally {
  // kill() destroys the remote VM. close() alone would only drop your local
  // control channel and leave it running until the idle timeout.
  await sandbox.kill()
}
