from vidpress.cli import make_parser


def test_cli_options():
    args=make_parser().parse_args(['compress','a.mov','-o','out','-c','av1','-q','tiny','--jobs','4','--auto-vmaf','95','--recursive','--dry-run','--hdr','sdr','--skip-if-larger','--subtitles','copy','--audio','copy','--report','report.csv'])
    assert args.codec=='av1'
    assert args.auto_vmaf==95
    assert args.jobs=='4'
    assert args.hdr=='sdr'


def test_doctor_parses():
    assert make_parser().parse_args(['doctor','--install']).install


def test_preserve_aliases_are_supported():
    args = make_parser().parse_args(['compress', 'a.mov', '--preserve-audio', '--preserve-subtitles'])
    assert args.audio == 'copy'
    assert args.subtitles == 'copy'
