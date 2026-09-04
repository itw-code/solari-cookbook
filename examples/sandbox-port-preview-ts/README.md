# Port preview (TypeScript)

Serve something from inside the sandbox on a public URL. Starts an HTTP server in the VM, gets a `*.preview.getsolari.com` URL, then fetches it from the open internet to prove it is reachable.

## Run

```bash
cd examples/sandbox-port-preview-ts
npm install
export SOLARI_API_KEY=slr_live_...   # https://console.getsolari.com
npm start
```

Source: [`index.ts`](index.ts)
