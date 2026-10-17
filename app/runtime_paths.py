"""Lightweight owner-bound receipt paths shared by workers and scheduler."""
import hashlib,json,os,re
from pathlib import Path
BASE=Path(os.environ.get('WECHAT_ASSISTANT_HOME',Path.home()/'.local/share/wechat-chat-assistant')).expanduser().resolve()

def binding_fingerprint(value):
    mode=value.get('report_binding_mode','legacy4')
    if mode not in ('legacy4','full5'):raise ValueError('Unknown receipt binding; migration must be explicit')
    fields=('owner','account','self_id','db_root','key_file') if mode=='full5' else ('db_root','self_id','owner','account')
    if not all(value.get(k) for k in fields):raise ValueError('Receipt owner binding is incomplete')
    return hashlib.sha256(json.dumps({k:value[k] for k in fields},sort_keys=True).encode()).hexdigest()

def report_location(value,day,base=None):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day):raise ValueError('Invalid report day')
    layout=value.get('report_layout','bound')
    if layout not in ('flat','bound'):raise ValueError('Unknown receipt layout; migration must be explicit')
    base=Path(base) if base is not None else BASE
    binding=binding_fingerprint(value)
    return ((base/'reports'/day) if layout=='flat' else (base/'reports'/binding/day)),binding
