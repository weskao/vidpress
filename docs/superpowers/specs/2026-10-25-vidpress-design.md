# Vidpress design

## Intent
Free macOS terminal video compression: a delightful colorful interface for one-off use and a dependable batch CLI for scripts. User controls quality, codec, HDR and size; input videos must never be overwritten or deleted.

## Approaches
- Plain FFmpeg shell scripts: smallest footprint, but hard to make safe and interactive across many files.
- Python CLI using standard library + Rich (selected): easy packaging via uv, concurrency via threads supervising FFmpeg subprocesses, no custom transcoder.
- Full Textual TUI: more complex and costly for a workflow that ultimately starts a batch.

## Architecture
- `engine.py`: discovers videos, probes FFprobe metadata, validates codec/media combinations, generates FFmpeg commands, supervises runs, validates completed output, protects originals, emits reports.
- `cli.py`: argparse flags, rich terminal prompts/progress/results, optional Homebrew setup.
- `tests/`: isolated safety checks and FFmpeg integration.

## Constraints
- Python 3.10+, uv with a single installed `vidpress` entrypoint.
- macOS primary, basic FFmpeg-based processing supports Linux.
- Software H.264/H.265/AV1 and optional Apple VideoToolbox.
- CRF profiles, bitrate approximation target size, optional ab-av1 VMAF search.
- Transcode may cost significant power; worker default conservative.
- Never silently overwrite, never delete original. Validate output before publishing atomically.
- Preserve HDR/10-bit when possible. SDR tone mapping explicit; HDR+H.264 requires conversion.
- Homebrew installs opt-in/confirmed, not silent privileged shell downloads.
- English + Traditional Chinese docs; GitHub Actions matrix.

## Tradeoffs and caveats
- Target file size uses single-pass average bitrate, not guaranteed byte-exact.
- VMAF search delegates to ab-av1 and is supported on software H.264/H.265/AV1 without scaling/tone mapping.
- Subtitle stream copy uses MKV to avoid MP4 codec compatibility surprises.
- Unrecognized, image-only or non-seekable streams fail with clear messages.
- FFmpeg's internal threads are only partially constrained by `-threads`; jobs are conservative.
