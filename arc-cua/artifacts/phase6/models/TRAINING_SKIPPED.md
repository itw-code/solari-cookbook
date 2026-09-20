# ModernBERT Monitor Model Training Notice

**Status:** TRAINING_SKIPPED
**Reason:** PyTorch is not installed (No module named 'torch')

## Policy Conformance
- Phase 6 requires production GPU acceleration and deep learning frameworks (`torch`, `transformers`) to fine-tune ModernBERT-base.
- Host environment: Windows/CI without active CUDA GPU or ML libraries.
- The ARC system defaults to deterministic heuristic monitors (`HeuristicMonitorAdapter`), maintaining full operational capability.
- To execute live model training:
  1. Deploy to a Linux host equipped with an NVIDIA GPU and CUDA drivers.
  2. Install deep learning dependencies: `pip install torch transformers datasets accelerate scikit-learn`
  3. Re-run: `python scripts/train_monitors_full.py`
