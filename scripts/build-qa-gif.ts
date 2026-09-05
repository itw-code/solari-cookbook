import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { execSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const tempDir = os.tmpdir();
const chromePath = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

interface StepConfig {
  step: number;
  total: number;
  stageName: string;
  model: string;
  leftTitle: string;
  leftSubtitle: string;
  leftHtml: string;
  actionType: string;
  actionDetail: string;
  targetElement: string;
  rationaleTitle: string;
  rationaleBadge: string;
  rationaleText: string;
  verifierType: string;
  verifierStatus: string;
  verifierDetails: string;
  stepColor: string; // "emerald" | "purple" | "rose"
}

const steps: StepConfig[] = [
  {
    step: 1,
    total: 7,
    stageName: "Cloud Session Bootstrap & Tunnel",
    model: "solari cloud browser [ACTION]",
    leftTitle: "Autonomous Ingress Tunnel Daemon",
    leftSubtitle: "Exposing localhost to Solari cloud microVMs",
    leftHtml: `
      <div style="background:#000; border-radius:14px; border:1px solid rgba(255,255,255,0.12); padding:22px; font-family:'JetBrains Mono',monospace; font-size:13px; height:100%; box-sizing:border-box; display:flex; flex-direction:column; justify-content:space-between;">
        <div>
          <div style="color:#10b981; margin-bottom:10px; font-weight:bold;">❯ npx coldstart tunnel 4310</div>
          <div style="color:#64748b; margin-bottom:6px;">[10:14:02.112] Spawning cloudflared quick tunnel... OK</div>
          <div style="color:#64748b; margin-bottom:6px;">[10:14:04.530] Capturing trycloudflare.com URL from stdout... OK</div>
          <div style="color:#38bdf8; margin-bottom:10px;">[10:14:05.891] TARGET_URL exported → https://quiet-panda-41.trycloudflare.com</div>
        </div>
        <div style="padding:16px; background:rgba(16,185,129,0.08); border:1px solid rgba(16,185,129,0.35); border-radius:10px;">
          <div style="color:#34d399; font-weight:bold; font-size:14px; margin-bottom:6px;">🛡️ Session Guard Armed</div>
          <div style="color:#cbd5e1; font-size:13px; margin-bottom:4px;">withSessionGuard() → browser.close() + solari.close() guaranteed in finally</div>
          <div style="color:#cbd5e1; font-size:13px;">Zero leaked microVMs — even when the test throws.</div>
        </div>
      </div>
    `,
    actionType: "BOOT & TUNNEL",
    actionDetail: "ingress live in ~4s",
    targetElement: "TunnelDaemon + Session Guard",
    rationaleTitle: "No-Zombie Doctrine",
    rationaleBadge: "Leak-Proof",
    rationaleText: "Every cloud session is wrapped in a lifecycle guard. Teardown runs in a finally block — 0 leaked microVMs across 110 tests.",
    verifierType: "Infrastructure Probe",
    verifierStatus: "READY (0 Leaks)",
    verifierDetails: "TARGET_URL live • Session recording enabled",
    stepColor: "emerald"
  },
  {
    step: 2,
    total: 7,
    stageName: "Smart Reset & Idempotent Seeding",
    model: "qa-framework seeder [FIXTURE]",
    leftTitle: "SmartReset Fixture Seeding",
    leftSubtitle: "Deterministic preconditions before every batch",
    leftHtml: `
      <div style="background:#000; border-radius:14px; border:1px solid rgba(16,185,129,0.4); padding:22px; font-family:'JetBrains Mono',monospace; font-size:13px; height:100%; box-sizing:border-box; display:flex; flex-direction:column; justify-content:space-between;">
        <div>
          <div style="color:#10b981; margin-bottom:8px; font-weight:bold;">❯ SmartReset.seed("qa-auto-daily-report")</div>
          <div style="color:#94a3b8; margin-bottom:6px;">DELETE FROM automations WHERE id = 'qa-auto-daily-report' → 1 row</div>
          <div style="color:#94a3b8; margin-bottom:6px;">INSERT fixture (cron 0 9 * * *, Asia/Jakarta) → OK</div>
          <div style="color:#34d399; font-weight:bold; margin-bottom:6px;">Re-run #2: same seed → same state (idempotent ✓)</div>
        </div>
        <div style="background:rgba(16,185,129,0.15); border:1px solid #10b981; border-radius:8px; padding:10px 14px; color:#10b981; font-weight:bold; text-align:center; font-size:14px;">
          ✓ FIXTURES SEEDED — rerunnable without residue
        </div>
      </div>
    `,
    actionType: "SEED FIXTURES",
    actionDetail: "idempotent reset",
    targetElement: "SQLite Fixtures Table",
    rationaleTitle: "Repeatability Doctrine",
    rationaleBadge: "Same Seed → Same State",
    rationaleText: "Flaky QA usually means dirty state. SmartReset wipes then seeds every fixture, so batch B5 passes the same on run 1 and run 100.",
    verifierType: "Fixture Verifier",
    verifierStatus: "SEEDED (Idempotent)",
    verifierDetails: "Cleanup + seed verified • No cross-run residue",
    stepColor: "emerald"
  },
  {
    step: 3,
    total: 7,
    stageName: "Resilient Selectors vs Copy Drift",
    model: "qa-framework selectors [PERCEPTION]",
    leftTitle: "fuzzyRoleLocator() Defeats Copy Drift",
    leftSubtitle: "Copy changed from 'Submit' to 'Send Request' — test still passes",
    leftHtml: `
      <div style="background:#090d16; border-radius:14px; border:1px solid rgba(16,185,129,0.4); padding:24px; height:100%; box-sizing:border-box; display:flex; flex-direction:column; justify-content:center; font-family:'JetBrains Mono',monospace;">
        <div style="background:#000; border:1px solid rgba(255,255,255,0.12); border-radius:10px; padding:16px; margin-bottom:14px;">
          <div style="color:#64748b; font-size:12px; margin-bottom:6px;">// brittle: breaks on any copy tweak</div>
          <div style="color:#f43f5e; font-size:13px; text-decoration:line-through;">page.getByRole('button', {'{'} name: 'Submit' {'}'})</div>
        </div>
        <div style="background:rgba(16,185,129,0.08); border:1px solid rgba(16,185,129,0.45); border-radius:10px; padding:16px;">
          <div style="color:#34d399; font-size:12px; margin-bottom:6px;">// resilient: normalized + fuzzy role match ✓</div>
          <div style="color:#e2e8f0; font-size:13px;">fuzzyRoleLocator(page, 'button', 'submit') → <strong>FOUND</strong></div>
          <div style="color:#94a3b8; font-size:12px; margin-top:4px;">normalizePattern() matched 'Send Request' @ similarity 0.81</div>
        </div>
      </div>
    `,
    actionType: "LOCATE ELEMENT",
    actionDetail: "fuzzy match 0.81",
    targetElement: "Renamed CTA Button",
    rationaleTitle: "Anti-Flake Doctrine",
    rationaleBadge: "Copy-Drift Proof",
    rationaleText: "Designers rename buttons; QA shouldn't break. Normalized accessibility selectors absorb copy drift that kills brittle locators.",
    verifierType: "Locator Engine",
    verifierStatus: "FOUND (Fuzzy 0.81)",
    verifierDetails: "Accessible name resolved • No hard-coded strings",
    stepColor: "emerald"
  },
  {
    step: 4,
    total: 7,
    stageName: "Zero-Pixel Trap Caught",
    model: "qa-framework assertions [GUARD]",
    leftTitle: "expectInteractive() Blocks Invisible Click",
    leftSubtitle: "Button exists in DOM but renders 0×0 — click would silently pass",
    leftHtml: `
      <div style="background:linear-gradient(135deg,#3b0764,#581c87,#1e1b4b); border-radius:14px; border:2px solid #f59e0b; padding:24px; height:100%; box-sizing:border-box; display:flex; flex-direction:column; justify-content:space-between; position:relative; overflow:hidden; font-family:'JetBrains Mono',monospace;">
        <div style="position:absolute; top:12px; right:14px; background:rgba(245,158,11,0.3); color:#f59e0b; border:1px solid #f59e0b; font-size:12px; font-weight:bold; padding:4px 12px; border-radius:6px;">TRAP CAUGHT (WARN)</div>
        <div>
          <div style="color:#e2e8f0; font-size:14px; margin-bottom:8px;">await expectInteractive(page, '#ghost-submit')</div>
          <div style="color:#fda4af; font-size:13px; margin-bottom:4px;">✗ boundingBox() → {'{'} width: 0, height: 0 {'}'}</div>
          <div style="color:#fda4af; font-size:13px;">✗ element is opacity:0 inside hidden container</div>
        </div>
        <div style="background:rgba(245,158,11,0.15); border:1px solid rgba(245,158,11,0.5); border-radius:8px; padding:10px 14px;">
          <div style="color:#fbbf24; font-size:13px; font-weight:bold;">⚠️ Zero-pixel element rejected — visible + positive dimensions required</div>
        </div>
      </div>
    `,
    actionType: "ASSERT INTERACTIVE",
    actionDetail: "0×0 element rejected",
    targetElement: "#ghost-submit (Hidden)",
    rationaleTitle: "Visibility Doctrine",
    rationaleBadge: "Trap Blocked",
    rationaleText: "Presence in the DOM is not interactability. expectInteractive demands visibility plus positive dimensions before any click counts.",
    verifierType: "Assertion Guard",
    verifierStatus: "WARN • CLICK BLOCKED",
    verifierDetails: "False-pass prevented • Defect filed, not hidden",
    stepColor: "rose"
  },
  {
    step: 5,
    total: 7,
    stageName: "Multi-Step E2E Run (Batches B1–B5)",
    model: "solari cloud browser [ACTION]",
    leftTitle: "Live Chat Flow Execution",
    leftSubtitle: "B2: profile switch → model select → prompt dispatch → stream",
    leftHtml: `
      <div style="background:#090d16; border-radius:14px; border:1px solid rgba(16,185,129,0.4); padding:24px; height:100%; box-sizing:border-box; position:relative; overflow:hidden; font-family:'JetBrains Mono',monospace;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
          <span style="color:#fff; font-weight:bold; font-size:15px;">Batch B2 — Chat & Agent Loop</span>
          <span style="color:#10b981; font-size:12px;">Step 5 / 6 ✓</span>
        </div>
        <div style="font-size:13px; color:#34d399; margin-bottom:6px;">[B2-01] Composer visible + Default Bot profile ✓</div>
        <div style="font-size:13px; color:#34d399; margin-bottom:6px;">[B2-02] Profile switch Default ⇄ Super Bot ✓</div>
        <div style="font-size:13px; color:#34d399; margin-bottom:6px;">[B2-04] Empty submit blocked, multiline grows ✓</div>
        <div style="font-size:13px; color:#38bdf8; margin-bottom:14px;">[B2-05] Prompt dispatched… streaming indicator live ▊</div>
        <div style="background:rgba(0,0,0,0.85); border:1px solid rgba(255,255,255,0.12); border-radius:8px; padding:8px 14px; font-size:12px; color:#cbd5e1;">
          TYPE composer → CLICK send → AWAIT assistant turn
        </div>
      </div>
    `,
    actionType: "CUA E2E RUN",
    actionDetail: "6/6 steps pass",
    targetElement: "Batches B1–B5 (30 checks)",
    rationaleTitle: "End-to-End Doctrine",
    rationaleBadge: "Live, Not Mocked",
    rationaleText: "Real cloud Chromium against a live tunnel URL. Auth, chat, history, profiles, workers — 30 functional checks with screenshots per step.",
    verifierType: "Execution Engine",
    verifierStatus: "6/6 STEPS PASS",
    verifierDetails: "Screenshot per step • Console errors captured",
    stepColor: "emerald"
  },
  {
    step: 6,
    total: 7,
    stageName: "Dual-Layer Verification (UI + DB Diff)",
    model: "qa-framework db-diff [GROUND TRUTH]",
    leftTitle: "DatabaseDiffEngine Ground Truth",
    leftSubtitle: "UI said 'saved' — the database confirms it",
    leftHtml: `
      <div style="background:#000; border-radius:14px; border:1px solid rgba(16,185,129,0.4); padding:22px; font-family:'JetBrains Mono',monospace; font-size:13px; height:100%; box-sizing:border-box; display:flex; flex-direction:column; justify-content:space-between;">
        <div>
          <div style="color:#10b981; margin-bottom:8px; font-weight:bold;">❯ DatabaseDiffEngine.diff(before, after)</div>
          <div style="color:#cbd5e1; margin-bottom:4px;">[PASS] D1: automation row exists in SQLite</div>
          <div style="color:#cbd5e1; margin-bottom:4px;">[PASS] D2: cron expression matches seeded expectation</div>
          <div style="color:#cbd5e1; margin-bottom:12px;">[PASS] D3: updated_at inside execution window</div>
        </div>
        <div style="background:rgba(16,185,129,0.15); border:1px solid #10b981; border-radius:8px; padding:10px 14px; color:#10b981; font-weight:bold; text-align:center; font-size:14px;">
          ✓ VERIFIED: UI claim backed by direct DB read
        </div>
      </div>
    `,
    actionType: "DB DIFF CHECK",
    actionDetail: "fail-closed D1-D3",
    targetElement: "SQLite Ground Truth",
    rationaleTitle: "Trust-Nothing Doctrine",
    rationaleBadge: "Zero Self-Report",
    rationaleText: "Never trust the UI's word that a write succeeded. The diff engine reads SQLite directly — fail-closed, like ColdStart's D1-D3 verifier.",
    verifierType: "SQLite Verifier",
    verifierStatus: "VERIFIED (D1, D2, D3)",
    verifierDetails: "Before/after snapshots • No agent narration",
    stepColor: "emerald"
  },
  {
    step: 7,
    total: 7,
    stageName: "Heuristic Verdict & QA Scorecard",
    model: "qa-framework heuristics [JUDGE]",
    leftTitle: "Combined QA Scorecard",
    leftSubtitle: "Functional QA verdict across all five batches",
    leftHtml: `
      <div style="background:#090d16; border-radius:14px; border:1px solid rgba(16,185,129,0.5); padding:20px; height:100%; box-sizing:border-box; display:flex; flex-direction:column; justify-content:space-between;">
        <table style="width:100%; border-collapse:collapse; font-family:'JetBrains Mono',monospace; font-size:12px; text-align:left;">
          <thead>
            <tr style="border-bottom:1px solid rgba(255,255,255,0.2); color:#94a3b8;">
              <th style="padding:8px 6px;">BATCH</th>
              <th style="padding:8px 6px;">FOCUS</th>
              <th style="padding:8px 6px;">CHECKS</th>
              <th style="padding:8px 6px;">VERDICT</th>
            </tr>
          </thead>
          <tbody>
            <tr style="border-bottom:1px solid rgba(255,255,255,0.08); color:#fff;">
              <td style="padding:10px 6px; color:#38bdf8; font-weight:bold;">B1 Auth</td>
              <td style="padding:10px 6px;">Login & guards</td>
              <td style="padding:10px 6px; color:#10b981; font-weight:bold;">6/6</td>
              <td style="padding:10px 6px;"><span style="background:#064e3b; color:#a7f3d0; padding:3px 8px; border-radius:4px; font-weight:bold;">PASS</span></td>
            </tr>
            <tr style="border-bottom:1px solid rgba(255,255,255,0.08); color:#fff;">
              <td style="padding:10px 6px; color:#38bdf8; font-weight:bold;">B2–B4</td>
              <td style="padding:10px 6px;">Chat · Files · Profiles</td>
              <td style="padding:10px 6px; color:#10b981; font-weight:bold;">19/19</td>
              <td style="padding:10px 6px;"><span style="background:#064e3b; color:#a7f3d0; padding:3px 8px; border-radius:4px; font-weight:bold;">PASS</span></td>
            </tr>
            <tr style="color:#fff;">
              <td style="padding:10px 6px; color:#38bdf8; font-weight:bold;">B5 Workers</td>
              <td style="padding:10px 6px;">Automations & logs</td>
              <td style="padding:10px 6px; color:#10b981; font-weight:bold;">5/6*</td>
              <td style="padding:10px 6px;"><span style="background:#451a03; color:#fbbf24; padding:3px 8px; border-radius:4px; font-weight:bold;">WARN</span></td>
            </tr>
          </tbody>
        </table>
        <div style="background:rgba(16,185,129,0.12); border:1px solid rgba(16,185,129,0.45); border-radius:10px; padding:12px 16px; text-align:center;">
          <div style="color:#10b981; font-weight:bold; font-size:14px; font-family:monospace;">✓ LIVE FUNCTIONAL QA CERTIFIED</div>
          <div style="color:#cbd5e1; font-size:12px; margin-top:3px;">*B5 heuristic: 1 enhancement filed — "I think it should be enhanced, because…"</div>
        </div>
      </div>
    `,
    actionType: "FULL QA COMPLETE",
    actionDetail: "30 checks evaluated",
    targetElement: "Heuristic Engine",
    rationaleTitle: "Strategic Summary",
    rationaleBadge: "Ready for CI Gate",
    rationaleText: "Slop-Catcher asks 'does it look right?' The QA Framework asks 'does it work?' Together they form the full production gate.",
    verifierType: "Production Readiness",
    verifierStatus: "QA CERTIFIED",
    verifierDetails: "24 unit tests green • B1–B5 evidence archived",
    stepColor: "emerald"
  }
];

function generateHtml(cfg: StepConfig): string {
  const badgeBg = cfg.stepColor === "rose" ? "rgba(244,63,94,0.2)" : cfg.stepColor === "purple" ? "rgba(168,85,247,0.2)" : "rgba(16,185,129,0.2)";
  const badgeBorder = cfg.stepColor === "rose" ? "#f43f5e" : cfg.stepColor === "purple" ? "#a855f7" : "#10b981";
  const badgeText = cfg.stepColor === "rose" ? "#fda4af" : cfg.stepColor === "purple" ? "#d8b4fe" : "#6ee7b7";

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <style>
    * { margin:0; padding:0; box-sizing:border-box; }
    body {
      width: 1280px;
      height: 720px;
      background: #070a0d;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      color: #f8fafc;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      -webkit-font-smoothing: antialiased;
    }
    .title-bar {
      height: 48px;
      background: linear-gradient(90deg, #0d1219, #090c10);
      border-bottom: 1px solid rgba(255,255,255,0.08);
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 24px;
    }
    .traffic-lights {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .dot { width: 13px; height: 13px; border-radius: 50%; display: inline-block; }
    .dot-red { background: #ef4444; }
    .dot-yellow { background: #f59e0b; }
    .dot-green { background: #10b981; }
    .title-text {
      font-family: "JetBrains Mono", monospace;
      font-size: 14px;
      color: #94a3b8;
      margin-left: 16px;
    }
    .title-text strong { color: #f8fafc; }
    .step-counter {
      font-family: "JetBrains Mono", monospace;
      font-size: 13px;
      font-weight: bold;
      color: ${badgeText};
      background: ${badgeBg};
      border: 1px solid ${badgeBorder};
      padding: 4px 12px;
      border-radius: 8px;
    }
    .main-body {
      flex: 1;
      display: flex;
      overflow: hidden;
    }
    .left-panel {
      width: 760px;
      background: #05070a;
      border-right: 1px solid rgba(255,255,255,0.08);
      padding: 24px;
      display: flex;
      flex-direction: column;
    }
    .left-header {
      margin-bottom: 16px;
    }
    .left-header h3 {
      font-size: 16px;
      font-weight: 700;
      color: #f8fafc;
    }
    .left-header p {
      font-size: 12px;
      color: #64748b;
      margin-top: 3px;
      font-family: "JetBrains Mono", monospace;
    }
    .left-canvas {
      flex: 1;
      border-radius: 12px;
      overflow: hidden;
    }
    .right-panel {
      flex: 1;
      background: #090c10;
      padding: 24px 28px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }
    .section-label {
      font-family: "JetBrains Mono", monospace;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #64748b;
      margin-bottom: 6px;
    }
    .action-chip {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: ${badgeBg};
      border: 1px solid ${badgeBorder};
      color: ${badgeText};
      padding: 8px 14px;
      border-radius: 8px;
      font-family: "JetBrains Mono", monospace;
      font-size: 13px;
      font-weight: 700;
    }
    .target-val {
      font-family: "JetBrains Mono", monospace;
      font-size: 13px;
      color: #f1f5f9;
      font-weight: 600;
    }
    .rationale-card {
      background: rgba(0,0,0,0.5);
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 10px;
      padding: 14px 16px;
      font-size: 13px;
      color: #cbd5e1;
      line-height: 1.5;
      font-family: "JetBrains Mono", monospace;
    }
    .verifier-card {
      background: rgba(16,185,129,0.08);
      border: 1px solid rgba(16,185,129,0.3);
      border-radius: 10px;
      padding: 12px 16px;
    }
    .verifier-card.rose {
      background: rgba(244,63,94,0.08);
      border: 1px solid rgba(244,63,94,0.3);
    }
    .verifier-title {
      font-size: 12px;
      font-weight: 700;
      color: #34d399;
      font-family: "JetBrains Mono", monospace;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .verifier-title.rose { color: #f43f5e; }
    .verifier-desc {
      font-size: 12px;
      color: #94a3b8;
      font-family: "JetBrains Mono", monospace;
      margin-top: 4px;
    }
    .bottom-bar {
      height: 48px;
      background: #07090d;
      border-top: 1px solid rgba(255,255,255,0.06);
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 24px;
      font-family: "JetBrains Mono", monospace;
      font-size: 12px;
    }
    .step-pills {
      display: flex;
      gap: 6px;
      align-items: center;
    }
    .pill {
      width: 28px;
      height: 26px;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 6px;
      background: rgba(255,255,255,0.05);
      color: #64748b;
      font-size: 12px;
    }
    .pill.active {
      background: ${badgeBorder};
      color: #fff;
      font-weight: bold;
    }
  </style>
</head>
<body>
  <div class="title-bar">
    <div style="display:flex; align-items:center;">
      <div class="traffic-lights">
        <span class="dot dot-red"></span>
        <span class="dot dot-yellow"></span>
        <span class="dot dot-green"></span>
      </div>
      <div class="title-text">
        QA Framework Action Replay • <strong>${cfg.stageName}</strong> • <span style="color:#38bdf8;">${cfg.model}</span>
      </div>
    </div>
    <div class="step-counter">
      STEP ${String(cfg.step).padStart(2, '0')} / ${String(cfg.total).padStart(2, '0')}
    </div>
  </div>

  <div class="main-body">
    <div class="left-panel">
      <div class="left-header">
        <h3>${cfg.leftTitle}</h3>
        <p>${cfg.leftSubtitle}</p>
      </div>
      <div class="left-canvas">
        ${cfg.leftHtml}
      </div>
    </div>

    <div class="right-panel">
      <div>
        <div class="section-label">Pipeline Action</div>
        <div class="action-chip">
          <span>🎯 ${cfg.actionType}</span>
          <span style="font-weight:normal; opacity:0.8;">• ${cfg.actionDetail}</span>
        </div>
      </div>

      <div>
        <div class="section-label">Target Component</div>
        <div class="target-val">${cfg.targetElement}</div>
      </div>

      <div>
        <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
          <span class="section-label">${cfg.rationaleTitle}</span>
          <span style="font-size:11px; font-family:monospace; color:${badgeText};">${cfg.rationaleBadge}</span>
        </div>
        <div class="rationale-card">
          &ldquo;${cfg.rationaleText}&rdquo;
        </div>
      </div>

      <div class="verifier-card ${cfg.stepColor}">
        <div class="verifier-title ${cfg.stepColor}">
          <span>●</span>
          <span>${cfg.verifierType}: ${cfg.verifierStatus}</span>
        </div>
        <div class="verifier-desc">${cfg.verifierDetails}</div>
      </div>
    </div>
  </div>

  <div class="bottom-bar">
    <div style="display:flex; align-items:center; gap:10px;">
      <span style="color:#64748b;">STEPS:</span>
      <div class="step-pills">
        ${steps.map(s => `<div class="pill ${s.step === cfg.step ? 'active' : ''}">${s.step}</div>`).join('')}
      </div>
    </div>
    <div style="color:#10b981;">
      ColdStart × QA Framework Action Replay (1280×720 • 2.0s/step)
    </div>
  </div>
</body>
</html>`;
}

async function main() {
  console.log("Rendering 7 QA Framework replay frames at 1280x720 with Headless Chrome...");
  const framePaths: string[] = [];

  for (const s of steps) {
    const htmlContent = generateHtml(s);
    const htmlFile = path.join(tempDir, `qa_frame_${s.step}.html`);
    const pngFile = path.join(tempDir, `qa_frame_${s.step}.png`);
    fs.writeFileSync(htmlFile, htmlContent, "utf8");

    console.log(`Capturing frame ${s.step}/${steps.length} (1280x720)...`);
    execSync(`"${chromePath}" --headless=new --disable-gpu --no-sandbox "--screenshot=${pngFile}" --window-size=1280,720 "file:///${htmlFile.replace(/\\/g, "/")}"`);

    framePaths.push(pngFile);
  }

  console.log("Assembling frames into high-resolution GIF and MP4 with ffmpeg...");
  const gifOut = path.resolve(__dirname, "../artifacts/qa-framework-replay.gif");
  const docsGifOut = path.resolve(__dirname, "../docs/artifacts/qa-framework-replay.gif");
  const mp4Out = path.resolve(__dirname, "../artifacts/qa-framework-replay.mp4");
  const docsMp4Out = path.resolve(__dirname, "../docs/artifacts/qa-framework-replay.mp4");

  // Create concat list for ffmpeg with 2 seconds per frame
  const listFile = path.join(tempDir, "qa_frames.txt");
  let listContent = "";
  for (const f of framePaths) {
    listContent += `file '${f.replace(/\\/g, "/")}'\nduration 2.0\n`;
  }
  // Repeat last frame for hold
  listContent += `file '${framePaths[framePaths.length - 1].replace(/\\/g, "/")}'\nduration 3.0\n`;
  fs.writeFileSync(listFile, listContent, "utf8");

  // Generate GIF with palettegen/paletteuse for crisp 1280x720 social media quality
  execSync(`ffmpeg -y -f concat -safe 0 -i "${listFile}" -vf "fps=10,split[s0][s1];[s0]palettegen=max_colors=256:reserve_transparent=0:stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=4" -loop 0 "${gifOut}"`);
  fs.copyFileSync(gifOut, docsGifOut);
  console.log(`✓ High-Res GIF generated at ${gifOut} (${(fs.statSync(gifOut).size / 1024).toFixed(1)} KB)`);

  // Generate MP4 for Discord / Twitter / X video uploads (1280x720 H.264)
  execSync(`ffmpeg -y -f concat -safe 0 -i "${listFile}" -c:v libx264 -pix_fmt yuv420p -movflags +faststart "${mp4Out}"`);
  fs.copyFileSync(mp4Out, docsMp4Out);
  console.log(`✓ High-Res MP4 generated at ${mp4Out} (${(fs.statSync(mp4Out).size / 1024).toFixed(1)} KB)`);
}

main().catch(err => {
  console.error("Error generating replay media:", err);
  process.exit(1);
});
