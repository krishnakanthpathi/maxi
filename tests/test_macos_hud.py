from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("swiftc"), reason="Requires macOS and Swift")
def test_result_images_use_returned_paths(tmp_path):
    """Exercise real HUD state without launching the app or needing XCTest."""
    root = Path(__file__).resolve().parents[1]
    sources = root / "frontends/macos/Sources/MaxiHUD"
    binary = tmp_path / "hud_checks"
    compile_result = subprocess.run(
        [
            "swiftc", str(sources / "AppState.swift"), str(sources / "ResultImage.swift"),
            str(root / "tests/macos/ResultImageCheck.swift"), "-o", str(binary),
        ],
        capture_output=True, text=True, timeout=60,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
