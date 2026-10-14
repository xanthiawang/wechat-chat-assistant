# Third-party components

## macOS WeChat read-only toolkit

Files in `app/vendor/` derive from:

- Source: https://gist.github.com/acmerfight/0a01249ef72970d07a2603dbb629e80f
- Pinned revision: `c98dbb10cf23c30e83d5d744905101b0880887a0`
- License: MIT, copyright 2026 Contributors. Full notice in `app/vendor/LICENSE`.
- `bootstrap_keys.py` and `capture_keys.py`: upstream source preserved.
- `sqlcipher_probe.py`: adapted to expose only the read-only interface; write
  flags and upstream generated-data self-tests removed. No upstream self-tests
  are run or distributed by this package.
- Shipped Python file hashes: `app/vendor/SHA256.json`.

## Runtime dependencies

Installed separately through npm, with exact root versions and registry
integrity hashes in `package-lock.json`:

- OpenClaw `2026.10.3`: https://github.com/openclaw/openclaw
- OpenClaw Codex runtime `2026.10.3`: distributed as `@openclaw/codex`
- Tencent Weixin channel `2.4.10`: https://github.com/Tencent/openclaw-weixin

Dependency licenses remain with those packages. They are not included in the
release archive. Homebrew supplies Python, Node and SQLCipher as prerequisites;
their versions follow Homebrew and are checked at installation where required.
This project is an independent integration, not an official WeChat or OpenAI product.
