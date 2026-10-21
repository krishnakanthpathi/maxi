"""Verify sanitized beta distributions and write the release checksums."""
from pathlib import Path
import hashlib
import plistlib
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'
WHEEL = DIST / 'maxi_ai-0.3.0b1-py3-none-any.whl'
SDIST = DIST / 'maxi_ai-0.3.0b1.tar.gz'
MAC = DIST / 'MaxiHUD-0.3.0-beta.1-macos-arm64.zip'
INSTALLER_ZIP = DIST / 'Maxi-0.3.0-beta.1-macos-universal.zip'
INSTALLER_DMG = DIST / 'Maxi-0.3.0-beta.1-macos-universal.dmg'
INSTALLER_SH = DIST / 'install-macos.sh'


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
artifacts = [WHEEL, SDIST, MAC]
if any(path.exists() for path in [INSTALLER_ZIP, INSTALLER_DMG, INSTALLER_SH]):
    assert all(path.is_file() for path in [INSTALLER_ZIP, INSTALLER_DMG, INSTALLER_SH]), 'Build the complete macOS installer set'
    with zipfile.ZipFile(INSTALLER_ZIP) as archive:
        names = archive.namelist()
        safe(names)
        base = 'Maxi.app/Contents/'
        info = plistlib.loads(archive.read(base + 'Info.plist'))
        assert info['CFBundleExecutable'] == 'MaxiHUD'
        assert info['CFBundleIconFile'] == 'Maxi.icns'
        assert archive.read(base + 'Resources/Maxi.icns').startswith(b'icns')
        assert base + 'MacOS/MaxiHUD' in names
        assert base + 'MacOS/MaxiLauncher' not in names
        assert base + 'Resources/Install Maxi.command' in names
        assert archive.read(base + 'Resources/install_macos.sh') == INSTALLER_SH.read_bytes()
        assert archive.read(base + 'Resources/' + WHEEL.name) == WHEEL.read_bytes()
        assert archive.read(base + 'Resources/default.env') == (ROOT / '.env.example').read_bytes()
    artifacts.extend([INSTALLER_ZIP, INSTALLER_DMG, INSTALLER_SH])
    assert INSTALLER_SH.read_bytes() == (ROOT / 'scripts/install_macos.sh').read_bytes()
    print('PASS: combined app includes native startup, backend wheel, setup script, and icon')
lines = [f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}' for path in artifacts]
(DIST / 'SHA256SUMS').write_text('\n'.join(lines) + '\n')
print('PASS: wheel, source archive, and macOS companion are sanitized and complete')
print('Wrote', DIST / 'SHA256SUMS')
