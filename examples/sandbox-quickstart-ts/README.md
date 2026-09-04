# Sandbox quickstart (TypeScript)

Run untrusted code in a fresh microVM: execute a command, write a file, read it back.

Commands are not shell-interpreted — argv goes in `args`. For pipes or redirection run a shell explicitly: `run("sh", { args: ["-c", "..."] })`.

## Run

```bash
cd examples/sandbox-quickstart-ts
npm install
export SOLARI_API_KEY=slr_live_...   # https://console.getsolari.com
npm start
```

Source: [`index.ts`](index.ts)
