#!/usr/bin/env python3
"""Allowlisted release archives; private runtime folders cannot enter assets."""
import hashlib
from pathlib import Path
import tarfile
import zipfile
from check_package import ROOT, files, main as check

VERSION='0.1.0'
PREFIX='wechat-chat-assistant-v'+VERSION


def main():
    check()
    out=ROOT/'dist';out.mkdir(exist_ok=True)
    paths=files()
    tgz=out/(PREFIX+'.tgz');zip_path=out/(PREFIX+'.zip')
    with tarfile.open(tgz,'w:gz') as archive:
        for p in paths:
            info=archive.gettarinfo(str(p),arcname=PREFIX+'/'+str(p.relative_to(ROOT)))
            info.uid=info.gid=0
            info.uname=info.gname=''
            with p.open('rb') as stream:archive.addfile(info,stream)
    with zipfile.ZipFile(zip_path,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for p in paths:archive.write(p,arcname=PREFIX+'/'+str(p.relative_to(ROOT)))
    digest=hashlib.sha256(tgz.read_bytes()).hexdigest()
    bootstrap=out/'install.sh'
    bootstrap.write_text('''#!/bin/bash
set -euo pipefail
base="${WECHAT_ASSISTANT_HOME:-$HOME/.local/share/wechat-chat-assistant}"
target="$base/packages/VERSION"
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then echo '此Beta仅支持Apple Silicon Mac。'; exit 1; fi
if [[ -e "$target" ]]; then echo "固定版本目录已存在，重新打开：$target/Install.command"; exit 1; fi
umask 077
mkdir -p "$base/packages"
tmp="$(mktemp -d)"
trap 'rm -f "$tmp/package.tgz"; rmdir "$tmp" 2>/dev/null || true' EXIT
curl -fL 'https://github.com/xanthiawang/wechat-chat-assistant/releases/download/vVERSION/wechat-chat-assistant-vVERSION.tgz' -o "$tmp/package.tgz"
actual="$(shasum -a 256 "$tmp/package.tgz" | cut -d ' ' -f 1)"
[[ "$actual" == DIGEST ]] || { echo 'SHA256校验失败，未执行安装。'; exit 1; }
# Refuse unsafe archive members before extraction.
tar -tzf "$tmp/package.tgz" | while IFS= read -r member; do
  [[ "$member" == wechat-chat-assistant-vVERSION/* && "$member" != *../* ]] || exit 1
done
tar -xzf "$tmp/package.tgz" -C "$tmp"
mv "$tmp/wechat-chat-assistant-vVERSION" "$target"
exec /bin/bash "$target/Install.command"
'''.replace('VERSION',VERSION).replace('DIGEST',digest))
    bootstrap.chmod(0o755)
    sums=''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in [tgz,zip_path,bootstrap])
    (out/'SHA256SUMS').write_text(sums)
    print(sums)


if __name__=='__main__':main()
