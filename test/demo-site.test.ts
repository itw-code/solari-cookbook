/**
 * demo-site.test.ts — Unit and integration tests for the unified demo target site.
 */

import { describe, it, expect, beforeAll, afterAll } from "vitest"
import { startDemoServer, openDemoDb, type DemoServerInstance } from "../src/demo-site/server.js"
import { verifyDemoSignup } from "../src/demo-site/verifier.js"

describe("Demo Site Server & Verifier", () => {
  let demo: DemoServerInstance

  beforeAll(async () => {
    demo = await startDemoServer({ port: 0 })
  })

  afterAll(async () => {
    if (demo) {
      await demo.close()
    }
  })

  describe("Signup POST and fail-closed Verifier", () => {
    it("POSTs a signup and verifies task_completed=true for correct email, false for wrong email", async () => {
      const name = "Ada Lovelace"
      const correctEmail = "ada@computing.org"
      const wrongEmail = "charles@babbage.org"

      const res = await fetch(`${demo.baseUrl}/signup`, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: new URLSearchParams({ name, email: correctEmail }).toString(),
      })

      expect(res.status).toBe(200)
      const html = await res.text()
      expect(html).toContain("Access Requested")
      expect(html).toContain(correctEmail)

      // Verifier check with correct email
      const verifiedCorrect = verifyDemoSignup({
        expectedEmail: correctEmail,
        db: demo.db,
      })

      expect(verifiedCorrect.task_completed).toBe(true)
      expect(verifiedCorrect.checks.D1.passed).toBe(true)
      expect(verifiedCorrect.checks.D2.passed).toBe(true)
      expect(verifiedCorrect.checks.D3.passed).toBe(true)
      expect(verifiedCorrect.row?.name).toBe(name)
      expect(verifiedCorrect.row?.email).toBe(correctEmail)

      // Verifier check with wrong email
      const verifiedWrong = verifyDemoSignup({
        expectedEmail: wrongEmail,
        db: demo.db,
      })

      expect(verifiedWrong.task_completed).toBe(false)
      expect(verifiedWrong.checks.D1.passed).toBe(true)
      expect(verifiedWrong.checks.D2.passed).toBe(false)
      expect(verifiedWrong.checks.D2.detail).toContain(wrongEmail)
    })

    it("fails closed when the database is empty or has no matching records", () => {
      const emptyDb = openDemoDb(":memory:")
      try {
        const result = verifyDemoSignup({
          expectedEmail: "nobody@example.com",
          db: emptyDb,
        })
        expect(result.task_completed).toBe(false)
        expect(result.checks.D1.passed).toBe(false)
        expect(result.checks.D2.passed).toBe(false)
        expect(result.checks.D3.passed).toBe(false)
      } finally {
        emptyDb.close()
      }
    })

    it("rejects signup with missing required fields", async () => {
      const res = await fetch(`${demo.baseUrl}/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ name: "Incomplete" }).toString(),
      })
      expect(res.status).toBe(400)
    })
  })

  describe("Landing page design variants (clean vs ?slop=1)", () => {
    it("serves clean human-grade design on GET /", async () => {
      const res = await fetch(`${demo.baseUrl}/`)
      expect(res.status).toBe(200)
      const html = await res.text()

      // Clean markers
      expect(html).toContain('data-variant="clean"')
      expect(html).toContain("Request Early Access")
      expect(html).toContain("-apple-system")
      expect(html).toContain("--radius: 8px")
      expect(html).toContain("#0284c7")

      // Should not contain slop markers
      expect(html).not.toContain('data-variant="slop"')
      expect(html).not.toContain("purple-hero")
      expect(html).not.toContain("btn-slop-submit")
    })

    it("serves intentional AI slop design on GET /?slop=1", async () => {
      const res = await fetch(`${demo.baseUrl}/?slop=1`)
      expect(res.status).toBe(200)
      const html = await res.text()

      // Slop markers
      expect(html).toContain('data-variant="slop"')
      expect(html).toContain("purple-hero")
      expect(html).toContain("linear-gradient(135deg, #667eea 0%, #764ba2 100%)")
      expect(html).toContain("'Inter', Arial, sans-serif")
      expect(html).toContain("btn-slop-submit")
      expect(html).toContain("#888888") // low contrast gray button background
      expect(html).toContain("#777777") // low contrast gray text

      // Should not contain clean markers
      expect(html).not.toContain('data-variant="clean"')
      expect(html).not.toContain("clean-card")
    })
  })

  describe("Deterministic Design Metrics endpoint (/design-metrics.json)", () => {
    it("returns clean metrics on GET /design-metrics.json", async () => {
      const res = await fetch(`${demo.baseUrl}/design-metrics.json`)
      expect(res.status).toBe(200)
      const json = await res.json()

      expect(json).toEqual({
        contrastRatio: 7.2,
        spacingVariance: 0,
      })
    })

    it("returns slop metrics on GET /design-metrics.json?slop=1", async () => {
      const res = await fetch(`${demo.baseUrl}/design-metrics.json?slop=1`)
      expect(res.status).toBe(200)
      const json = await res.json()

      expect(json).toEqual({
        contrastRatio: 2.1,
        spacingVariance: 15,
      })
    })
  })
})
