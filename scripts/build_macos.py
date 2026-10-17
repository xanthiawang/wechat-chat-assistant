#!/usr/bin/env python3
"""Build an unsigned native setup launcher; only allowlisted public source is bundled."""
import json
import plistlib
from pathlib import Path
import shutil
import subprocess
import tempfile
from check_package import ROOT, files, main as check


def main():
    check()
    version=json.loads((ROOT/'package.json').read_text())['version']
    out=ROOT/'dist';out.mkdir(exist_ok=True)
    target=out/f'WeChat-Chat-Assistant-{version}-arm64.app'
    if target.exists():raise RuntimeError('Build already exists; retain or move it before rebuilding: '+str(target))
    with tempfile.TemporaryDirectory(prefix='wechat-build-',dir=out) as temporary:
        app=Path(temporary)/target.name
        executable=app/'Contents/MacOS/WeChatAssistant'
        resources=app/'Contents/Resources/package'
        executable.parent.mkdir(parents=True);resources.mkdir(parents=True)
        for source in files():
            dest=resources/source.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
        subprocess.run(['xcrun','swiftc','-swift-version','5','-parse-as-library','-O','-target','arm64-apple-macosx14.0',
            str(ROOT/'native/AssistantApp.swift'),'-o',str(executable)],check=True)
        info={'CFBundleIdentifier':'com.zixinwang.wechat-chat-assistant','CFBundleName':'WeChat Chat Assistant',
            'CFBundleDisplayName':'微信聊天助手','CFBundleExecutable':'WeChatAssistant','CFBundlePackageType':'APPL',
            'CFBundleShortVersionString':version,'CFBundleVersion':version,'LSMinimumSystemVersion':'14.0',
            'NSHighResolutionCapable':True,'NSPrincipalClass':'NSApplication','LSApplicationCategoryType':'public.app-category.utilities'}
        (app/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
        subprocess.run(['codesign','--force','--deep','--sign','-',str(app)],check=True)
        app.rename(target)
    zipped=out/f'WeChat-Chat-Assistant-{version}-arm64.app.zip'
    subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(target),str(zipped)],check=True)
    dmg=out/f'WeChat-Chat-Assistant-{version}-arm64.dmg'
    with tempfile.TemporaryDirectory(prefix='wechat-dmg-',dir=out) as temporary:
        stage=Path(temporary);shutil.copytree(target,stage/'微信聊天助手.app')
        (stage/'Applications').symlink_to('/Applications')
        subprocess.run(['hdiutil','create','-volname','微信聊天助手','-srcfolder',str(stage),'-format','UDZO',str(dmg)],check=True)
    subprocess.run(['codesign','--verify','--deep','--strict',str(target)],check=True)
    print('Built ad-hoc signed, NOT notarized launcher:',target.name)
    print(zipped.name);print(dmg.name)


if __name__=='__main__':main()
