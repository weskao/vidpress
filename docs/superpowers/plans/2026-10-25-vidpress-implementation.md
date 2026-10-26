# Vidpress implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship a free colorful and safe uv-installable FFmpeg CLI.

**Architecture:** Separate FFmpeg planning/safe execution from argparse/Rich UI; subprocesses run concurrently using a bounded thread pool.

**Tech Stack:** Python 3.10+, FFmpeg, FFprobe, uv, Rich, Pytest, Ruff, ab-av1 (optional).

**Spec:** `docs/superpowers/specs/2026-10-25-vidpress-design.md`

## Global Constraints
- Never overwrite source or existing destination.
- No silent brew installs, only explicit or confirmed.
- Support a noninteractive `compress` command.
- All failures should be recorded, with nonzero exit codes.

## Review Focus
- Filenames with spaces/Unicode: `test_unicode_paths_and_end_to_end_encoding`.
- Existing output never overwritten: `test_existing_output_not_overwritten`.
- Output larger than input: `test_skip_larger_deletes_temp_and_preserves_original`.
- HDR+H.264 rejected: `test_reject_invalid_combinations`.
- Colliding output names detected: `test_duplicate_stems_from_different_sources_keep_distinct_destination`.

## Task 1: Engine and safety [x]
- [x] Write failing tests for media selection, probe, encode command and cleanup.
- [x] Implement `engine.py`.
- [x] Run tests and check return codes.

## Task 2: CLI and user experience [x]
- [x] Write failing tests for CLI flag parsing.
- [x] Implement `cli.py` with Rich display, interactive wizard, concurrency, doctor, reports.
- [x] Add uv packaging and Makefile.

## Task 3: Documentation, CI, quality [x]
- [x] Document how to install/use all advanced flags in both English and zh-TW.
- [x] Add GitHub Actions, .gitignore, sample commands.
- [x] Execute local tests/smoke and lint; record outcomes before claiming success.

## Task 4: Publish private repository [ ]
- [ ] Create GitHub private repository (requires repository creation permission).
- [ ] Push main and verify remote URL and visibility.
