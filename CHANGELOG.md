# Changelog

## 2026-10-20: fixes found by a source read

These were found by reading the source against its own documentation after release, not by the earlier test and review passes. Each fix has a regression test in
`tests/test_findings_20261020.py` that failed before the fix, and each fix was checked by undoing it and confirming a test fails. Behaviour that changed is listed under "Changed".

### Fixed
- `predict.py` counted a verdict of `1` or `0` as a real boolean, like the promotion gate did; and the overseer hashed a candidate with `default=repr` (a memory address for any object). It now requires real booleans and refuses a candidate that is not plain data.
- **The promotion gate and the vital signs counted a verdict of `1` or `0` as a real `True`/`False`.** They now require real booleans.
