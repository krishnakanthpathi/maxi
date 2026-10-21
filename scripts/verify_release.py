"""Verify sanitized beta distributions and write the release checksums."""
from pathlib import Path
import hashlib
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'
WHEEL = DIST / 'maxi_ai-0.3.0b1-py3-none-any.whl'
SDIST = DIST / 'maxi_ai-0.3.0b1.tar.gz'
MAC = DIST / 'MaxiHUD-0.3.0-beta.1-macos-arm64.zip'


def safe(names):
    for name in names:
        path = Path(name)
        forbidden = {'.env', 'mcp_config.json', 'history.jsonl', 'qr.png', '.git', '.build', '__pycache__'}
        assert not forbidden.intersection(path.parts), f'Private/runtime path in release: {name}'
        assert not name.endswith(('.sqlite3', '.db', '.pid', '.log', '.pyc')), name


with zipfile.ZipFile(WHEEL) as archive:
    names = archive.namelist()
    safe(names)
    assert 'frontends/macos/Package.swift' in names
    assert 'frontends/macos/Sources/MaxiHUD/HUDView.swift' in names
    assert 'frontends/macos/Sources/MaxiHUD/GlassStyle.swift' in names
    assert 'app/sounds/minimal_wake.mp3' in names
    metadata = next(n for n in names if n.endswith('.dist-info/METADATA'))
    assert '\nVersion: 0.3.0b1\n' in archive.read(metadata).decode()
with tarfile.open(SDIST) as archive:
    names = archive.getnames()
    safe(names)
    assert any(n.endswith('/frontends/macos/Sources/MaxiHUD/HUDView.swift') for n in names)
    assert any(n.endswith('/LICENSE') for n in names)
with zipfile.ZipFile(MAC) as archive:
    names = archive.namelist()
    safe(names)
    assert 'Maxi.app/Contents/MacOS/MaxiHUD' in names
    assert 'Maxi.app/Contents/Info.plist' in names
    assert 'INSTALL.md' in names
lines = [f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}' for path in [WHEEL, SDIST, MAC]]
(DIST / 'SHA256SUMS').write_text('\n'.join(lines) + '\n')
print('PASS: wheel, source archive, and macOS companion are sanitized and complete')
print('Wrote', DIST / 'SHA256SUMS')
