/**
 * design-qa-orchestrator.test.ts — Integration tests for the Design QA orchestrator.
 */
import { describe, it, expect, afterEach } from "vitest"
import { existsSync, readFileSync, rmSync } from "node:fs"
import { join, resolve } from "node:path"
import {
  evaluateRunDesign,
  determineQAStatus,
  MOCK_FALLBACK_CSS_METRICS,
  type DesignQAResult,
} from "../src/design-qa/orchestrator.ts"

describe("Design QA Orchestrator Integration", () => {
  const sampleScreenshotBase64 =
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
  const testRunId = "r_test_mock_run_01"

  afterEach(() => {
    const dir = join(resolve("artifacts/runs"), testRunId)
    if (existsSync(dir)) {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it("calls evaluateRunDesign with mock runId and screenshot, returning a valid DesignQAResult without throwing", async () => {
    const result: DesignQAResult = await evaluateRunDesign(testRunId, sampleScreenshotBase64)

    expect(result).toBeDefined()
    expect(result.runId).toBe(testRunId)
    expect(typeof result.slopScore).toBe("number")
    expect(result.slopScore).toBeGreaterThanOrEqual(0)
    expect(result.slopScore).toBeLessThanOrEqual(100)
    expect(["PASS", "WARN", "BLOCK"]).toContain(result.status)
    expect(Array.isArray(result.flags)).toBe(true)

    // Verify artifact persistence
    const reportPath = join(resolve("artifacts/runs"), testRunId, "design-qa-report.json")
    expect(existsSync(reportPath)).toBe(true)
    const saved = JSON.parse(readFileSync(reportPath, "utf8")) as DesignQAResult
    expect(saved.runId).toBe(testRunId)
    expect(saved.slopScore).toBe(result.slopScore)
    expect(saved.status).toBe(result.status)
  })

  it("uses mock fallback CSS metrics when computedCss is not provided", async () => {
    const result = await evaluateRunDesign("r_fallback_test", sampleScreenshotBase64)

    expect(result.metrics?.contrastRatio).toBe(MOCK_FALLBACK_CSS_METRICS.contrastRatio)
    expect(result.metrics?.spacingVariance).toBe(MOCK_FALLBACK_CSS_METRICS.spacingVariance)
    expect(result.status).toBe("PASS")

    // Cleanup
    const dir = join(resolve("artifacts/runs"), "r_fallback_test")
    if (existsSync(dir)) rmSync(dir, { recursive: true, force: true })
  })

  it("detects low contrast and high spacing variance when computedCss is supplied", async () => {
    const badCss = {
      contrastRatio: 2.1,
      spacingVariance: 16,
    }

    const result = await evaluateRunDesign("r_bad_css_run", sampleScreenshotBase64, badCss)

    // Contrast < 4.5 -> 40 points, spacingVariance > 0 -> 20 points
    // Deterministic = 60 points -> 36 weighted points + VLM score * 0.4
    expect(result.slopScore).toBeGreaterThanOrEqual(36)
    expect(result.flags.some((f) => f.includes("Low contrast ratio"))).toBe(true)
    expect(result.flags.some((f) => f.includes("Off-grid spacing variance"))).toBe(true)
    expect(["WARN", "BLOCK"]).toContain(result.status)

    // Cleanup
    const dir = join(resolve("artifacts/runs"), "r_bad_css_run")
    if (existsSync(dir)) rmSync(dir, { recursive: true, force: true })
  })

  it("correctly maps score ranges to PASS, WARN, and BLOCK statuses", () => {
    expect(determineQAStatus(15)).toBe("PASS")
    expect(determineQAStatus(29)).toBe("PASS")
    expect(determineQAStatus(30)).toBe("WARN")
    expect(determineQAStatus(45)).toBe("WARN")
    expect(determineQAStatus(59)).toBe("WARN")
    expect(determineQAStatus(60)).toBe("BLOCK")
    expect(determineQAStatus(85)).toBe("BLOCK")
  })

  it("integrates with buildScorecard by populating designSlopScore and designStatus from persisted reports", async () => {
    const { buildScorecard } = await import("../src/scorecard/build.ts")
    const scorecardRunId = "r_scorecard_test_run"

    await evaluateRunDesign(scorecardRunId, sampleScreenshotBase64, {
      contrastRatio: 7.0,
      spacingVariance: 0,
    })

    const mockRun: any = {
      run_id: scorecardRunId,
      variant_id: "inv__s0__P1:0__P2:0__P3:0__P4:0__P5:0",
      seed: 0,
      intensity_by_axis: { P1_relabel: 0, P2_structure: 0, P3_field_order: 0, P4_nav_order: 0, P5_theme: 0 },
      agent: { model: "test-model", steps_taken: 5, max_steps: 20, terminated_by: "done", status: "ok" },
      outcome: {
        status: "ok",
        task_completed: true,
        action_trace_path: join(resolve("artifacts/runs"), scorecardRunId, "trace.json"),
        verifier: { task_completed: true, field_errors: [], checks_run: [], evidence_hash: "abcd" },
      },
      session: { replay_url: null, recording_id: null, sandbox_id: null, snapshot_id: null, fixture_path: null },
      cost: { credits: null, hours: 0.01, sandbox_seconds: 10, browser_seconds: 10, model_tokens_in: 100, model_tokens_out: 10, model_request_count: 5, llm_calls: 5 },
    }

    const scorecard = buildScorecard({
      runs: [mockRun],
      config: { max_steps: 20, viewport: "1280x800", n_runs_per_point: 1, mode: "MOCK" },
    })

    expect(typeof scorecard.designSlopScore).toBe("number")
    expect(scorecard.designSlopScore).toBeGreaterThanOrEqual(0)
    expect(["PASS", "WARN", "BLOCK"]).toContain(scorecard.designStatus)
    expect(scorecard.designStatus).toBe("PASS")

    // Cleanup
    const dir = join(resolve("artifacts/runs"), scorecardRunId)
    if (existsSync(dir)) rmSync(dir, { recursive: true, force: true })
  })

  it("buildScorecard nulls the design fields when no design-qa reports exist for the runs", async () => {
    const { buildScorecard } = await import("../src/scorecard/build.ts")

    const mockRun: any = {
      run_id: "r_no_design_qa_report",
      variant_id: "inv__s0__P1:0__P2:0__P3:0__P4:0__P5:0",
      seed: 0,
      intensity_by_axis: { P1_relabel: 0, P2_structure: 0, P3_field_order: 0, P4_nav_order: 0, P5_theme: 0 },
      agent: { model: "test-model", steps_taken: 5, max_steps: 20, terminated_by: "done", status: "ok" },
      outcome: {
        status: "ok",
        task_completed: true,
        action_trace_path: "trace.json",
        verifier: { task_completed: true, field_errors: [], checks_run: [], evidence_hash: "abcd" },
      },
      session: { replay_url: null, recording_id: null, sandbox_id: null, snapshot_id: null, fixture_path: null },
      cost: { credits: null, hours: 0.01, sandbox_seconds: 10, browser_seconds: 10, model_tokens_in: 100, model_tokens_out: 10, model_request_count: 5, llm_calls: 5 },
    }

    const scorecard = buildScorecard({
      runs: [mockRun],
      config: { max_steps: 20, viewport: "1280x800", n_runs_per_point: 1, mode: "MOCK" },
    })

    // No design-qa-report.json exists for this run -> honest nulls, never fabricated scores.
    expect(scorecard.designSlopScore).toBeNull()
    expect(scorecard.designStatus).toBeNull()
    expect(scorecard.designQaDisclosure).toBeNull()
  })
})
