#!/usr/bin/env python3
"""Interactive, isolated installation. Never publishes personal runtime state."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import shutil
import socket
import subprocess
import sys

BASE=Path(os.environ.get('WECHAT_ASSISTANT_HOME',Path.home()/'.local/share/wechat-chat-assistant')).expanduser().resolve()
PROFILE='wechat-chat-assistant'
SOURCE=Path(__file__).resolve().parent.parent
STATE=Path.home()/('.openclaw-'+PROFILE)
CONFIG=BASE/'reader-config.json'
VERSION='0.1.0'


def write(path, value):
    from tempfile import mkstemp
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,tmp=mkstemp(dir=path.parent,prefix='.setup-')
    try:
        with os.fdopen(fd,'w') as f:
            json.dump(value,f,ensure_ascii=False,indent=2)
            f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def confirm(message, word='y'):
    if not sys.stdin.isatty():raise RuntimeError('需要交互式终端；不会自动跳过确认。')
    return input(message+f'\n输入 {word} 继续，其他输入取消：').strip()==word


def config():
    return json.loads(CONFIG.read_text())


def run(args, capture=False, timeout=None):
    result=subprocess.run([str(x) for x in args],check=False,capture_output=capture,text=True,timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'{Path(str(args[0])).name} 执行失败（{result.returncode}）。请查看终端或本机服务日志。')
    if capture:
        for i,ch in enumerate(result.stdout):
            if ch=='{':
                try:return json.loads(result.stdout[i:])
                except json.JSONDecodeError:pass
        raise RuntimeError('命令没有返回有效JSON；未假定成功。')


def oc(*args,capture=False,timeout=None):
    c=config()
    return run([c['node'],c['cli'],'--profile',c['profile'],*args],capture,timeout)


def install():
    if platform.system()!='Darwin' or platform.machine()!='arm64':
        raise RuntimeError('Beta仅支持Apple Silicon macOS；请不要用Rosetta运行。')
    if sys.version_info<(3,14):raise RuntimeError('需要Python 3.14+（zstd支持）。')
    if CONFIG.exists():
        print('检测到已有安装。配置和记录已保留。使用 connect、reader、verify、enable 子命令继续。')
        return
    if STATE.exists():raise RuntimeError('已有同名OpenClaw profile；拒绝覆盖。请使用其他隔离环境。')
    if (BASE/'app').exists() or (BASE/'runtime').exists():
        raise RuntimeError('发现未完成安装。不会覆盖；请按 docs/RECOVERY.md 处理。')
    node=shutil.which('node');npm=shutil.which('npm')
    if not node or not npm:raise RuntimeError('需要Node24.16+/npm。请运行Install.command。')
    major,minor=map(int,subprocess.check_output([node,'--version'],text=True).strip().lstrip('v').split('.')[:2])
    if major<24 or (major==24 and minor<16):raise RuntimeError('Node版本过低。')
    if not confirm('安装独立微信助手、启动本机回环服务；模型处理聊天内容需要你后续单独授权。'):
        return
    BASE.mkdir(parents=True,exist_ok=True,mode=0o700);BASE.chmod(0o700)
    (BASE/'runtime').mkdir(mode=0o700)
    for name in ['package.json','package-lock.json']:
        shutil.copy2(SOURCE/name,BASE/'runtime'/name)
    run([npm,'ci','--prefix',BASE/'runtime','--omit=dev'],timeout=1800)
    shutil.copytree(SOURCE/'app',BASE/'app',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(SOURCE/'plugin',BASE/'plugin')
    workspace=BASE/'workspace';workspace.mkdir(mode=0o700)
    shutil.copy2(SOURCE/'docs/SOUL.md',workspace/'SOUL.md')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    c={'version':VERSION,'profile':PROFILE,'node':str(Path(node).resolve()),'python':sys.executable,
       'cli':str(BASE/'runtime/node_modules/.bin/openclaw'),'port':port}
    write(CONFIG,c)
    STATE.mkdir(mode=0o700)
    env={'WECHAT_ASSISTANT_HOME':str(BASE)}
    proxy=input('可选HTTP/HTTPS代理URL（例如本机代理；没有则直接回车）：').strip()
    if proxy:
        from urllib.parse import urlparse
        parsed=urlparse(proxy)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
            raise RuntimeError('仅支持不含账户密码的HTTP/HTTPS代理URL。')
        env.update(HTTP_PROXY=proxy,HTTPS_PROXY=proxy,NODE_USE_ENV_PROXY='1',NO_PROXY='localhost,127.0.0.1,::1,.weixin.qq.com,.weixin.qq.com.cn,.wechat.com')
    write(STATE/'openclaw.json',{'gateway':{'mode':'local','port':port,'bind':'loopback','auth':{'mode':'token','token':secrets.token_urlsafe(32)}},
       'agents':{'defaults':{'workspace':str(workspace),'heartbeat':{'every':'0m'}}},'session':{'dmScope':'per-account-channel-peer'},'plugins':{'slots':{'memory':'none'}},'tools':{'deny':['*']},'env':{'vars':env}})
    # Install from the lockfile-controlled packages, never a mutable latest tag.
    oc('plugins','install',str(BASE/'runtime/node_modules/@tencent-weixin/openclaw-weixin'),'--force')
    oc('plugins','install',str(BASE/'runtime/node_modules/@openclaw/codex'),'--force')
    oc('gateway','install','--port',str(port),'--runtime-path',c['node'])
    # A brand-new isolated profile belongs exclusively to this installer.
    # Disable dependency-generated background model jobs before authorization.
    for job in oc('cron','list','--json',capture=True).get('jobs',[]):
        if job.get('enabled'):
            oc('cron','disable',job['id'])
    connect()
    if confirm('现在初始化本人微信聊天读取？会使用临时重签名副本，必须先保存草稿并完成微信官方备份。'):
        reader()
        verify()
        if confirm('执行真实模型检索和完整昨日简报试发？相关文字将发送到你选择的模型服务，使用订阅额度。'):
            activate()
    print('安装向导结束。诊断：python3.14 '+str(BASE/'app/setup.py')+' doctor')


def connect():
    if not confirm('接入ChatGPT/Codex订阅：问答和相关聊天文字将发送给OpenAI处理，并消耗订阅额度。不会配置收费API备用通道。'):
        raise RuntimeError('未授权模型连接。')
    pause_and_invalidate()
    oc('models','auth','login','--provider','openai','--device-code','--set-default')
    oc('channels','login','--channel','openclaw-weixin')
    accounts=[]
    folder=STATE/'openclaw-weixin/accounts'
    for p in folder.glob('*.json'):
        if '.' in p.stem:continue
        data=json.loads(p.read_text())
        if data.get('token') and data.get('userId'):
            accounts.append((p.stem,data['userId']))
    if len(accounts)!=1:raise RuntimeError('未找到唯一的已认证机器人账户；未猜测主人身份。')
    account,owner=accounts[0]
    c=config()
    changed=c.get('account')!=account or c.get('owner')!=owner
    if changed:
        for field in ['key_file','db_root','self_id','original_app_confirmed']:
            c.pop(field,None)
    c.update(account=account,owner=owner);write(CONFIG,c)
    print('扫码账户已保存到本机。请在微信助手会话发一条“你好”，建立当前对话通道。')
    input('已发送后按回车继续：')


def reader():
    roots=sorted((Path.home()/'Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files').glob('*/db_storage'))
    if not roots:raise RuntimeError('未找到Mac微信4.x数据库。先登录原版微信并同步需要的记录。')
    for i,p in enumerate(roots):print(f'{i+1}. {p.parent.name}')
    choice=0 if len(roots)==1 else int(input('选择你本人当前登录的账户序号：'))-1
    if not 0<=choice<len(roots):raise RuntimeError('账户选择无效。')
    root=roots[choice]
    # Confirm local account independently from the official bot transport ID.
    import re
    suggested=re.sub(r'_[0-9a-f]{4}$','',root.parent.name)
    self_id=input(f'确认此数据库所属微信ID（查看文件夹名；通常为 {suggested}）：').strip()
    if not self_id or not (root.parent.name==self_id or root.parent.name.startswith(self_id+'_')):
        raise RuntimeError('本地微信ID与所选账户目录不匹配。')
    if not confirm('读取初始化将备份加密数据库、运行临时重签名微信副本以获取本人账户密钥，可能需要手机登录确认。副本访问你的账户数据，存在微信版本不兼容或账号检测风险。原版签名和SIP不改变。\n请先保存草稿、完成官方备份，然后从微信菜单正常退出（不会替你强制结束原版）。',word='我已备份并同意'):
        return
    if subprocess.run(['pgrep','-x','WeChat'],capture_output=True).returncode==0:
        raise RuntimeError('微信仍在运行；请从菜单正常退出后重试 reader。')
    pause_and_invalidate(reader=True)
    c=config();c.update(db_root=str(root),self_id=self_id);write(CONFIG,c)
    state=BASE/('private-reader-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    run([sys.executable,BASE/'app/bootstrap_local_reader.py','--confirm-temporary-copy','--state-dir',state])
    c['key_file']=str(state/'keys.json');write(CONFIG,c)
    if not confirm('原版微信已恢复。请打开原版确认能正常登录、看到聊天列表。确认正常后继续：'):
        raise RuntimeError('原版微信可用性尚未确认；不启用读取工具或简报。')
    c['original_app_confirmed']=True;write(CONFIG,c)


def verify():
    c=config()
    if not c.get('original_app_confirmed'):raise RuntimeError('尚未完成原版微信可用性确认。')
    pause_and_invalidate()
    sys.path.insert(0,str(BASE/'app/vendor'))
    from sqlcipher_probe import verify as verify_db, DB, load_key
    root=Path(c['db_root']);keys=Path(c['key_file']);paths=sorted(root.rglob('*.db'))
    if not paths:raise RuntimeError('没有实际数据库。')
    for p in paths:
        result=verify_db(p,keys)
        if not result['verified'] or result['query_only']!='1':raise RuntimeError('数据库验证失败，保持简报停用。')
    p=root/'contact/contact.db'
    encoded=c['self_id'].encode().hex()
    with DB(p,load_key(keys,p)) as db:
        own=db.query("SELECT username,nick_name FROM contact WHERE username=CAST(x'"+encoded+"' AS TEXT)")
    if len(own)!=1:raise RuntimeError('无法从真实联系人数据确认本地本人身份。')
    c['reader_verified']=True;write(CONFIG,c)
    print(f'{len(paths)}个真实数据库只读验证通过。本地账号身份已核对。')


def activate():
    c=config()
    if not all(c.get(k) for k in ['reader_verified','original_app_confirmed','owner','account','key_file']):
        raise RuntimeError('缺少真实读取或认证身份。')
    verify()
    oc('plugins','install',str(BASE/'plugin'),'--force')
    oc('config','unset','tools.deny')
    oc('config','set','tools.allow','["wechat_history","wechat_memory"]')
    oc('gateway','restart')
    oc('gateway','call','sessions.reset','--params',json.dumps({'key':'agent:main:main','reason':'new'}),'--json',capture=True)
    # Prove the actual subscription runtime invokes the owner-only tool.
    key='agent:main:main'
    audit=BASE/'retrieval-audit.jsonl'
    before=audit.stat().st_size if audit.exists() else 0
    tested=oc('agent','--session-key',key,'--message','调用wechat_history，limit=1，days=1；仅回复实际消息总数和读取范围，不复述消息正文。',
              '--reply-channel','openclaw-weixin','--reply-account',c['account'],'--reply-to',c['owner'],'--deliver','--json',capture=True,timeout=900)
    completed=[]
    if audit.exists():
        with audit.open('rb') as f:
            f.seek(before)
            completed=[json.loads(line) for line in f.read().splitlines() if line]
    if tested.get('status')!='ok' or not tested.get('result',{}).get('deliverySucceeded') or not any('records' in r and r.get('allowed') for r in completed):
        raise RuntimeError('模型工具或主人通道未验证；未启用定时任务。')
    from daily_briefing import main as brief, report_folder
    saved=sys.argv;sys.argv=['daily_briefing.py']
    try:brief()
    finally:sys.argv=saved
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    day=(datetime.now(ZoneInfo('Asia/Shanghai'))-timedelta(days=1)).strftime('%Y-%m-%d')
    from history_reader import binding_fingerprint
    folder=report_folder(day)
    receipt=json.loads((folder/'status.json').read_text())
    if receipt.get('status')!='sent' or receipt.get('binding')!=binding_fingerprint(config()):
        raise RuntimeError('完整简报尚未确认发送；不启用定时任务。')
    # Preserve the canonical sent-day receipt even for trial runs.
    job=oc('cron','add','--name','微信每日简报','--declaration-key','wechat-chat-assistant:daily',
       '--description','每天北京时间09:00开始整理前一天本机同步的文字聊天并发送给主人',
       '--cron','0 9 * * *','--tz','Asia/Shanghai','--exact','--disabled',
       '--command-argv',json.dumps([c['python'],str(BASE/'app/daily_briefing.py')]),
       '--command-cwd',str(BASE/'app'),'--timeout-seconds','3600','--no-deliver','--json',capture=True)
    job=job.get('job',job);oc('cron','enable',job['id'])
    c['daily_job_id']=job['id'];write(CONFIG,c)
    with (BASE/'workspace/SOUL.md').open('a') as f:
        f.write('\n安装向导已完成真实读取、模型检索和完整简报试发。09:00任务已配置并启用（配置验证时间：'+datetime.now().isoformat()+'）。电脑离线或服务故障时不能保证准点送达。\n')
    print('真实检索和完整试发已通过。每天北京时间09:00开始生成并推送。Mac必须开机联网。')


def pause_and_invalidate(reader=False):
    import fcntl
    with (BASE/'briefing.lock').open('a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('简报正在处理；先等待它结束，再重新授权或初始化，避免中途切换账户。')
        c=config()
        if c.get('daily_job_id'):
            oc('cron','disable',c['daily_job_id'])
        oc('config','set','tools.deny','["*"]')
        c['reader_verified']=False
        if reader:
            c.pop('original_app_confirmed',None)
            c.pop('key_file',None)
        write(CONFIG,c)


def doctor():
    c=config();checks={'platform':platform.system()+'/'+platform.machine(),'version':c['version'],
       'model_and_channel_connected':bool(c.get('account') and c.get('owner')),'reader_verified':bool(c.get('reader_verified'))}
    if c.get('daily_job_id'):
        j=oc('cron','get',c['daily_job_id'],'--json',capture=True);j=j.get('job',j)
        checks['briefing_enabled']=j.get('enabled');checks['next_run_ms']=j.get('nextRunAtMs')
    print(json.dumps(checks,ensure_ascii=False,indent=2))


def uninstall():
    if not confirm('停止并卸载此独立profile的后台服务；保留本机聊天、密钥、配置和订阅登录文件，绝不自动删除个人数据。'):
        return
    c=config()
    if c.get('daily_job_id'):oc('cron','disable',c['daily_job_id'])
    oc('gateway','uninstall')
    print('服务已停止。本机个人数据保留在 '+str(BASE)+' 和 '+str(STATE))


if __name__=='__main__':
    os.umask(0o077)
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command',choices=['install','connect','reader','verify','enable','doctor','uninstall'])
    try:
        args=ap.parse_args()
        {'install':install,'connect':connect,'reader':reader,'verify':verify,'enable':activate,'doctor':doctor,'uninstall':uninstall}[args.command]()
    except (Exception,KeyboardInterrupt) as error:
        print('未完成：'+str(error),file=sys.stderr)
        print('现有配置和数据保留。请参阅 docs/RECOVERY.md。',file=sys.stderr)
        sys.exit(2)
