# Monitor Model Training Notice

**Status:** SKIPPED
**Reason:** Missing optional dependencies: No module named 'torch'

## Policy Conformance
- Phase 3B strictly enforces zero mandatory heavy ML dependencies (PyTorch / HuggingFace Transformers).
- Standard testing, continuous integration, and baseline runtime operate on deterministic heuristic monitors.
- To enable training:
  1. Install optional dependencies: `pip install torch transformers datasets accelerate`
  2. Re-run `python scripts/train_monitors.py --smoke`
