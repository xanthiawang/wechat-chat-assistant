#!/usr/bin/env python3
"""Read genuine local WeChat data; fixed read-only queries, never arbitrary SQL."""
import argparse
from collections import Counter
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

BASE = Path(os.environ.get('WECHAT_ASSISTANT_HOME', Path.home()/'.local/share/wechat-chat-assistant')).expanduser().resolve()
sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor'))
from sqlcipher_probe import DB, load_key
from compression import zstd
TZ = ZoneInfo('Asia/Shanghai')


def private_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.write-')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read(query='', day=None, days=7, offset=0, limit=60, full=False):
    config = json.loads((BASE / 'reader-config.json').read_text())
    root, keys = Path(config['db_root']), Path(config['key_file'])
    now = datetime.now(TZ)
    end = now if not day else datetime.strptime(day, '%Y-%m-%d').replace(tzinfo=TZ) + timedelta(days=1)
    start = end - timedelta(days=days if not day else 1)
    if days == 0 and not day:
        start = datetime(1970, 1, 1, tzinfo=TZ)
    a, b = int(start.timestamp()), int(end.timestamp())
    names, hashes = {}, {}
    def open_db(p):
        return DB(p, load_key(keys, p))
    with open_db(root / 'contact/contact.db') as db:
        for r in db.query('SELECT username,nick_name,remark FROM contact'):
            names[r['username']] = r['remark'] or r['nick_name'] or r['username']
    with open_db(root / 'session/session.db') as db:
        for r in db.query('SELECT username FROM SessionTable'):
            hashes[hashlib.md5(r['username'].encode()).hexdigest()] = r['username']
    for user in names:
        hashes[hashlib.md5(user.encode()).hexdigest()] = user
    terms = [s.casefold() for s in re.split(r'[\s,，;；]+', query.strip()) if s]
    rows, ledger, counts = [], [], Counter()
    paths = sorted(p for p in (root / 'message').glob('*.db') if re.fullmatch(r'(biz_)?message_\d+\.db', p.name))
    if not paths:
        raise RuntimeError('required message databases not found')
    for path in paths:
        with open_db(path) as db:
            db.query('BEGIN')
            try:
                senders = {int(r['rowid']): r['user_name'] for r in db.query('SELECT rowid,user_name FROM Name2Id')}
                for user in senders.values():
                    hashes[hashlib.md5(user.encode()).hexdigest()] = user
                tables = [r['name'] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'") if re.fullmatch(r'Msg_[0-9a-f]{32}', r['name'])]
                for table in tables:
                    chat = hashes.get(table[4:], table)
                    label = names.get(chat, chat)
                    cursor = -1
                    total = text_count = omitted = matched = 0
                    while True:
                        batch = db.query(f'SELECT local_id,server_id,create_time,local_type,real_sender_id,hex(message_content) body FROM "{table}" WHERE create_time>={a} AND create_time<{b} AND local_id>{cursor} ORDER BY local_id LIMIT 1000')
                        if not batch:
                            break
                        for r in batch:
                            cursor = int(r['local_id'])
                            total += 1
                            kind = int(r['local_type'])
                            counts[str(kind)] += 1
                            if kind != 1:
                                omitted += 1
                                continue
                            raw = bytes.fromhex(r['body'] or '')
                            try:
                                if raw.startswith(b'\x28\xb5\x2f\xfd'):
                                    raw = zstd.decompress(raw)
                                body = raw.decode('utf8', 'strict')
                            except Exception:
                                omitted += 1
                                counts['unreadable_text'] += 1
                                continue
                            text_count += 1
                            sender = senders.get(int(r['real_sender_id']), '未知发送者')
                            if chat.endswith('@chatroom') and body.startswith(sender + ':\n'):
                                body = body[len(sender)+2:]
                            if terms and not any(t in (label+' '+names.get(sender,sender)+' '+body).casefold() for t in terms):
                                continue
                            matched += 1
                            rows.append({'source': f'{path.name}/{table}/{cursor}', 'chat': label, 'chat_id':chat,
                                         'sender':names.get(sender,sender), 'from_self':sender==config['self_id'], 'time':datetime.fromtimestamp(int(r['create_time']), TZ).isoformat(),
                                         'server_id':r['server_id'], 'text':body})
                        if len(batch) < 1000:
                            break
                    ledger.append({'database':path.name,'table':table,'chat':label,'messages':total,'read_text':text_count,'omitted':omitted,'matches':matched})
            finally:
                db.query('ROLLBACK')
    rows.sort(key=lambda r:(r['time'],r['source']), reverse=not full)
    selected = rows if full else rows[offset:offset+limit]
    # Bound tool output; never hide that more evidence exists.
    chars = 0
    if not full:
        bounded = []
        for r in selected:
            item = dict(r)
            if len(item['text']) > 6000:
                item['text'] = item['text'][:6000]
                item['text_truncated'] = True
            size = len(json.dumps(item,ensure_ascii=False))
            if bounded and chars+size > 40000:
                break
            bounded.append(item)
            chars += size
        selected = bounded
    return {'scope':'仅此Mac当前已同步记录；官方手机恢复备份未作为可读数据源；图片/语音/附件/XML不解析',
            'window_start':start.isoformat(),'window_end':end.isoformat(),'read_at':now.isoformat(),
            'databases':len(paths),'tables_scanned':len(ledger),'active_chats':sum(bool(x['messages']) for x in ledger),
            'messages':sum(x['messages'] for x in ledger),'read_text':sum(x['read_text'] for x in ledger),
            'omitted':sum(x['omitted'] for x in ledger),'message_types':dict(counts),
            'total_matches':len(rows),'offset':offset,'returned':len(selected),'next_offset':offset+len(selected) if offset+len(selected)<len(rows) and not full else None,
            'records':selected, **({'ledger':ledger} if full else {})}


def main():
    os.umask(0o077)
    ap = argparse.ArgumentParser()
    ap.add_argument('--query', default='')
    ap.add_argument('--day')
    ap.add_argument('--days', type=int, default=7)
    ap.add_argument('--offset', type=int, default=0)
    ap.add_argument('--limit', type=int, default=60)
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    if not 0<=args.days<=3650 or not 0<=args.offset<=1000000 or not 1<=args.limit<=100:
        raise ValueError('query range outside permitted bounds')
    result = read(args.query,args.day,args.days,args.offset,args.limit,full=bool(args.output))
    if args.output:
        if not args.output.resolve().is_relative_to(BASE.resolve()):
            raise ValueError('export must stay in private assistant directory')
        private_write(args.output,result)
        print(json.dumps({k:v for k,v in result.items() if k not in ('records','ledger')},ensure_ascii=False))
    else:
        print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'error':type(error).__name__,'message':str(error)},ensure_ascii=False),file=sys.stderr)
        sys.exit(2)
