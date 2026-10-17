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
VERSION='0.3.0'


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


def configure_schedules(brief_script=None):
    import fcntl
    from contextlib import ExitStack
    from scheduler import install as install_agent,ROOT as scheduler_root
    c=config();original=dict(c)
    if not c.get('reader_verified') or not c.get('original_app_confirmed'):
        raise RuntimeError('真实读取和原版微信尚未验证；不启用调度。')
    scheduler_root.mkdir(mode=0o700,parents=True,exist_ok=True)
    with ExitStack() as stack:
        for path in [BASE/'briefing.lock',scheduler_root/'worker.lock']:
            lock=stack.enter_context(path.open('a'))
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError('早报正在运行，请完成后再更新调度。')
        jobs=oc('cron','list','--json',capture=True,timeout=30)['jobs']
        previous=[j['id'] for j in jobs if j.get('id') in [c.get('preparation_job_id'),c.get('daily_job_id')] and j.get('enabled')]
        learning=next((j for j in jobs if j.get('id')==c.get('learning_job_id') or j.get('declarationKey')=='wechat-chat-assistant:learning'),None)
        created_learning=False
        if learning is None:
            learning=oc('cron','add','--name','微信语气与关系学习','--cron','30 5,11,17,23 * * *','--tz','Asia/Shanghai','--exact',
                '--command-argv',json.dumps([c['python'],str(BASE/'app/memory_refresh.py')]),'--command-cwd',str(BASE/'app'),
                '--command-env','WECHAT_ASSISTANT_HOME='+str(BASE),'--timeout-seconds','300','--no-deliver',
                '--declaration-key','wechat-chat-assistant:learning','--disabled','--json',capture=True)
            learning=learning.get('job',learning);c['learning_job_id']=learning['id'];created_learning=True
            oc('cron','enable',learning['id'],capture=True)
        else:c['learning_job_id']=learning['id']
        c.update(brief_script=str(brief_script or c.get('brief_script',BASE/'app/daily_briefing.py')),
            report_layout=c.get('report_layout','bound'),report_binding_mode=c.get('report_binding_mode','legacy4'))
        try:
            for job_id in previous:oc('cron','disable',job_id,capture=True)
            write(CONFIG,c)
            installed=install_agent(locked=True)
            c.update(scheduler_backend='launchd',scheduler_label=installed['label'],scheduler_plist=installed['plist'])
            write(CONFIG,c)
        except BaseException:
            if created_learning:oc('cron','disable',learning['id'],capture=True)
            write(CONFIG,original)
            for job_id in previous:oc('cron','enable',job_id,capture=True)
            raise
    return {'scheduler_backend':'launchd','scheduler_label':c['scheduler_label'],'learning_job_id':c['learning_job_id']}


def install():
    if platform.system()!='Darwin' or platform.machine()!='arm64':
        raise RuntimeError('Beta仅支持Apple Silicon macOS；请不要用Rosetta运行。')
    if sys.version_info<(3,14):raise RuntimeError('需要Python 3.14+（zstd支持）。')
    if CONFIG.exists():
        print('检测到已有安装，继续配置；不覆盖程序、配置或记录。')
        return resume()
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
    oc('gateway','start')
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


def resume():
    c=config()
    if c.get('version')!=VERSION:
        if not confirm('当前安装版本为 '+str(c.get('version','未知'))+'。更新到'+VERSION+'？只更新程序并备份旧程序，保留登录、密钥、任务状态和投递回执，不重新初始化微信。'):return
        upgrade()
    if not c.get('account') or not c.get('owner'):
        connect()
    c=config()
    if not c.get('key_file') or not c.get('original_app_confirmed'):
        if not confirm('现在继续聊天读取初始化？需要本人备份、退出微信并同意临时副本操作。'):return
        reader()
    if not config().get('reader_verified'):verify()
    if confirm('继续开启／修复09:00早报？已有同一账号的真实简报回执时直接修复调度；否则需要模型检索和完整试发，会使用订阅额度。'):
        repair()


def upgrade():
    import fcntl
    from contextlib import ExitStack
    c=config()
    if c.get('version')==VERSION:return
    if SOURCE.resolve()==BASE.resolve():raise RuntimeError('请从新下载的配置应用启动程序更新。')
    target=BASE/'code-backups'/datetime.now().strftime('%Y%m%d-%H%M%S-%f');target.mkdir(mode=0o700,parents=True)
    stage=target/'new';stage.mkdir(mode=0o700)
    locks=[BASE/'briefing.lock',BASE/'scheduler/worker.lock']
    if c.get('key_file'):
        digest=hashlib.sha256(json.dumps({k:c.get(k) for k in ('owner','account','self_id','db_root','key_file')},sort_keys=True).encode()).hexdigest()
        locks.append(BASE/'memory'/digest/'learning.lock')
    with ExitStack() as stack:
        for path in locks:
            path.parent.mkdir(mode=0o700,parents=True,exist_ok=True);lock=stack.enter_context(path.open('a'))
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError('早报或学习正在运行，已保留旧程序；请结束后再更新。')
        desired=json.loads((SOURCE/'package.json').read_text())
        installed_plugins=None
        for name,version in desired['dependencies'].items():
            installed=BASE/'runtime/node_modules'/name/'package.json'
            matched=installed.exists() and json.loads(installed.read_text()).get('version')==version
            if not matched and name in ('@openclaw/codex','@tencent-weixin/openclaw-weixin'):
                if installed_plugins is None:installed_plugins=oc('plugins','list','--json',capture=True,timeout=45).get('plugins',[])
                plugin_id={'@openclaw/codex':'codex','@tencent-weixin/openclaw-weixin':'openclaw-weixin'}[name]
                entry=next((p for p in installed_plugins if p.get('id')==plugin_id and p.get('version')==version and p.get('status')=='loaded'),None)
                if entry:
                    source=Path(entry['source']).resolve();scope=Path.home()/('.openclaw-'+c['profile'])/'npm'
                    if source.is_file() and source.is_relative_to(scope):
                        for parent in source.parents:
                            if not parent.is_relative_to(scope):break
                            manifest=parent/'package.json'
                            if manifest.is_file():
                                package=json.loads(manifest.read_text())
                                if package.get('name')==name and package.get('version')==version:matched=True;break
            if not matched:raise RuntimeError('依赖版本变化，需要单独迁移；未覆盖现有运行环境。')
        shutil.copytree(SOURCE/'app',stage/'app',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        write(target/'reader-config.json',c)
        soul=BASE/'workspace/SOUL.md';old_soul=soul.read_bytes() if soul.exists() else None
        if old_soul is not None:(target/'SOUL.md').write_bytes(old_soul);(target/'SOUL.md').chmod(0o600)
        was_loaded=False
        if c.get('scheduler_backend')=='launchd':
            from scheduler import stop,agent_label
            was_loaded=subprocess.run(['launchctl','print','gui/'+str(os.getuid())+'/'+agent_label()],capture_output=True).returncode==0
            stop()
        old_app_moved=False
        try:
            (BASE/'app').rename(target/'app');old_app_moved=True
            (stage/'app').rename(BASE/'app')
            marker='配置版本 '+VERSION
            if old_soul is not None and marker not in old_soul.decode():
                with soul.open('a') as stream:stream.write('\n'+marker+'：早报由独立本机调度器提前准备、08:00核对同步、09:00投递，唤醒后最迟中午补发。任务导入需主人预览确认；完成或取消事项不重开。原有权限限制保持有效。\n')
            c['version']=VERSION;write(CONFIG,c)
            if was_loaded:
                from scheduler import install as install_agent
                install_agent(locked=True)
        except BaseException:
            if old_app_moved:
                if (BASE/'app').exists():(BASE/'app').rename(target/'failed-app')
                (target/'app').rename(BASE/'app')
            write(CONFIG,json.loads((target/'reader-config.json').read_text()))
            if old_soul is not None:soul.write_bytes(old_soul)
            if was_loaded:
                from scheduler import install as install_agent
                install_agent(locked=True)
            raise
    print('程序已更新，旧程序已备份；个人状态与回执保持原状。')


def prior_real_delivery():
    from scheduler import report_location
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    c=config()
    for offset in range(1,9):
        day=(datetime.now(ZoneInfo('Asia/Shanghai'))-timedelta(days=offset)).strftime('%Y-%m-%d')
        folder,binding=report_location(c,day);path=folder/'status.json'
        if not path.exists():continue
        state=json.loads(path.read_text())
        if state.get('binding')!=binding or state.get('status') not in ('sent','corrected_sent'):continue
        for receipt in [*folder.glob('*receipt*.json'),*folder.glob('narrative-delivery-*.json')]:
            value=json.loads(receipt.read_text())
            if not value.get('dryRun') and value.get('payload',{}).get('deliveryStatus')=='sent':return True
    return False


def repair():
    c=config()
    if c.get('version')!=VERSION:
        if not confirm('需要先更新程序到'+VERSION+'才能安装新的独立调度。保留个人状态并更新？'):return
        upgrade();c=config()
    if not c.get('reader_verified') or not c.get('original_app_confirmed'):raise RuntimeError('先完成聊天读取验证。')
    if prior_real_delivery():
        configure_schedules();print('已复用同一账号的真实试发回执，修复独立09:00调度；没有重复试发。')
    else:activate()


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
    configure_schedules()
    with (BASE/'workspace/SOUL.md').open('a') as f:
        f.write('\n真实读取、模型检索和完整简报试发已验证。提前准备晨报、08:00核对同步、09:00尝试投递；学习独立运行（配置验证时间：'+datetime.now().isoformat()+'）。电脑离线或服务故障时不能保证准点送达。\n')
    print('真实检索和完整试发已通过。独立调度提前准备，08:00核对同步，09:00投递；学习独立运行。Mac必须开机联网。')


def pause_and_invalidate(reader=False):
    import fcntl
    with (BASE/'briefing.lock').open('a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('简报正在处理；先等待它结束，再重新授权或初始化，避免中途切换账户。')
        c=config()
        if c.get('scheduler_backend')=='launchd':
            from scheduler import busy,stop
            if busy():raise RuntimeError('早报工作进程正在处理，请结束后再更改账号。')
            stop()
        for key in ['daily_job_id','preparation_job_id','learning_job_id']:
            if c.get(key):oc('cron','disable',c[key])
        oc('config','set','tools.deny','["*"]')
        c['reader_verified']=False
        if reader:
            c.pop('original_app_confirmed',None)
            c.pop('key_file',None)
        write(CONFIG,c)


def doctor():
    from zoneinfo import ZoneInfo
    from datetime import timedelta
    import sqlite3
    checked=datetime.now(ZoneInfo('Asia/Shanghai'))
    checks={'checked_at':checked.isoformat(),'platform':platform.system()+'/'+platform.machine(),
            'launcher_version':VERSION,'installed':CONFIG.exists(),'checks':{},'warnings':[]}
    if not CONFIG.exists():
        checks['warnings'].append('尚未安装；未检查登录、聊天读取或调度。')
        print(json.dumps(checks,ensure_ascii=False,indent=2));return
    c=config()
    if c.get('version') and c.get('version')!=VERSION:
        checks['warnings'].append('已安装程序版本与配置应用不同；继续配置不会自动覆盖旧程序。')
    checks.update(version=c.get('version'),profile=c.get('profile'),
       model_and_channel_connected=bool(c.get('account') and c.get('owner')),
       reader_verified=bool(c.get('reader_verified')),original_app_confirmed=bool(c.get('original_app_confirmed')))
    checks['checks']['account_flags']='saved_configuration_only'
    try:
        jobs=oc('cron','list','--json',capture=True,timeout=25).get('jobs',[])
        checks['checks']['gateway']='live'
        checks['schedules']={}
        for field in ['preparation_job_id','daily_job_id','learning_job_id']:
            job=next((j for j in jobs if j.get('id')==c.get(field)),None)
            state=(job or {}).get('state',{})
            checks['schedules'][field]=None if job is None else {
                'enabled':job.get('enabled'),'schedule':job.get('schedule'),
                'last_status':state.get('lastRunStatus'),'last_run_ms':state.get('lastRunAtMs'),
                'next_run_ms':state.get('nextRunAtMs'),'last_error':state.get('lastError')}
        daily=checks['schedules']['daily_job_id']
        checks['briefing_enabled']=daily.get('enabled') if daily else False
        for key,value in checks['schedules'].items():
            if c.get('scheduler_backend')=='launchd' and key!='learning_job_id':continue
            if value and value.get('last_status')=='error':checks['warnings'].append('定时任务最近一次运行失败，请查看状态与本机日志。');break
    except Exception as error:
        checks['checks']['gateway']='unavailable';checks['briefing_enabled']=None
        checks['warnings'].append('未取得实时调度状态：'+str(error))
    if c.get('scheduler_backend')=='launchd':
        from scheduler import agent_label,report_location,job_state,load as scheduler_load
        label=agent_label()
        result=subprocess.run(['launchctl','print','gui/'+str(os.getuid())+'/'+label],capture_output=True,text=True,timeout=10)
        loaded=result.returncode==0
        checks['scheduler']={'backend':'launchd','loaded':loaded,'label':label,'status':scheduler_load(BASE/'scheduler/status.json')}
        checks['briefing_enabled']=loaded and bool(c.get('reader_verified')) and bool(c.get('original_app_confirmed'))
        report_day=(checked-timedelta(days=1)).strftime('%Y-%m-%d')
        checks['scheduler']['jobs']=scheduler_load(job_state(c,report_day))
        action=checks['scheduler']['status'].get('action')
        if action in ('held','missed_window'):checks['warnings'].append('早报需要核对投递状态或已经超过自动补发窗口，不会盲目重发。')
        if not loaded:checks['warnings'].append('独立早报服务未运行，请点击验证／修复。')
    if all(c.get(k) for k in ['db_root','self_id','owner','account']):
        fingerprint=hashlib.sha256(json.dumps({k:c[k] for k in ['db_root','self_id','owner','account']},sort_keys=True).encode()).hexdigest()
        memory_binding=hashlib.sha256(json.dumps({k:c.get(k) for k in ['owner','account','self_id','db_root','key_file']},sort_keys=True).encode()).hexdigest()
        folder=BASE/'memory'/memory_binding
        status=folder/'learning-status.json'
        if status.exists():
            value=json.loads(status.read_text())
            checks['learning']={k:value.get(k) for k in ['phase','at','voice_samples','observed_edit_candidates','candidates_added','error_type']}
        database=folder/'memory.sqlite'
        if database.exists():
            db=sqlite3.connect(database.as_uri()+'?mode=ro',uri=True,timeout=2)
            try:
                checks['tasks']={row[0]:row[1] for row in db.execute('SELECT status,count(*) FROM tasks GROUP BY status')}
                checks['observed_edits']=db.execute('SELECT count(*) FROM feedback').fetchone()[0]
            finally:db.close()
        day=(checked-timedelta(days=1)).strftime('%Y-%m-%d')
        if c.get('scheduler_backend')=='launchd':reports=report_location(c,day)[0]
        else:
            reports=BASE/'reports'/fingerprint/day
            if not reports.exists():reports=BASE/'reports'/day
        state=reports/'status.json'
        checks['latest_briefing']={'source_day':day,'status':'not_prepared'}
        if state.exists():
            value=json.loads(state.read_text())
            checks['latest_briefing'].update({k:value.get(k) for k in ['status','prepared_at','sent_at','correction_sent_at','error_type']})
        fallback=reports/'task-reminder.json'
        if fallback.exists():
            pages=json.loads(fallback.read_text()).get('pages',[])
            checks['latest_briefing']['fallback_pages_sent']=sum(p.get('status')=='sent' for p in pages)
        checks['checks']['learning_and_briefing']='local_saved_records'
    checks['reply_sending']='not_in_public_beta'
    checks['warnings'].append('休眠、离线、订阅额度不足或微信会话失效会影响09:00投递。')
    print(json.dumps(checks,ensure_ascii=False,indent=2))


def uninstall():
    if not confirm('停止并卸载此独立profile的后台服务；保留本机聊天、密钥、配置和订阅登录文件，绝不自动删除个人数据。'):
        return
    c=config()
    if c.get('scheduler_backend')=='launchd':
        from scheduler import busy,stop
        if busy():raise RuntimeError('早报正在运行，请结束后再卸载服务。')
        stop(remove=True)
    for key in ['daily_job_id','preparation_job_id','learning_job_id']:
        if c.get(key):oc('cron','disable',c[key])
    oc('gateway','uninstall')
    print('服务已停止。本机个人数据保留在 '+str(BASE)+' 和 '+str(STATE))


if __name__=='__main__':
    os.umask(0o077)
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command',choices=['install','resume','upgrade','repair','connect','reader','verify','enable','doctor','uninstall'])
    try:
        args=ap.parse_args()
        {'install':install,'resume':resume,'upgrade':upgrade,'repair':repair,'connect':connect,'reader':reader,'verify':verify,'enable':activate,'doctor':doctor,'uninstall':uninstall}[args.command]()
    except (Exception,KeyboardInterrupt) as error:
        print('未完成：'+str(error),file=sys.stderr)
        print('现有配置和数据保留。请参阅 docs/RECOVERY.md。',file=sys.stderr)
        sys.exit(2)
