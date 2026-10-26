# 🎬 vidpress

**A free, colorful, safe and script-friendly FFmpeg video compressor for macOS.**

- 🌏 **Traditional Chinese documentation:** [README.zh-TW.md](README.zh-TW.md)
- Written in Python 3.10+, installed with **uv** like `polytool` / `monitask-center`.
- `vidpress` opens a colorful guided terminal menu; `vidpress compress ...` works in shell scripts and automation.
- Powered by native FFmpeg/FFprobe subprocesses, not a Python video transcoder.

> **Status:** Working CLI, initial test suite and GitHub Actions workflow. CI is only verified once the code is pushed and actions complete. The initial repository was prepared locally; the private GitHub remote must be created by its owner.

![Batch demo: four sample clips compressed to H.265 in parallel](docs/images/demo.gif)

## Quick start (macOS)

```bash
brew install uv ffmpeg
# From the project directory:
uv tool install .
vidpress                   # colorful interactive interface
```

`uv tool install .` creates an isolated environment and makes `vidpress` available on your `PATH`. If a terminal does not recognize it, run `uv tool update-shell` and open a new shell. Developers can use `uv run vidpress` without globally installing the CLI.

```bash
vidpress doctor            # inspect FFmpeg/FFprobe/ab-av1/uv
vidpress doctor --install  # offer to install missing FFmpeg on macOS
vidpress presets           # list CRF quality levels
vidpress --help
```

> **Installation safety:** During compression, missing FFmpeg is detected. On macOS with Homebrew, interactive users will be asked for permission to install it. Non-interactive automation must use `--install-missing` to opt in to package installation. When automatic VMAF is requested, `ab-av1` is checked similarly; the FFmpeg build must provide `libvmaf`. Nothing runs with `sudo` behind the scenes.

## Main CLI commands

![vidpress compress: plan, per-file progress bars and results](docs/images/compress.jpeg)

![vidpress inspect: resolution, duration and HDR of a video](docs/images/inspect.jpeg)

```bash
# Default: HEVC/x265 at balanced CRF 27
vidpress compress ~/Movies/video.mov -o ~/Movies/compressed -y

# Batch video files, including nested folders, conservative CPU parallelism
vidpress compress ~/Movies/recordings -o ~/Movies/compressed -r -q balanced --jobs auto -y

# Smaller size, AV1 (CPU intensive)
vidpress compress ~/Movies/recordings -o ~/Movies/av1 -r -c av1 -q small --jobs 2 -y

# Preserve more image details
vidpress compress ~/Movies/video.mov -o ~/Movies/quality -c h265 -q high -y

# Aggressive AV1 profile
vidpress compress ~/Movies/video.mov -o ~/Movies/tiny -c av1 -q tiny -y

# Fast HEVC hardware mode on a supported Mac; output size is less predictable
vidpress compress ~/Movies/video.mov -o ~/Movies/fast -c hevc-vt -q balanced -y

# Dry run (read metadata but do not write output)
vidpress compress ~/Movies/recordings -o ~/Movies/out -r --dry-run -y

# Show input duration/resolution/HDR and other stream attributes
vidpress inspect ~/Movies/video.mov
```

## Quality presets

| Profile | H.264 CRF | H.265 CRF | AV1 CRF | Use |
|---|---:|---:|---:|---|
| `high` | 18 | 21 | 27 | Preserve detail / archival-style quality |
| `balanced` | 23 | 27 | 35 | General purpose |
| `small` | 28 | 30 | 40 | Favor smaller files |
| `tiny` | 32 | 34 | 45 | Aggressive compression; inspect quality |

CRF is **not comparable across codecs**. Lower CRF normally means higher quality/larger file. These are starting points, not objective quality guarantees. Audio defaults to re-encoded AAC 128 kbps; no subtitles by default. Original resolution and frame rate are maintained unless set explicitly.

![vidpress presets: CRF per codec and profile](docs/images/presets.jpeg)

### Advanced commands

```bash
# Custom codec, CRF and encoder preset
vidpress compress input.mp4 -o out -c h265 --crf 29 --preset slow -y

# Cap height without upscaling (e.g. 4K to 1080p)
vidpress compress input.mp4 -o out --resolution 1080 -y

# Approximate output goal per file, one-pass ABR (no guaranteed exact size)
vidpress compress input.mov -o out --target-size 100 -y

# Copy original audio streams; if copying subtitle streams, output is MKV
vidpress compress input.mov -o out --preserve-audio --preserve-subtitles -y

# Or remove audio entirely
vidpress compress input.mov -o out --audio none -y

# HDR input: auto preserves 10-bit and HDR tags for x265/AV1; to make SDR:
vidpress compress hdr_input.mov -o sdr_out --hdr sdr -c h265 -y

# Never keep a result that is equal to or larger than its input (default)
vidpress compress input.mp4 -o out --skip-if-larger -y

# If you intentionally want output even when larger
vidpress compress input.mp4 -o out --no-skip-if-larger -y

# Export results for scripts, with Unicode filenames
vidpress compress ~/Movies -r -o out --report reports/summary.csv -y
vidpress compress ~/Movies -r -o out --report reports/summary.json -y

# Explicitly allow Homebrew to install missing dependencies in scripts
vidpress compress input.mov -o out --install-missing -y
```

### Automatic H.264 / H.265 / AV1 quality optimization with VMAF

This optional feature asks `ab-av1` to *sample* the input and search for an AV1 CRF meeting the target VMAF score. It can be significantly slower than fixed-CRF compression and is **not a guarantee of perceived quality**.

```bash
brew install ab-av1
vidpress doctor
vidpress compress input.mov -o out -c av1 --auto-vmaf 95 --jobs 1 -y
# Also supports software H.265 and H.264:
vidpress compress input.mov -o out -c h265 --auto-vmaf 95 --jobs 1 -y
```

The tool executes `ab-av1 crf-search` and parses its structured newline-delimited JSON `crf-search-done` result, then uses the found CRF to encode the complete video with FFmpeg. It requires an FFmpeg build with libvmaf. `--auto-vmaf` cannot be combined with `--target-size` or `--resolution` or `--hdr sdr`; it supports the three software codecs (`h264`, `h265`, `av1`), but not VideoToolbox. Keep an eye on text, HUDs and moving-gameplay footage even when VMAF is high.

## Interactive experience

Run `vidpress` or `vidpress interactive` in an interactive terminal. The Rich UI presents a rounded-panel title, colorful menu, prompts for input/output, codec and quality, an advanced-settings wizard, confirmation before encoding, progress bars per video, time elapsed, per-file results and savings. `NO_COLOR=1` is respected by Rich and a small terminal window still works without clipped, fixed-width art. In a non-interactive shell, always invoke `vidpress compress ...`.

![Interactive mode: menu, advanced options and compression plan](docs/images/interactive.jpeg)

## All compress options

| Flag | Description |
|---|---|
| `INPUT...` | Video file(s) or directory/directories |
| `-o, --output PATH` | Output directory (default `compressed`) |
| `-c, --codec` | `h264`, `h265` (default), `av1`, `hevc-vt` (Apple VideoToolbox) |
| `-q, --quality` | `high`, `balanced` (default), `small`, `tiny` |
| `--crf N` / `--preset NAME` | Manual codec-specific quality/speed; invalid on `hevc-vt` |
| `--jobs auto\|N` | Max concurrent videos; conservative auto by CPU and codec |
| `-r, --recursive` | Include subdirectories |
| `--resolution HEIGHT` | Reduce output height only (no upscaling) |
| `--target-size MB` | Approximate output goal per file via ABR (excludes CRF/VMAF) |
| `--audio aac\|copy\|none` | Default AAC 128k, retain audio streams, or remove audio |
| `--preserve-audio` | Alias for `--audio copy` |
| `--subtitles none\|copy` | Default remove; copying switches output to MKV |
| `--preserve-subtitles` | Alias for `--subtitles copy` |
| `--hdr auto\|preserve\|sdr` | Auto preserve HDR; explicitly convert HDR to SDR via tone map |
| `--auto-vmaf N` | Use `ab-av1` to find CRF for H.264/H.265/AV1 meeting VMAF target |
| `--skip-if-larger` | Skip any result >= source size (default) |
| `--no-skip-if-larger` | Allow larger final files |
| `--dry-run` | Probe/plan only, do not write compressed videos |
| `--report PATH` | Write `.csv` or `.json` with size/savings/status/error fields |
| `--install-missing` | Install needed tools through Homebrew without another prompt |
| `-y, --yes` | Skip interactive confirmation (not a privilege escalation flag) |

## How parallel compression works

`ThreadPoolExecutor` runs **separate FFmpeg processes**, one per video, each with its own progress and failure. `--jobs auto` selects at most 2 concurrent AV1 videos, 3 for the other codecs, and also scales down with available logical CPU cores. `--threads` is passed to the encoder based on detected CPU count / job count. This is intentionally conservative: multiple x265/SVT-AV1 encoders can otherwise compete for CPU/memory and be slower than a smaller number of jobs. For batch jobs try 1, 2 and 3 and compare actual throughput.

Files are first encoded into a unique **hidden temporary file in the output directory**. Vidpress probes the result, checks output duration against the source, checks the size policy, then publishes using an exclusive filesystem hard link. It **never deletes or overwrites the original**, never replaces a pre-existing destination, and removes unsuccessful temporary results. If output is larger, status is `larger-skipped`, with the input untouched. An interrupted or failed file may produce an incomplete temporary file until the process exits; retrying won't corrupt the original.

### Important limits

- **Not a lossless transcoder.** CRF controls lossy quality. H.264/H.265/AV1 speed vs quality depends on content and hardware.
- **Size targets approximate.** `--target-size` is a one-pass bitrate estimate with mux reserve; output might exceed the target. Confirm via report; exact-byte guarantees are not claimed.
- **HDR needs care.** `--hdr auto`/`preserve` retain HDR tags and 10-bit pixel format for software x265/AV1; H.264 cannot preserve HDR in this tool. Explicit `--hdr sdr` uses `zscale` + `tonemap`, which needs suitable FFmpeg filters. Check results in a color-managed player. Source color metadata may vary.
- **Subtitles:** copying subtitles requires Matroska (.mkv); font attachments and all arbitrary streams aren't included automatically. MP4 without `--preserve-subtitles` discards subtitle streams. Other track metadata is copied where supported.
- **Compatibility:** AV1 playback may not work on older systems. Apple hardware encoding requires support from your Mac/FFmpeg build and targets speed rather than peak compression efficiency.
- **Paths:** supported `.mp4`, `.mov`, `.mkv`, `.webm`, `.avi`, `.m4v`, `.mpg`, `.mpeg`, `.ts`. Hidden files skipped for directory traversal. Nested folder structure is preserved; conflicting output filenames are rejected. Input directories under the chosen output directory are excluded from discovery.
- **Media safety:** always test on a few representative clips. Output integrity checks compare duration, but do not prove bit-perfect playback or perceptual quality. The source file is the backup.

## Development

```bash
uv sync --group dev
uv run vidpress --help
uv run pytest -q
uv run ruff check .
make help
make install
make test
make lint
```

CI tests on macOS + Ubuntu, runs Ruff, unit/integration tests and CLI smoke. A `uv.lock` is generated by `uv sync`/`uv lock` when network access to PyPI is available. The initial project bundle has **no `uv.lock`** because the creation environment did not have PyPI DNS access. The CI file intentionally runs `uv sync --group dev` (without `--locked`); commit a resolved lock file and update the workflow to `--locked` once it is generated.

## Publish as a private GitHub repository

After installing and logging in to [GitHub CLI](https://cli.github.com/):

```bash
brew install gh
# gh auth login     # only once, if not logged in
cd vidpress
git init -b main
git add .
git commit -m "feat: initialize vidpress CLI"
gh repo create weskao/vidpress --private --source . --remote origin --push
```

Alternatively after your first commit run `make publish-private`. Do not share the private repo's clone link publicly with people who lack permission. Once the private repo exists, installation via `uv tool install git+https://github.com/weskao/vidpress.git` requires your git credentials to access it. **The remote URL is not live until created and verified.**

### Security

No media is uploaded to an external service: normal encoding uses local FFmpeg, and VMAF sampling uses local ab-av1. FFmpeg/FFprobe processes read local filenames only. Use trusted video inputs; keep FFmpeg updated. Video filenames/paths appear in optional reports, so treat those as potentially sensitive. Dependency installation via Homebrew is initiated only on explicit request/consent.

## Credits

Built on [FFmpeg](https://ffmpeg.org/), [uv](https://docs.astral.sh/uv/), [Rich](https://github.com/Textualize/rich) and optional [ab-av1](https://github.com/alexheretic/ab-av1). MIT licensed (see [LICENSE](LICENSE)); third-party tools retain their own licenses.
