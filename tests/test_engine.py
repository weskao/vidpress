import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from vidpress.engine import (
    Options,
    choose_jobs,
    collect_inputs,
    encoder_command,
    parse_vmaf_result,
    plan_destination,
    probe_file,
    validate_options,
    video_bitrate,
)


def test_presets_and_threads():
    assert choose_jobs(10, 'auto', 8, 'av1') == 2
    assert choose_jobs(10, 5, 8, 'h265') == 5
    assert choose_jobs(1, 'auto', 2, 'h265') == 1


def test_discover_recursive_skips_hidden_and_output(tmp_path):
    (tmp_path / 'a.mp4').write_bytes(b'a')
    (tmp_path / '.hidden.mp4').write_bytes(b'a')
    (tmp_path / 'nested').mkdir()
    (tmp_path / 'nested' / 'b.mov').write_bytes(b'b')
    (tmp_path / 'out').mkdir()
    (tmp_path / 'out' / 'old.mp4').write_bytes(b'old')
    inputs = collect_inputs([tmp_path], tmp_path / 'out', recursive=True)
    assert [p.name for p in inputs] == ['a.mp4', 'b.mov']
    assert len(collect_inputs([tmp_path], tmp_path / 'out', recursive=False)) == 1


def test_duplicate_stems_from_different_sources_keep_distinct_destination(tmp_path):
    (tmp_path / 'a').mkdir()
    (tmp_path / 'b').mkdir()
    a = tmp_path / 'a' / 'x.mp4'
    b = tmp_path / 'b' / 'x.mp4'
    assert plan_destination(a, tmp_path / 'output', tmp_path / 'a', 'mp4') != plan_destination(b, tmp_path / 'output', tmp_path / 'b', 'mp4')


def test_command_hdr_preserves_bit_depth_and_metadata():
    opt = Options(codec='h265', hdr='preserve', audio='copy', subtitles='copy')
    media = {'duration': 60, 'height': 2160, 'width': 3840, 'hdr': True, 'color_transfer': 'smpte2084', 'color_primaries': 'bt2020', 'color_space': 'bt2020nc', 'audio_bitrate': 128000}
    cmd = encoder_command(Path('input.mov'), Path('output.mkv'), opt, media, crf=27, threads=4)
    assert '-pix_fmt' in cmd and cmd[cmd.index('-pix_fmt')+1] == 'yuv420p10le'
    assert '-color_trc' in cmd and 'smpte2084' in cmd
    assert '-map' in cmd and '0:s?' in cmd
    assert '-c:a' in cmd and 'copy' in cmd


def test_target_size_and_scale():
    media = {'duration': 100, 'height': 1080, 'width': 1920, 'hdr': False, 'audio_bitrate': 96000}
    bps = video_bitrate(10, media, 'aac')
    assert 600000 < bps < 800000
    cmd = encoder_command(Path('a.mov'), Path('b.mp4'), Options(resolution=720, target_size_mb=10), media, 27, 2)
    assert '-b:v' in cmd and 'scale=' in ' '.join(cmd)
    assert '-crf' not in cmd


def test_reject_invalid_combinations():
    with pytest.raises(ValueError, match='software'):
        validate_options(Options(codec='hevc-vt', auto_vmaf=95))
    with pytest.raises(ValueError, match='10-bit'):
        validate_options(Options(codec='h264', hdr='preserve'), {'hdr': True})
    with pytest.raises(ValueError, match='target'):
        validate_options(Options(target_size_mb=5, auto_vmaf=95))
    with pytest.raises(ValueError, match='VMAF'):
        validate_options(Options(auto_vmaf=101))


def test_parse_vmaf_json_lines():
    output = '\n'.join([json.dumps({'type':'sample-encode-done','crf':23}),json.dumps({'type':'crf-search-done','crf':31.25,'vmaf':95.2})])
    assert parse_vmaf_result(output) == 31.25
    with pytest.raises(ValueError):
        parse_vmaf_result('{"type":"crf-search-error"}')


def test_probe_detects_hdr(monkeypatch):
    import vidpress.engine as e
    monkeypatch.setattr(e.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0,stdout=json.dumps({'format':{'duration':'11.2'},'streams':[{'codec_type':'video','width':1080,'height':1920,'color_transfer':'arib-std-b67'}, {'codec_type':'audio','bit_rate':'128000'}]}), stderr=''))
    p = probe_file(Path('anything.mp4'))
    assert p['hdr'] is True
    assert p['duration'] == 11.2


def test_hdr_sdr_emits_tone_mapping_and_bt709():
    media = {'duration':12, 'height':2160, 'width':3840, 'hdr': True,
             'color_transfer':'smpte2084', 'color_space':'bt2020nc',
             'color_primaries':'bt2020','audio_bitrate':128000}
    cmd = encoder_command(Path('a.mov'), Path('b.mp4'), Options(codec='h264', hdr='sdr'),media,24,2)
    assert 'tonemap=hable' in ' '.join(cmd)
    assert cmd[cmd.index('-color_trc')+1] == 'bt709'


def test_videotoolbox_hdr_requests_10_bit(tmp_path):
    source = tmp_path / "a.mov"
    source.write_bytes(b"0" * 2048)
    media = {'duration':12, 'height':2160, 'width':3840, 'hdr': True,
             'color_transfer':'smpte2084', 'color_space':'bt2020nc',
             'color_primaries':'bt2020','audio_bitrate':128000}
    cmd = encoder_command(source, tmp_path / 'b.mp4', Options(codec='hevc-vt'), media, None, 4)
    assert '-pix_fmt' in cmd
    assert cmd[cmd.index('-pix_fmt') + 1] == 'p010le'



def test_vmaf_accepts_all_software_codecs_and_passes_encoder_flag(monkeypatch):
    import vidpress.engine as e
    calls = []
    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout='{"type":"crf-search-done","crf":25.5}', stderr='')
    monkeypatch.setattr(e.subprocess, 'run', fake_run)
    for codec, expected in (('h264','libx264'), ('h265','libx265'), ('av1','libsvtav1')):
        e.validate_options(Options(codec=codec, auto_vmaf=95))
        assert e.search_vmaf(Path('my film.mp4'), Options(codec=codec, auto_vmaf=95)) == 25.5
        assert expected in calls[-1]


def test_vmaf_and_manual_crf_are_mutually_exclusive():
    with pytest.raises(ValueError, match='CRF'):
        validate_options(Options(codec='h265', auto_vmaf=95, crf=23))
