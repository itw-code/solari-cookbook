/**
 * Stealth mode + managed proxy — reach a site that blocks datacenter traffic.
 *
 * Two independent knobs:
 *   stealth: true   runtime fingerprint patches + a headful browser on real GPU
 *   proxy:   "us"   residential egress in that country
 *
 * `proxy` and `captcha` both REQUIRE `stealth: true` — a proxied request from an
 * obviously-automated browser is the pairing that gets blocked. Shorthands:
 *
 *   proxy: "us"                        residential, United States
 *   proxy: { country: "gb" }           residential, United Kingdom
 *   proxy: { country: "us", tier: "mobile" }
 *   proxy: { country: "us", session: "warm-1" }   sticky IP across sessions
 *   proxy: "smart"                     let Solari pick and rotate on block
 */
import { Solari } from "@solarisdk/browser"

const solari = new Solari({ apiKey: process.env.SOLARI_API_KEY! })

const browser = await solari.launch({
  stealth: true,
  proxy: "us",
  // captcha: true,   // managed reCAPTCHA / hCaptcha / Turnstile solving
})
try {
  const page = await browser.newPage()

  // Echoes the egress IP the target site actually sees — i.e. the proxy's,
  // not your machine's and not the pool host's.
  await page.goto("https://api.ipify.org?format=json")
  console.log("egress :", await page.locator("pre").innerText())

  // `browser.proxy` reports what the gateway resolved (country/tier/timezone),
  // never the upstream vendor credentials.
  console.log("proxy  :", JSON.stringify(browser.proxy))
} finally {
  await browser.close()
  // Required, or the process never exits — see browser-quickstart-ts.
  await solari.close()
}
