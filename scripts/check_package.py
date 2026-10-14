#!/usr/bin/env python3
"""Static checks only; never fabricate chats or execute account initialization."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parent.parent
PUBLIC_DIRS=['app','plugin','docs','scripts','.github']
PUBLIC_FILES=['README.md','LICENSE','THIRD_PARTY_NOTICES.md','SECURITY.md','package.json','package-lock.json','Install.command','.gitignore']


def files():
    manifest=json.loads((ROOT/'scripts/public_files.json').read_text())
    result=[]
    for name in manifest:
        p=ROOT/name
        if p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(ROOT):
            raise RuntimeError('Unsafe or missing release input: '+name)
        result.append(p)
    return sorted(result)


def main():
    for p in files():
        text=p.read_text()
        if p.suffix=='.py':ast.parse(text,filename=str(p))
        if p.suffix=='.json':json.loads(text)
        if p.suffix in ('.sh','.command'):subprocess.run(['bash','-n',str(p)],check=True)
        if p.suffix=='.mjs':subprocess.run(['node','--check',str(p)],check=True)
        # Actual credential / account identifiers do not belong in source.
        if re.search(r'wxid_[a-zA-Z0-9]{8,}|o9cq[0-9A-Za-z]+|sk-(?:proj-)?[A-Za-z0-9_-]{20,}',text):
            raise RuntimeError('Personal identity or credential-like text found: '+str(p.relative_to(ROOT)))
        if re.search(r'/Users/[A-Za-z][A-Za-z0-9._-]+/',text):
            raise RuntimeError('Machine-specific author path found: '+str(p.relative_to(ROOT)))
    hashes=json.loads((ROOT/'app/vendor/SHA256.json').read_text())
    for name,value in hashes.items():
        assert hashlib.sha256((ROOT/'app/vendor'/name).read_bytes()).hexdigest()==value,name
    package=json.loads((ROOT/'package.json').read_text());lock=json.loads((ROOT/'package-lock.json').read_text())
    assert package['dependencies']==lock['packages']['']['dependencies']
    for name,version in package['dependencies'].items():
        entry=lock['packages']['node_modules/'+name]
        assert entry['version']==version and entry.get('integrity'),name
    print('PASS: syntax, vendor hashes, root dependency pins, public-source privacy checks; no chat data generated.')


if __name__=='__main__':main()
