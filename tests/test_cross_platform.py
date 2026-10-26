"""Windows/macOS portability regression tests."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from vidpress.engine import Options, encode_one


def test_filesystem_without_hardlinks_still_saves_encoded_video(monkeypatch, tmp_path):
    import vidpress.engine as e
    src = tmp_path / 'in.mp4'
    src.write_bytes(b'original' * 4)
    dst = tmp_path / 'out' / 'in.mp4'
    dst.parent.mkdir()
    monkeypatch.setattr(e, 'probe_file', lambda _: {'duration': 1, 'hdr': False, 'height': 360, 'width': 640, 'audio_bitrate': 128000})
    monkeypatch.setattr(e, 'run_encode', lambda cmd, duration, progress=None: Path(cmd[-1]).write_bytes(b'new encoded video'))
    monkeypatch.setattr(e.os, 'link', lambda *_: (_ for _ in ()).throw(OSError('hardlinks unsupported')))
    result = encode_one(src, dst, Options(skip_if_larger=False), threads=1)
    assert result['status'] == 'ok', result['error']
    assert dst.read_bytes() == b'new encoded video'
    assert src.read_bytes() == b'original' * 4


def test_fallback_copy_does_not_overwrite_racing_output(monkeypatch, tmp_path):
    import vidpress.engine as e
    src = tmp_path / 'in.mp4'
    src.write_bytes(b'original' * 4)
    dst = tmp_path / 'out' / 'in.mp4'
    dst.parent.mkdir()
    monkeypatch.setattr(e, 'probe_file', lambda _: {'duration': 1, 'hdr': False, 'height': 360, 'width': 640, 'audio_bitrate': 128000})
    def racing_encode(cmd, duration, progress=None):
        Path(cmd[-1]).write_bytes(b'encoded')
        dst.write_bytes(b'existing')
    monkeypatch.setattr(e, 'run_encode', racing_encode)
    monkeypatch.setattr(e.os, 'link', lambda *_: (_ for _ in ()).throw(OSError('hardlinks unsupported')))
    result = encode_one(src, dst, Options(skip_if_larger=False), threads=1)
    assert result['status'] == 'exists-skipped'
    assert dst.read_bytes() == b'existing'


def test_hevc_videotoolbox_rejected_outside_macos(monkeypatch):
    import vidpress.engine as e
    monkeypatch.setattr(e.sys, 'platform', 'win32')
    with pytest.raises(ValueError, match='macOS'):
        e.validate_options(Options(codec='hevc-vt'))


def test_windows_installer_uses_winget_without_shell(monkeypatch):
    import vidpress.cli as cli
    calls = []
    monkeypatch.setattr(cli.platform, 'system', lambda: 'Windows')
    monkeypatch.setattr(cli.shutil, 'which', lambda name: '/bin' if name == 'winget' else None)
    monkeypatch.setattr(cli.subprocess, 'run', lambda argv, **kwargs: calls.append(argv) or SimpleNamespace(returncode=0))
    assert cli._install_package('ffmpeg', auto=True)
    assert calls == [['winget', 'install', '--id', 'Gyan.FFmpeg', '-e', '--accept-source-agreements', '--accept-package-agreements']]


def test_windows_without_winget_does_not_auto_install(monkeypatch):
    import vidpress.cli as cli
    monkeypatch.setattr(cli.platform, 'system', lambda: 'Windows')
    monkeypatch.setattr(cli.shutil, 'which', lambda _: None)
    assert not cli._install_package('ffmpeg', auto=True)
