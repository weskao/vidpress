import shutil
import subprocess

import pytest

from vidpress.engine import Options, encode_one


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='needs FFmpeg')
def test_unicode_paths_and_end_to_end_encoding(tmp_path):
    input_video = tmp_path / '中文 檔案.mp4'
    proc = subprocess.run([
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=128x96:rate=8',
        '-t', '1.25', '-c:v', 'mpeg4', '-q:v', '2', '-y', str(input_video)
    ], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    original_size = input_video.stat().st_size
    out = tmp_path / 'compressed' / '中文 檔案.mp4'
    res = encode_one(input_video, out, Options(codec='h264', crf=25, preset='ultrafast', skip_if_larger=False), 2)
    assert res['status'] == 'ok', res['error']
    assert out.is_file() and out.stat().st_size > 0
    assert input_video.stat().st_size == original_size
    res_again = encode_one(input_video, out, Options(codec='h264'), 2)
    assert res_again['status'] == 'exists-skipped'


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='needs FFmpeg')
def test_cli_parallel_compression_smoke(tmp_path):
    from vidpress.cli import main

    inputs = tmp_path/'source'
    inputs.mkdir()
    for index in range(2):
        r = subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi',
                            '-i',f'testsrc2=size=96x64:rate={8+index}', '-t','1', '-c:v','mpeg4',
                            '-y',str(inputs/f'影片 {index}.mp4')],capture_output=True,text=True)
        assert r.returncode == 0, r.stderr
    report = tmp_path/'report.json'
    result = main(['compress',str(inputs),'-o',str(tmp_path/'compressed'),'-c','h264',
                   '--preset','ultrafast','--no-skip-if-larger','--jobs','2','--report',str(report),'-y'])
    assert result == 0
    assert report.is_file()
    assert len(list((tmp_path/'compressed').rglob('*.mp4'))) == 2
