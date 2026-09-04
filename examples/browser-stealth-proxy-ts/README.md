# Stealth + managed proxy (TypeScript)

Reach a site that blocks datacenter traffic: `stealth: true` for the fingerprint patches, `proxy: "us"` for residential egress. Prints the IP the target actually sees.

`proxy` and `captcha` both require `stealth: true`.

## Run

```bash
cd examples/browser-stealth-proxy-ts
npm install
export SOLARI_API_KEY=slr_live_...   # https://console.getsolari.com
npm start
```

Source: [`index.ts`](index.ts)
