"""Video planning, loss-safe encoding and reporting (no terminal UI)."""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

EXTENSIONS = {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v', '.mpg', '.mpeg', '.ts'}
PRESETS = {
    'high': {'h264': 18, 'h265': 21, 'av1': 27},
    'balanced': {'h264': 23, 'h265': 27, 'av1': 35},
    'small': {'h264': 28, 'h265': 30, 'av1': 40},
    'tiny': {'h264': 32, 'h265': 34, 'av1': 45},
}
CODECS = {'h264': 'libx264', 'h265': 'libx265', 'av1': 'libsvtav1', 'hevc-vt': 'hevc_videotoolbox'}
DEFAULT_PRESET = {'h264': 'slow', 'h265': 'slow', 'av1': '6'}
REPORT_FIELDS = ('input', 'output', 'status', 'codec', 'crf', 'input_bytes', 'output_bytes', 'saved_percent', 'error')
HDR_TRANSFERS = {'smpte2084', 'arib-std-b67'}


@dataclass(frozen=True)
class Options:
    codec: str = 'h265'
    quality: str = 'balanced'
    crf: float | None = None
    preset: str | None = None
    resolution: int | None = None
    target_size_mb: float | None = None
    audio: str = 'aac'        # aac, copy, none
    subtitles: str = 'none'   # none, copy
    hdr: str = 'auto'         # auto, preserve, sdr
    skip_if_larger: bool = True
    dry_run: bool = False
    auto_vmaf: float | None = None


def choose_jobs(count: int, requested: str | int, cpu: int, codec: str) -> int:
    if requested != 'auto':
        count_jobs = int(requested)
        if count_jobs < 1:
            raise ValueError('jobs must be >= 1')
        return min(count, count_jobs)
    # Leave enough encoder threads for each job; AV1 is particularly CPU-hungry.
    return max(1, min(count, 2 if codec == 'av1' else 3, max(1, cpu // 4)))


def collect_inputs(paths: list[Path], output: Path, recursive: bool = False) -> list[Path]:
    found: set[Path] = set()
    out = output.resolve()
    for given in paths:
        path = given.expanduser().resolve()
        if path.is_file():
            if path.suffix.lower() in EXTENSIONS and path != out:
                found.add(path)
        elif path.is_dir():
            iterator = path.rglob('*') if recursive else path.iterdir()
            for candidate in iterator:
                if (candidate.is_file() and candidate.suffix.lower() in EXTENSIONS
                    and not any(part.startswith('.') for part in candidate.relative_to(path).parts)
                    and candidate.resolve() != out
                    and out not in candidate.resolve().parents):
                    found.add(candidate.resolve())
        else:
            raise ValueError(f'Input not found: {given}')
    return sorted(found)


def plan_destination(source: Path, output: Path, root: Path, container: str) -> Path:
    """Preserve the name of each input directory to avoid flattening collisions."""
    base = root.resolve()
    src = source.resolve()
    rel = (Path(base.name) / src.relative_to(base)) if base.is_dir() else Path(src.name)
    return output / rel.with_suffix(f'.{container}')


def validate_options(options: Options, media: dict | None = None) -> None:
    if options.codec not in CODECS or options.quality not in PRESETS:
        raise ValueError('Unknown codec or quality')
    if options.crf is not None and not (0 <= options.crf <= (63 if options.codec == 'av1' else 51)):
        raise ValueError('CRF out of codec range')
    if options.audio not in ('aac', 'copy', 'none') or options.subtitles not in ('none', 'copy'):
        raise ValueError('Unsupported audio/subtitle policy')
    if options.hdr not in ('auto', 'preserve', 'sdr'):
        raise ValueError('Unknown HDR setting')
    if options.target_size_mb is not None and options.target_size_mb <= 0:
        raise ValueError('target size must be positive')
    if options.target_size_mb is not None and options.auto_vmaf is not None:
        raise ValueError('target size cannot be used with auto VMAF')
    if options.target_size_mb is not None and options.crf is not None:
        raise ValueError('target size cannot be used with CRF')
    if options.auto_vmaf is not None and options.crf is not None:
        raise ValueError('Automatic VMAF cannot be combined with manual CRF')
    if options.auto_vmaf is not None and not (0 < options.auto_vmaf <= 100):
        raise ValueError('VMAF must be in (0, 100]')
    if options.auto_vmaf is not None and options.codec == 'hevc-vt':
        raise ValueError('Automatic VMAF requires a software CRF-based codec')
    if options.auto_vmaf is not None and (options.resolution or options.hdr == 'sdr'):
        raise ValueError('Automatic VMAF does not support scaling or HDR tone mapping')
    if options.codec == 'hevc-vt' and (options.crf is not None or options.preset is not None):
        raise ValueError('VideoToolbox uses target bitrate, not CRF/preset')
    if media and media['hdr'] and options.hdr != 'sdr' and options.codec == 'h264':
        raise ValueError('Cannot preserve HDR/10-bit in H.264; choose H.265/AV1 or --hdr sdr')
    if options.resolution is not None and options.resolution < 144:
        raise ValueError('Output height must be >=144')


def probe_file(path: Path) -> dict:
    proc = subprocess.run([
        'ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)
    ], capture_output=True, text=True, check=False)
    if proc.returncode:
        raise RuntimeError(f'ffprobe failed for {path}: {proc.stderr.strip()}')
    data = json.loads(proc.stdout)
    videos = [s for s in data.get('streams', []) if s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic')]
    if not videos:
        raise ValueError(f'No video stream: {path}')
    v = videos[0]
    fmt = data.get('format', {})
    audios = [s for s in data.get('streams', []) if s.get('codec_type') == 'audio']
    duration = float(fmt.get('duration') or v.get('duration') or 0)
    if duration <= 0:
        raise ValueError(f'Cannot determine positive video duration: {path}')
    return {
        'duration': duration, 'width': int(v.get('width') or 0), 'height': int(v.get('height') or 0),
        'hdr': v.get('color_transfer') in HDR_TRANSFERS,
        'color_transfer': v.get('color_transfer'),
        'color_primaries': v.get('color_primaries'),
        'color_space': v.get('color_space'),
        'audio_bitrate': sum(int(s.get('bit_rate') or 128000) for s in audios),
    }


def video_bitrate(megabytes: float, media: dict, audio: str) -> int:
    # Reserve 4% for mux overhead/bitrate variation. One-pass ABR is approximate.
    total_bps = megabytes * 1_000_000 * 8 * .96 / media['duration']
    audio_bps = (media.get('audio_bitrate', 128000) if audio == 'copy'
                 else (128000 if audio == 'aac' else 0))
    available = int(total_bps - audio_bps)
    if available < 50000:
        raise ValueError('target size is too small for duration and audio budget')
    return available


def preset_for(options: Options) -> str | None:
    return options.preset or DEFAULT_PRESET.get(options.codec)


def encoder_command(source: Path, destination: Path, options: Options, media: dict,
                    crf: float | None, threads: int) -> list[str]:
    validate_options(options, media)
    hdr_input = media['hdr']
    hdr_preserve = hdr_input and options.hdr != 'sdr'
    cmd = ['ffmpeg', '-hide_banner', '-nostdin', '-y', '-loglevel', 'error', '-progress', 'pipe:1', '-nostats',
           '-i', str(source), '-map', '0:v:0']
    if options.audio != 'none':
        cmd += ['-map', '0:a?']
    if options.subtitles == 'copy':
        cmd += ['-map', '0:s?']
    cmd += ['-map_metadata', '0', '-map_chapters', '0', '-c:v', CODECS[options.codec]]
    if options.codec == 'hevc-vt':
        if options.target_size_mb is not None:
            bitrate = video_bitrate(options.target_size_mb, media, options.audio)
        else:
            original_bitrate = max(300000, int(source.stat().st_size * 8 / media['duration']))
            factor = {'high': .85, 'balanced': .65, 'small': .45, 'tiny': .30}[options.quality]
            bitrate = int(original_bitrate * factor)
        cmd += ['-b:v', str(bitrate)]
    elif options.target_size_mb is not None:
        cmd += ['-b:v', str(video_bitrate(options.target_size_mb, media, options.audio))]
    else:
        cmd += ['-crf', str(crf if crf is not None else options.crf if options.crf is not None else PRESETS[options.quality][options.codec])]
    preset = preset_for(options)
    if preset:
        cmd += ['-preset', preset]
    cmd += ['-threads', str(max(1, threads))]
    filters = []
    if hdr_input and options.hdr == 'sdr':
        filters.append('zscale=t=linear:npl=100,format=gbrpf32le,tonemap=hable,zscale=t=bt709:m=bt709:p=bt709:r=tv,format=yuv420p')
    if options.resolution is not None and media['height'] > options.resolution:
        filters.append(f'scale=-2:{options.resolution}')
    if filters:
        cmd += ['-vf', ','.join(filters)]
    if hdr_preserve:
        if options.codec == 'hevc-vt':
            cmd += ['-pix_fmt', 'p010le', '-profile:v', 'main10']
        else:
            cmd += ['-pix_fmt', 'yuv420p10le']
        color_fields = [('color_transfer', '-color_trc'), ('color_primaries', '-color_primaries'), ('color_space', '-colorspace')]
        for key, flag in color_fields:
            value = media.get(key)
            if value and re.fullmatch(r'[A-Za-z0-9_-]+', value):
                cmd += [flag, value]
    elif options.codec != 'hevc-vt':
        cmd += ['-pix_fmt', 'yuv420p']
    if hdr_input and options.hdr == 'sdr':
        cmd += ['-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709']
    if options.codec in ('h265', 'hevc-vt'):
        cmd += ['-tag:v', 'hvc1'] if destination.suffix == '.mp4' else []
    if options.audio == 'aac':
        cmd += ['-c:a', 'aac', '-b:a', '128k']
    elif options.audio == 'copy':
        cmd += ['-c:a', 'copy']
    if options.subtitles == 'copy':
        cmd += ['-c:s', 'copy']
    if destination.suffix == '.mp4':
        cmd += ['-movflags', '+faststart']
    cmd.append(str(destination))
    return cmd


def parse_vmaf_result(output: str) -> float:
    for line in reversed(output.splitlines()):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get('type') == 'crf-search-done':
            return float(item['crf'])
    raise ValueError('ab-av1 could not find a CRF satisfying minimum VMAF')


def search_vmaf(source: Path, options: Options) -> float:
    proc = subprocess.run([
        'ab-av1', 'crf-search', '-i', str(source), '--encoder', CODECS[options.codec],
        '--preset', preset_for(options) or '6',
        '--min-vmaf', str(options.auto_vmaf), '--stdout-format', 'json',
    ], capture_output=True, text=True, check=False)
    if proc.returncode:
        raise RuntimeError(f'ab-av1 CRF search failed: {proc.stderr[-800:].strip()}')
    return parse_vmaf_result(proc.stdout)


def run_encode(command: list[str], duration: float, progress: Callable[[float], None] | None = None) -> None:
    # ffmpeg stdout is -progress data, stderr only errors. Drain both without large buffers.
    with tempfile.TemporaryFile(mode='w+t') as errors:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors, text=True)
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                if progress and line.startswith('out_time='):
                    clock = line.strip().partition('=')[2]
                    try:
                        hours, minutes, seconds = clock.split(':')
                        elapsed = int(hours)*3600 + int(minutes)*60 + float(seconds)
                        progress(min(100.0, max(0.0, elapsed / duration * 100)))
                    except (ValueError, ZeroDivisionError):
                        pass
            code = proc.wait()
        except BaseException:
            proc.terminate()
            proc.wait()
            raise
        if code:
            errors.seek(0)
            raise RuntimeError(f'FFmpeg exited {code}: {errors.read()[-1200:].strip()}')
    if progress:
        progress(100.0)


def encode_one(source: Path, destination: Path, options: Options, threads: int,
               progress: Callable[[float], None] | None = None) -> dict:
    row = {'input': str(source), 'output': str(destination), 'status': 'failed', 'codec': options.codec,
           'crf': '', 'input_bytes': source.stat().st_size, 'output_bytes': 0, 'saved_percent': 0.0, 'error': ''}
    temp = None
    try:
        if source.resolve() == destination.resolve():
            raise ValueError('Output would overwrite input; select a different output directory')
        if destination.exists():
            row['status'] = 'exists-skipped'
            return row
        media = probe_file(source)
        validate_options(options, media)
        if options.subtitles == 'copy' and destination.suffix != '.mkv':
            raise ValueError('Copy subtitles requires MKV container')
        if options.dry_run:
            row['status'] = 'dry-run'
            return row
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_name(f'.{destination.stem}.{uuid4().hex}.partial{destination.suffix}')
        crf = search_vmaf(source, options) if options.auto_vmaf is not None else options.crf
        row['crf'] = str(crf if crf is not None else PRESETS[options.quality].get(options.codec, '-'))
        command = encoder_command(source, temp, options, media, crf, threads)
        run_encode(command, media['duration'], progress)
        output_media = probe_file(temp)
        if abs(output_media['duration'] - media['duration']) > max(1.0, media['duration'] * .025):
            raise RuntimeError('Output duration differs from input (incomplete encode)')
        row['output_bytes'] = temp.stat().st_size
        row['saved_percent'] = round((1 - row['output_bytes'] / max(1, row['input_bytes'])) * 100, 2)
        if options.skip_if_larger and row['output_bytes'] >= row['input_bytes']:
            row['status'] = 'larger-skipped'
        else:
            # Reserve destination exclusively: never overwrite an output created by another job.
            try:
                os.link(temp, destination)
                row['status'] = 'ok'
            except FileExistsError:
                row['status'] = 'exists-skipped'
        return row
    except Exception as exc:
        row['error'] = str(exc)
        return row
    finally:
        if temp:
            temp.unlink(missing_ok=True)


def write_report(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == '.json':
        path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding='utf-8')
    elif path.suffix.lower() == '.csv':
        with path.open('w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=REPORT_FIELDS, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
    else:
        raise ValueError('Report must be .json or .csv')
