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
