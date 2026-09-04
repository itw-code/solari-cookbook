# Persistent profiles (TypeScript)

Log in once, reuse the session forever. A profile stores cookies + localStorage server-side; attach it with `profileId` and the browser starts already logged in.

Run it twice — the visit counter survives because the profile is saved between runs. Attaching a profile does not auto-save it; you must call `profiles.save()`.

## Run

```bash
cd examples/browser-profiles-ts
npm install
export SOLARI_API_KEY=slr_live_...   # https://console.getsolari.com
npm start
```

Source: [`index.ts`](index.ts)
