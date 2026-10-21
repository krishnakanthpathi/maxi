# Release preparation

For v0.3.0-beta.1, Python uses PEP 440 version `0.3.0b1`, while the Git tag and macOS archive use `v0.3.0-beta.1`. `app/__init__.py` supplies the Python, CLI, and API version; Hatch reads the same value.

Before publication:

1. Run `python -m pytest -q` and `bash scripts/test_macos_hud.sh` on macOS.
2. Run `uv build` to create the wheel and source distribution.
3. Run `bash scripts/package_macos.sh` to build the native companion for the host architecture.
4. Run `python3 scripts/verify_release.py` to check required source/assets, exclude private runtime files, and write `dist/SHA256SUMS`.
5. Smoke-test the wheel's installed layout and `maxi --version` outside the source checkout.
6. Commit the reviewed source, push it, and create prerelease tag `v0.3.0-beta.1` with `releases/v0.3.0-beta.1.md` as the release notes. Upload only this release's wheel, sdist, macOS companion, and checksums.

The app is a companion to the Python daemon and is not Developer ID signed or notarized. Do not describe it as a standalone, notarized download. Do not claim automatic memory injection, wake-word listening, a Windows GUI, or a Linux GUI. Never upload `.env`, `.maxi/mcp_config.json`, history, pairing codes, databases, or local model files.

## Combined macOS installer

Run `bash scripts/package_macos_installer.sh` after building the wheel. This
builds a universal Swift HUD and native launcher, generates the ∑ ICNS asset,
and packages a ZIP and DMG. The app bundles the wheel and online setup script;
Python is installed on first setup when needed, rather than included offline.
Both the app and mounted disk must have the icon. The app is ad-hoc signed for
bundle integrity, not Developer ID signed or notarized.

Run `python3 scripts/verify_release.py` again to verify the combined bundle and
include all new assets in `SHA256SUMS`. Upload these additional artifacts:

- `Maxi-0.3.0-beta.1-macos-universal.dmg`
- `Maxi-0.3.0-beta.1-macos-universal.zip`
- `install-macos.sh`

When adding installer packaging to the existing beta, preserve the original
wheel, sdist, and companion ZIP. Replace only the checksum manifest and release
description, and add the new installer files. Publish the installer assets
before pushing website links that depend on them.

Verify a clean install with `--no-configure --no-launch` and isolated
`MAXI_INSTALL_DIR`, `MAXI_APPS_DIR`, and `MAXI_BIN_DIR`. Force
`UV_MANAGED_PYTHON=1` during this check to exercise the runtime download. Check
the installed backend from outside the source checkout, without contacting any
personal providers or opening microphone/shortcut listeners. Apple Silicon is
tested on this build host; validate the Intel binary on an Intel Mac before
claiming runtime testing there.

An authenticated GitHub CLI can publish with:

```bash
gh release create v0.3.0-beta.1 --prerelease \
  --title '∑ Maxi v0.3.0-beta.1' \
  --notes-file releases/v0.3.0-beta.1.md \
  dist/maxi_ai-0.3.0b1-py3-none-any.whl \
  dist/maxi_ai-0.3.0b1.tar.gz \
  dist/MaxiHUD-0.3.0-beta.1-macos-arm64.zip \
  dist/SHA256SUMS
```
