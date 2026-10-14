#!/usr/bin/env python3
"""Run the reviewed temporary-copy capture with backup and outer recovery."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

SOURCE_REVISION = 'c98dbb10cf23c30e83d5d744905101b0880887a0'

def run(args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if p.returncode:
        raise RuntimeError(f'{Path(args[0]).name} failed with exit {p.returncode}')
    return p.stdout + p.stderr


def original_signature():
    return run(['codesign', '-dvv', '/Applications/WeChat.app'])


def recover(state, before):
    """Stop only executables inside this newly created private app copy."""
    shadow = state / 'WeChat-trial.app'
    disabled = state / 'WeChat-trial.disabled'
    def processes():
        rows = []
        for line in run(['ps', '-axo', 'pid=,comm=']).splitlines():
            fields = line.strip().split(None, 1)
            if len(fields) == 2:
                rows.append((int(fields[0]), fields[1]))
        return rows
    def owned():
        return [(pid, path) for pid, path in processes()
                if path.startswith(str(shadow) + '/')]
    for pid, _ in owned():
        try:
            os.kill(pid, signal.SIGCONT)
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 5
    while owned() and time.monotonic() < deadline:
        time.sleep(0.25)
    # Recheck exact private-copy paths before escalating; never kill by name.
    for pid, _ in owned():
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 3
    while owned() and time.monotonic() < deadline:
        time.sleep(0.25)
    if owned():
        raise RuntimeError('temporary copy still running; manual recovery required')
    if original_signature() != before:
        raise RuntimeError('original signature changed; manual recovery required')
    if shadow.exists():
        ls = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'
        subprocess.run([ls, '-u', str(shadow)], capture_output=True, timeout=30)
        if disabled.exists():
            raise RuntimeError('disabled-copy path already exists; refusing overwrite')
        shadow.rename(disabled)
    original_exe = '/Applications/WeChat.app/Contents/MacOS/WeChat'
    if not any(path == original_exe for _, path in processes()):
        subprocess.Popen([original_exe],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    time.sleep(1)
    original_running = any(path == original_exe for _, path in processes())
    print(f'Recovery: original signature unchanged; original process detected={original_running}; login/UI usability still requires confirmation.', flush=True)
    if not original_running:
        raise RuntimeError('original-app process was not detected; manual recovery required')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--confirm-temporary-copy', action='store_true')
    ap.add_argument('--state-dir', type=Path, required=True)
    args = ap.parse_args()
    if not args.confirm_temporary_copy:
        ap.error('explicit user confirmation of interruption and debug-copy access is required')
    os.umask(0o077)
    base = Path(os.environ.get('WECHAT_ASSISTANT_HOME', Path.home()/'.local/share/wechat-chat-assistant')).expanduser().resolve()
    source = Path(__file__).resolve().parent/'vendor'
    hashes = json.loads((source/'SHA256.json').read_text())
    for name, expected in hashes.items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f'reviewed source changed: {name}')
    if subprocess.run(['pgrep', '-x', 'WeChat'], capture_output=True).returncode == 0:
        raise RuntimeError('save drafts and quit WeChat normally before running')
    selected = json.loads((base/'reader-config.json').read_text())['db_root']
    roots = [Path(selected).resolve(strict=True)]
    allowed_root = Path.home()/'Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files'
    if not roots[0].is_relative_to(allowed_root.resolve()) or roots[0].name != 'db_storage':
        raise RuntimeError('invalid local WeChat account database selection')
    state = args.state_dir.expanduser().resolve()
    if not state.is_relative_to(base.resolve()):
        raise RuntimeError('private state must remain inside the assistant directory')
    state.mkdir(mode=0o700, parents=True, exist_ok=False)
    before = original_signature()
    run(['codesign', '--verify', '--deep', '--strict', '/Applications/WeChat.app'])
    shutil.copytree(roots[0], state / 'encrypted-database-backup')
    print('Encrypted database backup completed; keys never printed.', flush=True)
    capture_error = None
    try:
        proc = subprocess.Popen([
            sys.executable, str(source / 'bootstrap_keys.py'),
            '--acknowledge-debug-copy', '--db-root', str(roots[0]),
            '--state-dir', str(state), '--timeout', '300',
        ], start_new_session=True)
        try:
            returncode = proc.wait(timeout=420)
        except BaseException:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=10)
            raise
    except BaseException as error:
        capture_error = error
    try:
        recover(state, before)
    except Exception as recovery_error:
        raise RuntimeError(f'capture error: {type(capture_error).__name__ if capture_error else "none"}; recovery error: {recovery_error}') from recovery_error
    if capture_error is not None:
        raise capture_error
    key_file = state / 'keys.json'
    if not key_file.exists():
        raise RuntimeError('no captured keys; data connection remains unavailable')
    if key_file.stat().st_mode & 0o077:
        raise RuntimeError('captured key file permissions are not private')
    found = json.loads(key_file.read_text()).get('keys', {})
    intended = {str(p.relative_to(roots[0])) for p in roots[0].rglob('*.db')}
    missing = sorted(intended - set(found))
    print(json.dumps({'captured_databases': len(found), 'intended_databases': len(intended),
                      'missing_databases': len(missing), 'upstream_exit': returncode,
                      'complete_capture': not missing and returncode == 0}), flush=True)
    if missing or returncode:
        raise RuntimeError('capture incomplete; do not claim all-chat coverage')
    print('Capture complete; independent SQLCipher verification is still required.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Bootstrap stopped: {type(error).__name__}: {error}', file=sys.stderr)
        raise SystemExit(2)
