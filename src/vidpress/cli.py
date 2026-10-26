"""Rich TUI and command-line entry point for vidpress."""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.prompt import Confirm, Prompt
from rich.table import Table

from .engine import (
    CODECS,
    PRESETS,
    Options,
    choose_jobs,
    collect_inputs,
    encode_one,
    plan_destination,
    probe_file,
    validate_options,
    write_report,
)

console = Console()


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='vidpress', description='Colorful batch video compression powered by FFmpeg')
    p.add_argument('--version', action='version', version='vidpress 0.1.0')
    sub = p.add_subparsers(dest='command')
    parser = sub.add_parser('compress', help='Compress one or more videos or folders')
    parser.add_argument('inputs', nargs='+', type=Path)
    parser.add_argument('-o', '--output', type=Path, default=Path('compressed'))
    parser.add_argument('-c', '--codec', choices=list(CODECS), default='h265')
    parser.add_argument('-q', '--quality', choices=list(PRESETS), default='balanced')
    parser.add_argument('--crf', type=float)
    parser.add_argument('--preset')
    parser.add_argument('--resolution', type=int, help='Maximum output height (e.g. 720 or 1080)')
    parser.add_argument('--target-size', type=float, metavar='MB', help='Approximate MB per video, one-pass ABR')
    parser.add_argument('--audio', choices=['aac', 'copy', 'none'], default='aac')
    parser.add_argument('--subtitles', choices=['none', 'copy'], default='none')
    parser.add_argument('--preserve-audio', action='store_const', const='copy', dest='audio', help='Alias for --audio copy')
    parser.add_argument('--preserve-subtitles', action='store_const', const='copy', dest='subtitles', help='Alias for --subtitles copy (MKV output)')
    parser.add_argument('--hdr', choices=['auto', 'preserve', 'sdr'], default='auto')
    parser.add_argument('--auto-vmaf', type=float, metavar='SCORE', help='Use ab-av1 to find software codec CRF at target VMAF')
    parser.add_argument('--jobs', default='auto', help='Concurrent videos: auto, 1, 2, ...')
    parser.add_argument('-r', '--recursive', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--skip-if-larger', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--install-missing', action='store_true', help='Allow Homebrew/winget dependency setup')
    parser.add_argument('--report', type=Path, help='Write .json or .csv compression report')
    parser.add_argument('-y', '--yes', action='store_true', help='Run without confirmation')
    sub.add_parser('interactive', help='Colorful guided setup')
    doctor = sub.add_parser('doctor', help='Inspect FFmpeg/encoders and optional VMAF tool')
    doctor.add_argument('--install', action='store_true', help='Install missing prerequisites using Homebrew/winget (with confirmation)')
    inspect = sub.add_parser('inspect', help='Inspect video metadata')
    inspect.add_argument('inputs', nargs='+', type=Path)
    sub.add_parser('presets', help='Show quality presets')
    return p


def _install_package(package: str, auto: bool) -> bool:
    system = platform.system()
    if system == 'Darwin':
        manager = 'brew'
        command = ['brew', 'install', package]
    elif system == 'Windows':
        if package == 'ffmpeg':
            manager = 'winget'
            command = ['winget', 'install', '--id', 'Gyan.FFmpeg', '-e',
                       '--accept-source-agreements', '--accept-package-agreements']
        elif package == 'ab-av1':
            manager = 'cargo'
            command = ['cargo', 'install', 'ab-av1']
        else:
            return False
    else:
        console.print('[yellow]Install FFmpeg with your OS package manager and run doctor again.[/yellow]')
        return False
    if not shutil.which(manager):
        console.print(f'[yellow]{manager} is required to install {package} on {system}.[/yellow]')
        return False
    if not auto and (not sys.stdin.isatty() or not Confirm.ask(f'Install {package} via {manager}?', default=False)):
        return False
    console.print(f'[cyan]Installing {package} using {manager}...[/cyan]')
    done = subprocess.run(command, check=False).returncode == 0
    if done and system == 'Windows':
        console.print('[yellow]If FFmpeg is not found yet, restart your Terminal to refresh PATH.[/yellow]')
    return done


def ensure_deps(codec: str = 'h265', vmaf: bool = False, install: bool = False) -> bool:
    required = ['ffmpeg', 'ffprobe']
    if vmaf:
        required.append('ab-av1')
    missing = [name for name in required if not shutil.which(name)]
    if missing:
        console.print('[yellow]Missing: ' + ', '.join(missing) + '[/yellow]')
        if ('ffmpeg' in missing or 'ffprobe' in missing) and _install_package('ffmpeg', install):
            missing = [v for v in missing if v not in ('ffmpeg', 'ffprobe')]
        if 'ab-av1' in missing and _install_package('ab-av1', install):
            missing.remove('ab-av1')
        # Check PATH again rather than assuming installations worked.
        missing = [name for name in required if not shutil.which(name)]
        if missing:
            console.print('[red]Still missing: ' + ', '.join(missing) + '[/red]')
            return False
    result = subprocess.run(['ffmpeg', '-hide_banner', '-encoders'], capture_output=True, text=True, check=False)
    encoder = CODECS[codec]
    if result.returncode or encoder not in result.stdout:
        console.print(f'[red]FFmpeg does not support {encoder}.[/red]')
        return False
    if vmaf:
        filters = subprocess.run(['ffmpeg', '-hide_banner', '-filters'], capture_output=True, text=True, check=False)
        if 'libvmaf' not in filters.stdout:
            console.print('[red]ab-av1 requires an FFmpeg build with libvmaf.[/red]')
            return False
    return True


def doctor(install: bool = False) -> int:
    t = Table(title='🩺 Dependency doctor', box=box.ROUNDED)
    t.add_column('Component', style='bold cyan')
    t.add_column('Status')
    for program in ('uv', 'brew', 'ffmpeg', 'ffprobe', 'ab-av1'):
        available = shutil.which(program)
        t.add_row(program, f'[green]✓ {available}[/green]' if available else '[yellow]Not installed[/yellow]')
    console.print(t)
    ok = ensure_deps('h265', False, install)
    if shutil.which('ab-av1'):
        ensure_deps('av1', True, False)
    return 0 if ok else 1


def presets() -> None:
    t = Table(title='🎛 Quality profiles', box=box.ROUNDED)
    t.add_column('Profile', style='bold cyan')
    for codec in ('h264', 'h265', 'av1'):
        t.add_column(codec.upper())
    for mode, values in PRESETS.items():
        t.add_row(mode, *(str(values[c]) for c in ('h264', 'h265', 'av1')))
    console.print(t)
    console.print('[dim]CRF: lower = higher quality/larger size. Do not compare CRF between codecs.[/dim]')


def interactive() -> int:
    console.print(Panel.fit('[bold bright_cyan]🎬 VIDPRESS[/bold bright_cyan]\n[dim]Batch Video Compressor  ·  FFmpeg  ·  uv[/dim]', border_style='cyan'))
    while True:
        console.print('[bold]①[/bold] Compress videos   [bold]②[/bold] Inspect video   [bold]③[/bold] Presets   [bold]④[/bold] Doctor   [bold]⑤[/bold] Exit')
        choice = Prompt.ask('[cyan]Choose[/cyan]', choices=['1','2','3','4','5'], default='1')
        if choice == '5':
            return 0
        if choice == '3':
            presets()
            continue
        if choice == '4':
            doctor()
            continue
        if choice == '2':
            path = Path(Prompt.ask('Video path').strip().strip('"')).expanduser()
            return inspect_files([path])
        source = Path(Prompt.ask('Video file / folder').strip().strip('"')).expanduser()
        out = Path(Prompt.ask('Output folder', default='compressed')).expanduser()
        codec = Prompt.ask('Codec (H.265 balanced, AV1 smaller, H.264 compatible)', choices=list(CODECS), default='h265')
        quality = Prompt.ask('Quality', choices=list(PRESETS), default='balanced')
        custom = Confirm.ask('Customize advanced options?', default=False)
        args = make_parser().parse_args(['compress', str(source), '-o', str(out), '-c', codec, '-q', quality])
        if custom:
            args.recursive = Confirm.ask('Include subdirectories?', default=True)
            args.resolution = int(Prompt.ask('Max height (0=original)', default='0')) or None
            args.jobs = Prompt.ask('Parallel jobs', default='auto')
            args.audio = Prompt.ask('Audio policy', choices=['aac','copy','none'], default='aac')
            args.subtitles = Prompt.ask('Subtitles', choices=['none','copy'], default='none')
            args.hdr = Prompt.ask('HDR', choices=['auto','preserve','sdr'], default='auto')
            args.target_size = float(Prompt.ask('Approx target MB per video (0=CRF)', default='0')) or None
            if codec != 'hevc-vt' and not args.target_size:
                if Confirm.ask('Auto VMAF quality search? (slow)', default=False):
                    args.auto_vmaf = float(Prompt.ask('Minimum VMAF', default='95'))
            if not args.target_size and not args.auto_vmaf and codec != 'hevc-vt':
                args.crf = float(Prompt.ask('CRF (blank=profile)', default=str(PRESETS[quality][codec])))
        args.yes = False
        return compress(args)


def inspect_files(paths: list[Path]) -> int:
    result = 0
    for p in paths:
        try:
            d = probe_file(p)
            t = Table(title=str(p), box=box.ROUNDED)
            t.add_column('Property', style='cyan')
            t.add_column('Value')
            for key in ('width','height','duration','hdr','color_transfer','color_primaries','audio_bitrate'):
                t.add_row(key, str(d.get(key)))
            console.print(t)
        except Exception as e:
            console.print(f'[red]{e}[/red]')
            result = 1
    return result


def compress(args: argparse.Namespace) -> int:
    opt = Options(codec=args.codec, quality=args.quality, crf=args.crf, preset=args.preset,
                  resolution=args.resolution, target_size_mb=args.target_size,
                  audio=args.audio, subtitles=args.subtitles, hdr=args.hdr,
                  skip_if_larger=args.skip_if_larger, dry_run=args.dry_run, auto_vmaf=args.auto_vmaf)
    try:
        validate_options(opt)
        if args.jobs != 'auto' and int(args.jobs) < 1:
            raise ValueError('jobs must be >=1')
        paths = collect_inputs(args.inputs, args.output, args.recursive)
        if not paths:
            raise ValueError('No supported videos found (use --recursive for subdirectories)')
        output = args.output.expanduser().resolve()
        container = 'mkv' if opt.subtitles == 'copy' else 'mp4'
        tasks = []
        dest_set = set()
        for src in paths:
            owners = [p.expanduser().resolve() for p in args.inputs if src == p.expanduser().resolve() or
                      (p.expanduser().resolve().is_dir() and p.expanduser().resolve() in src.parents)]
            owner = max(owners, key=lambda p: len(p.parts))
            dest = plan_destination(src, output, owner, container)
            if dest in dest_set:
                raise ValueError(f'Output collision: {dest} (rename source files or select different roots)')
            dest_set.add(dest)
            tasks.append((src, dest))
        jobs = choose_jobs(len(tasks), args.jobs, os.cpu_count() or 2, opt.codec)
    except (ValueError, OSError) as e:
        console.print(f'[red]{e}[/red]')
        return 2
    table = Table(title='📦 Compression plan', box=box.ROUNDED)
    table.add_column('Files', style='cyan')
    table.add_column('Codec')
    table.add_column('Quality')
    table.add_column('Jobs')
    table.add_column('Output')
    table.add_row(str(len(tasks)), args.codec, f'{args.quality}'+(' / VMAF' if opt.auto_vmaf else ''), str(jobs), str(output))
    console.print(table)
    if not opt.dry_run and not args.yes and sys.stdin.isatty() and not Confirm.ask('Start encoding?', default=True):
        return 0
    if not opt.dry_run and not ensure_deps(args.codec, opt.auto_vmaf is not None, args.install_missing):
        return 2
    if opt.dry_run and not shutil.which('ffprobe'):
        console.print('[yellow]Dry-run requires ffprobe for source metadata.[/yellow]')
        return 2
    rows = []
    with Progress(SpinnerColumn(), TextColumn('[bold blue]{task.description}'),
                  BarColumn(), TaskProgressColumn(), TimeElapsedColumn(), console=console, transient=False) as progress:
        progress_ids = {src: progress.add_task(src.name, total=100) for src, _ in tasks}
        def work(src: Path, dst: Path):
            return encode_one(src, dst, opt, threads=max(1, (os.cpu_count() or 2)//jobs),
                              progress=lambda n: progress.update(progress_ids[src], completed=n))
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            futures = {pool.submit(work, s, d): s for s,d in tasks}
            for fut in as_completed(futures):
                row = fut.result()
                progress.update(progress_ids[futures[fut]], completed=100,
                                description=f'{futures[fut].name} [{row["status"]}]')
                rows.append(row)
    rows.sort(key=lambda r:r['input'])
    summary = Table(title='📊 Compression results', box=box.ROUNDED)
    summary.add_column('File', style='cyan')
    summary.add_column('Status')
    summary.add_column('Saved')
    summary.add_column('Output')
    for row in rows:
        color = 'green' if row['status']=='ok' else 'yellow' if row['status'] != 'failed' else 'red'
        summary.add_row(Path(row['input']).name,f'[{color}]{row["status"]}[/{color}]',
                        f'{row["saved_percent"]:.1f}%',row['output'])
        if row['error']:
            console.print(f'[red]{Path(row["input"]).name}: {row["error"]}[/red]')
    console.print(summary)
    if args.report:
        try:
            write_report(rows, args.report)
            console.print(f'[green]Report: {args.report}[/green]')
        except Exception as e:
            console.print(f'[red]Report failed: {e}[/red]')
            return 1
    return 1 if any(r['status']=='failed' for r in rows) else 0


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    if args.command is None or args.command == 'interactive':
        if not sys.stdin.isatty():
            make_parser().print_help()
            return 2
        return interactive()
    if args.command == 'doctor':
        return doctor(args.install)
    if args.command == 'presets':
        presets()
        return 0
    if args.command == 'inspect':
        return inspect_files(args.inputs)
    return compress(args)
