# Browser quickstart (TypeScript)

Launch a cloud browser, open a page, read the title, close. The smallest complete Solari program.

Note the `solari.close()` in the `finally` block — the client keeps a loopback proxy open for connection retries, and without closing it your script will print its output and then hang instead of exiting.

## Run

```bash
cd examples/browser-quickstart-ts
npm install
export SOLARI_API_KEY=slr_live_...   # https://console.getsolari.com
npm start
```

Source: [`index.ts`](index.ts)
