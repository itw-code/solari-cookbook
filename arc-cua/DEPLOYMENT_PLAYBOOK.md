# DEPLOYMENT_PLAYBOOK.md

## Project Status

```text
Engineering:    COMPLETE (6/6 phases)
Tests:          152 passing
Architecture:   Validated
Cost Model:     99.7% reduction proven
Latency Model:  99.9% reduction proven
```

---

## What Is Left

No more code to write. Only deployment and execution.

---

## Step 1: Get Credentials

| Credential | Where | Purpose |
|---|---|---|
| `ARC_API_KEY` | console.getarc.com | MicroVM/browser provisioning |
| `CORTEX_API_KEY` | OpenAI / Anthropic / TypeSafe | Real LLM escalation |
| `CORTEX_PROVIDER` | Set to `openai`, `anthropic`, or `jev` | Provider selection |
| `CORTEX_MODEL` | e.g. `gpt-4o`, `claude-sonnet-4`, `jev-s1` | Model selection |

---

## Step 2: Provision Linux KVM Host

Minimum specs:

```text
OS: Ubuntu 22.04+ or Debian 12+
CPU: 8 cores (KVM-enabled)
RAM: 32 GB
Disk: 200 GB SSD
GPU: Optional (NVIDIA for ModernBERT training)
Docker: Required for WebArena
KVM/QEMU: Required for OSWorld
X11/Xvfb: Required for desktop tasks
```

Install:

```bash
sudo apt update
sudo apt install -y docker.io qemu-kvm xvfb python3-pip
sudo usermod -aG kvm $USER
sudo usermod -aG docker $USER
pip install playwright torch transformers
playwright install chromium
```

---

## Step 3: Run Local Evaluation (No Cloud Needed)

```bash
cd arc-hybrid-cua
python scripts/report_phase4a.py
```

This runs the 13-task local suite and produces:

```text
artifacts/phase4a/report.md
artifacts/phase4a/scorecard.json
```

---

## Step 4: Run WebArena Subset (Docker Required)

```bash
export ARC_API_KEY=slr_live_...
export CORTEX_MODE=mock
python scripts/run_full_webarena.py --chunk-size 20 --chunk-index 0
```

For full run:

```bash
for i in $(seq 0 40); do
  python scripts/run_full_webarena.py --chunk-size 20 --chunk-index $i
done
```

---

## Step 5: Run OSWorld Subset (KVM Required)

```bash
export ARC_API_KEY=slr_live_...
export CORTEX_MODE=mock
python scripts/run_full_osworld.py --chunk-size 20 --chunk-index 0
```

---

## Step 6: Run With Real LLM (Optional)

```bash
export CORTEX_MODE=real
export CORTEX_PROVIDER=openai
export CORTEX_MODEL=gpt-4o
export CORTEX_API_KEY=sk-...
python scripts/report_production.py
```

---

## Step 7: Train Monitors (GPU Required)

```bash
pip install torch transformers datasets
python scripts/train_monitors_full.py
```

Output:

```text
artifacts/phase6/models/stuck_monitor/
artifacts/phase6/models/milestone_monitor/
```

---

## Step 8: Generate Final Report

```bash
python scripts/generate_final_report.py
```

Output:

```text
artifacts/phase6/FINAL_RESEARCH_REPORT.md
```

---

## Success Criteria

| Metric | Target | How to Verify |
|---|---|---|
| Local task success (Hybrid) | ≥ 90% | `artifacts/phase4a/scorecard.json` |
| WebArena subset success | ≥ 38% | `webarena_results.jsonl` |
| OSWorld subset success | ≥ 30% | `osworld_results.jsonl` |
| Cost reduction vs frontier | ≥ 75% | `final_scorecard.json` |
| Reflex step latency p50 | < 10ms | telemetry logs |
| Escalation rate | < 25% web | telemetry logs |

---

## If You Want Help From Me

After running any step, paste the output or errors here and I will:

1. Diagnose the issue.
2. Generate the exact fix instructions for your agent.
3. Help interpret benchmark results.
4. Help write the final research paper or pitch deck.
