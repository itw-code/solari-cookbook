"""Verify the audit-remediation regression suite actually discriminates.

A regression test that passes against the broken code is not a regression test. This
script proves `tests/test_audit_remediation.py` fails on the pre-remediation sources by
copying the pre-fix revisions into a throwaway directory and running pytest against that
copy — the working tree is never modified.

Pre-fix revisions are taken from git:
  * `cdp_extractor.py` and `cli.py` are baselined at the **staged** revision (`:src/...`),
    because they already carried staged changes that the remediation builds on.
  * `playwright_executor.py`, `executor_interface.py` and `monitors/stuck_monitor.py` are
    baselined at `HEAD`.

Usage:
    python scripts/verify_audit_remediation.py            # check the default test file
    python scripts/verify_audit_remediation.py --keep      # keep the temp tree for inspection

Exit code 0 when the suite discriminates (i.e. failures occur pre-fix and none occur
post-fix); 1 otherwise.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
TEST_FILE = "tests/test_audit_remediation.py"

# source path -> git revision holding the PRE-FIX content
PREFIX_SOURCES = {
    "arc_cua/cdp_extractor.py": ":src/arc_cua/cdp_extractor.py",
    "arc_cua/cli.py": ":src/arc_cua/cli.py",
    "arc_cua/playwright_executor.py": "HEAD:src/arc_cua/playwright_executor.py",
    "arc_cua/executor_interface.py": "HEAD:src/arc_cua/executor_interface.py",
    "arc_cua/monitors/stuck_monitor.py": "HEAD:src/arc_cua/monitors/stuck_monitor.py",
}


def _git_show(revision: str) -> str:
    proc = subprocess.run(
        ["git", "show", revision],
        cwd=REPO, capture_output=True, text=True, check=True,
    )
    return proc.stdout


def _run_pytest(test_path: pathlib.Path) -> tuple[int, str]:
    """Run pytest against `test_path`.

    The test module inserts `<its parent>/../src` onto `sys.path` itself, so the temp
    tree must mirror the repository layout (`<root>/src/arc_cua`, `<root>/tests/...`)
    for the pre-fix sources to actually be imported. Setting PYTHONPATH is not enough:
    the test's own `sys.path.insert` would put the real `src/` ahead of it.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_path), "-q", "-p", "no:randomly"],
        cwd=REPO, capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


def _summarise(output: str) -> tuple[int, int, int]:
    """Return (passed, failed, errored) parsed from a pytest -q summary line."""
    def _count(pattern: str) -> int:
        m = re.search(pattern, output)
        return int(m.group(1)) if m else 0

    return (
        _count(r"(\d+) passed"),
        _count(r"(\d+) failed"),
        _count(r"(\d+) error"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="keep the temporary tree")
    parser.add_argument("--test-file", default=TEST_FILE, help="test file to run")
    args = parser.parse_args()

    test_path = REPO / args.test_file
    if not test_path.exists():
        print(f"ERROR: test file not found: {test_path}", file=sys.stderr)
        return 1

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="arc_prefix_verify_"))
    prefix_root = tmp / "prefix_src"
    (prefix_root / "arc_cua" / "monitors").mkdir(parents=True)

    try:
        # Build a package tree at the pre-fix revision.
        for rel, revision in PREFIX_SOURCES.items():
            dest = prefix_root / rel
            dest.write_text(_git_show(revision), encoding="utf-8")
            print(f"  pre-fix {rel:44s} <- {revision}")

        # The remaining modules are unchanged by the remediation; copy them as-is.
        for src in (REPO / "src" / "arc_cua").rglob("*.py"):
            rel = src.relative_to(REPO / "src" / "arc_cua")
            dest = prefix_root / "arc_cua" / rel
            if dest.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

        # Mirror the repository layout so the test module's own
        # `sys.path.insert(0, <parent>/../src)` resolves to the PRE-FIX package.
        # `prefix_root` holds an `arc_cua/` package dir, so move that, not prefix_root.
        mirror = tmp / "repo_mirror"
        (mirror / "src").mkdir(parents=True)
        shutil.move(str(prefix_root / "arc_cua"), str(mirror / "src" / "arc_cua"))
        (mirror / "tests").mkdir()
        mirrored_test = mirror / "tests" / pathlib.Path(args.test_file).name
        shutil.copy2(test_path, mirrored_test)

        # Sanity-check the mirror is importable and actually pre-fix, so a silent
        # fall-through to the real package cannot masquerade as a passing verdict.
        probe = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, r'%s'); import arc_cua.cdp_extractor as m; "
             "print(m.__file__); print(hasattr(m.SanitizedAXTree, 'truncated') and "
             "'truncation_notice' in getattr(m.SanitizedAXTree, '__dataclass_fields__', {}))"
             % (mirror / "src")],
            capture_output=True, text=True,
        )
        probe_out = probe.stdout.strip().splitlines()
        if probe.returncode != 0 or not probe_out:
            print(f"\nERROR: pre-fix mirror is not importable:\n{probe.stderr}", file=sys.stderr)
            return 1
        resolved, has_manifest = probe_out[0], (probe_out[1] if len(probe_out) > 1 else "")
        print(f"\n  mirror resolves arc_cua -> {resolved}")
        if "repo_mirror" not in resolved:
            print("  ERROR: mirror did not shadow the installed package.", file=sys.stderr)
            return 1
        if has_manifest == "True":
            print("  ERROR: mirror carries the FIXED extractor (truncation_notice present); "
                  "the pre-fix revision was not selected.", file=sys.stderr)
            return 1
        print("  mirror is pre-fix (no truncation_notice) — OK")

        print("\n=== PRE-FIX run (expect failures) ===")
        rc_pre, out_pre = _run_pytest(mirrored_test)
        pre_passed, pre_failed, pre_errors = _summarise(out_pre)
        print(f"  passed={pre_passed} failed={pre_failed} errors={pre_errors}")
        for line in out_pre.splitlines():
            if line.startswith("FAILED") or line.startswith("ERROR"):
                print(f"  {line}")

        if pre_errors or pre_passed + pre_failed == 0:
            print("\n  ERROR: the pre-fix run did not collect — pytest reported "
                  f"{pre_errors} error(s) and {pre_passed + pre_failed} test(s). A "
                  "collection failure is NOT evidence of discrimination: it usually means "
                  "a module-level import the pre-fix revision cannot satisfy. Fix the "
                  "import so the suite collects and fails per-test instead.",
                  file=sys.stderr)
            return 1

        print("\n=== POST-FIX run (expect all passing) ===")
        rc_post, out_post = _run_pytest(test_path)
        post_passed, post_failed, post_errors = _summarise(out_post)
        print(f"  passed={post_passed} failed={post_failed} errors={post_errors}")
        for line in out_post.splitlines():
            if line.startswith("FAILED") or line.startswith("ERROR"):
                print(f"  {line}")

        print("\n=== VERDICT ===")
        discriminates = pre_failed > 0 and post_failed == 0
        if discriminates:
            print(f"  OK: {pre_failed}/{pre_passed + pre_failed} tests fail on pre-fix sources, "
                  f"and all {post_passed} pass on the fixed sources.")
        else:
            if pre_failed == 0:
                print("  FAIL: the suite passes against pre-fix sources — it does not "
                      "discriminate and proves nothing about the remediation.")
            if post_failed:
                print(f"  FAIL: {post_failed} test(s) fail against the fixed sources.")

        return 0 if discriminates else 1
    finally:
        if args.keep:
            print(f"\ntemp tree kept at: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
