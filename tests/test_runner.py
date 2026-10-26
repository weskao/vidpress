from pathlib import Path

from vidpress.engine import Options, encode_one, write_report


def test_skip_larger_deletes_temp_and_preserves_original(monkeypatch, tmp_path):
    import vidpress.engine as e
    src = tmp_path/'in.mp4'
    src.write_bytes(b'abc')
    dest = tmp_path/'out'/'in.mp4'
    monkeypatch.setattr(e, 'probe_file', lambda x:{'duration':1,'hdr':False,'height':360,'width':640,'audio_bitrate':128000})
    def fake_execute(cmd, duration, progress=None):
        Path(cmd[-1]).write_bytes(b'a'*80)
    monkeypatch.setattr(e, 'run_encode', fake_execute)
    result = encode_one(src,dest,Options(skip_if_larger=True),threads=1)
    assert result['status']=='larger-skipped'
    assert not dest.exists()
    assert src.read_bytes()==b'abc'
    assert not list(dest.parent.glob('.*partial*'))


def test_dry_run_does_not_create_files(monkeypatch,tmp_path):
    import vidpress.engine as e
    src = tmp_path/'source.mov'
    src.write_bytes(b'a')
    monkeypatch.setattr(e, 'probe_file', lambda x:{'duration':1,'hdr':False,'height':360,'width':640,'audio_bitrate':128000})
    result = encode_one(src,tmp_path/'out'/'source.mp4',Options(dry_run=True),threads=1)
    assert result['status']=='dry-run'
    assert not (tmp_path/'out').exists()


def test_existing_output_not_overwritten(monkeypatch,tmp_path):
    import vidpress.engine as e
    src=tmp_path/'src.mp4'
    src.write_bytes(b'1234')
    dst=tmp_path/'out.mp4'
    dst.write_bytes(b'existing')
    monkeypatch.setattr(e, 'probe_file', lambda x:{'duration':1,'hdr':False,'height':360,'width':640,'audio_bitrate':128000})
    res=encode_one(src,dst,Options(),threads=1)
    assert res['status']=='exists-skipped' and dst.read_bytes()==b'existing'


def test_report_csv_and_json(tmp_path):
    rows=[{'input':'a','output':'b','status':'ok','input_bytes':150,'output_bytes':100,'saved_percent':33.3,'error':''}]
    write_report(rows,tmp_path/'r.json')
    write_report(rows,tmp_path/'r.csv')
    assert '33.3' in (tmp_path/'r.csv').read_text()
    assert '"status": "ok"' in (tmp_path/'r.json').read_text()
