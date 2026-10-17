#!/usr/bin/env python3
"""User LaunchAgent supervisor. Clock/state inspection is separate from bounded work."""
import argparse,fcntl,hashlib,json,os,plistlib,signal,subprocess,sys,tempfile,time,uuid
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BASE=Path(os.environ.get('WECHAT_ASSISTANT_HOME',Path.home()/'.local/share/wechat-chat-assistant')).expanduser().resolve()
TZ=ZoneInfo('Asia/Shanghai')
ROOT=BASE/'scheduler'
UNCERTAIN={'pending','queued','unknown','failed','suppressed'}


def load(path,default=None):
    return json.loads(path.read_text()) if path.exists() else ({} if default is None else default)


def write(path,value):
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(dir=path.parent,prefix='.scheduler-')
    try:
        with os.fdopen(fd,'w') as stream:json.dump(value,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def config():return load(BASE/'reader-config.json')


def identity(c):
    if not all(c.get(k) for k in ('owner','account','self_id','db_root','key_file')):raise ValueError('Verified owner binding is incomplete')
    return hashlib.sha256(json.dumps({k:c[k] for k in ('owner','account','self_id','db_root','key_file')},sort_keys=True).encode()).hexdigest()


from runtime_paths import report_location


def job_state(c,day):return ROOT/identity(c)/(day+'.json')


def busy(name='worker.lock'):
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (ROOT/name).open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);return False
        except BlockingIOError:return True


def decide(c,now=None):
    now=now or datetime.now(TZ);day=(now-timedelta(days=1)).strftime('%Y-%m-%d')
    if not c.get('reader_verified') or not c.get('original_app_confirmed'):return {'action':'unverified','day':day}
    folder,binding=report_location(c,day);state=load(folder/'status.json');ledger=load(job_state(c,day))
    if state and (state.get('binding')!=binding or state.get('day')!=day):raise ValueError('Receipt binding mismatch; refusing another layout')
    if state.get('status') in ('sent','corrected_sent'):return {'action':'sent','day':day}
    for name in ('narrative-delivery.json','task-reminder.json'):
        journal=load(folder/name)
        if journal and journal.get('binding')!=binding:raise ValueError('Delivery journal belongs to another binding')
        if any(p.get('status') not in ('sent','unsent') for p in journal.get('pages',[])):return {'action':'held','day':day,'reason':'delivery_requires_review'}
    if str(state.get('status','')).startswith('delivery_'):
        if state.get('status')!='delivery_pending' or not (folder/'narrative-delivery.json').exists():
            return {'action':'held','day':day,'reason':'delivery_requires_review'}
    minute=now.hour*60+now.minute
    if any(ledger.get(key,{}).get('status') in ('running','cleanup_pending') for key in ('prepare','refresh')):
        if now.timestamp()>=ledger.get('cleanup',{}).get('next_after',0):return {'action':'cleanup','day':day}
        return {'action':'held','day':day,'reason':'model_cleanup_pending'}
    if minute>=12*60:return {'action':'missed_window','day':day}
    if minute<15:return {'action':'waiting','day':day}
    if state.get('status') in ('ready','delivery_pending'):
        refresh=ledger.get('refresh',{})
        checked=state.get('refresh_checked_at')
        checked_at=datetime.fromisoformat(checked).astimezone(TZ) if checked else None
        morning_checked=checked_at is not None and checked_at.date()==now.date() and checked_at.hour>=8
        if 8*60<=minute<8*60+40 and not morning_checked and not (folder/'narrative-delivery.json').exists():
            if refresh.get('attempts',0)<2 and now.timestamp()>=refresh.get('next_after',0):return {'action':'refresh','day':day}
        if minute>=9*60:
            if now.timestamp()>=ledger.get('deliver',{}).get('next_after',0):return {'action':'deliver','day':day}
        return {'action':'waiting','day':day}
    attempt=ledger.get('prepare',{})
    if attempt.get('attempts',0)<3 and now.timestamp()>=attempt.get('next_after',0):return {'action':'prepare','day':day}
    if minute>=9*60 and attempt.get('attempts',0)>=3:
        fallback=load(folder/'task-reminder.json')
        if fallback.get('pages') and all(p.get('status')=='sent' for p in fallback['pages']):return {'action':'fallback_sent','day':day}
        if now.timestamp()>=ledger.get('fallback',{}).get('next_after',0):return {'action':'fallback','day':day}
    return {'action':'waiting_retry','day':day}


def health(c):
    proc=subprocess.run([c['node'],c['cli'],'--profile',c['profile'],'gateway','call','health','--json','--timeout','10000'],capture_output=True,text=True,timeout=15)
    return proc.returncode==0


def cleanup_models(c,day):
    folder,binding=report_location(c,day)
    paths=[p for p in folder.rglob('*.run.json') if load(p).get('status') in ('running','cleanup_pending')]
    for path in paths[:5]:
        state=load(path);key=state.get('session_key','')
        if state.get('binding')!=identity(c) or not key.startswith('agent:main:wechat-digest-'+binding+'-'):raise ValueError('Model cleanup owner scope changed')
        result=subprocess.run([c['node'],c['cli'],'--profile',c['profile'],'gateway','call','sessions.abort',
            '--params',json.dumps({'key':key,'clearQueued':True}),'--timeout','10000','--json'],capture_output=True,text=True,timeout=15)
        if result.returncode:return False
        write(path,{**state,'status':'aborted'})
    return len(paths)<=5


def worker(action,day,expected):
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (ROOT/'worker.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        c=config()
        if identity(c)!=expected or not c.get('reader_verified') or not c.get('original_app_confirmed'):raise ValueError('Owner changed before worker start')
        # Recompute the real clock decision. A delayed process cannot send early or to a stale day.
        decision=decide(c)
        if decision['day']!=day or decision['action']!=action:return
        path=job_state(c,day);ledger=load(path);attempt=ledger.setdefault(action,{'attempts':0})
        event=ROOT/expected/(day+'-'+uuid.uuid4().hex+'.json')
        attempt.update(started_at=datetime.now(TZ).isoformat(),status='running');write(path,ledger)
        if action=='cleanup':
            try:cleaned=cleanup_models(c,day)
            except (OSError,subprocess.TimeoutExpired):cleaned=False
            if cleaned:
                for key in ('prepare','refresh'):
                    if ledger.get(key,{}).get('status') in ('running','cleanup_pending'):ledger[key]['status']='failed'
            attempt.update(status='complete' if cleaned else 'cleanup_pending',next_after=time.time()+60);write(path,ledger);return
        if action in ('deliver','fallback'):
            try:online=health(c)
            except (OSError,subprocess.TimeoutExpired):online=False
            if not online:
                attempt.update(status='gateway_unavailable',next_after=time.time()+60);write(path,ledger);return
        attempt['attempts']=attempt.get('attempts',0)+1;write(path,ledger)
        script=Path(c.get('brief_script',BASE/'app/daily_briefing.py')).resolve()
        if not script.is_relative_to(BASE) or not script.is_file():raise ValueError('Scheduled script must be installed inside the private runtime')
        flag={'prepare':'--prepare','refresh':'--refresh','deliver':'--deliver-ready','fallback':'--deliver-ready'}[action]
        process=subprocess.Popen([c['python'],str(script),'--day',day,flag],cwd=BASE,env={**os.environ,'WECHAT_ASSISTANT_HOME':str(BASE)},
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
        awake=None
        if Path('/usr/bin/caffeinate').exists():awake=subprocess.Popen(['/usr/bin/caffeinate','-i','-w',str(process.pid)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        deadline=time.time()+(900 if action in ('prepare','refresh') else 180)
        timed_out=False
        try:
            while True:
                remaining=deadline-time.time()
                if remaining<=0:raise subprocess.TimeoutExpired(process.args,0)
                try:stdout,stderr=process.communicate(timeout=min(5,remaining));break
                except subprocess.TimeoutExpired:
                    if time.time()>=deadline:raise
        except BaseException:
            timed_out=True
            # This process group was created by this worker; never signal the shared gateway.
            if process.poll() is None:os.killpg(process.pid,signal.SIGTERM)
            try:stdout,stderr=process.communicate(timeout=20)
            except subprocess.TimeoutExpired:
                if process.poll() is None:os.killpg(process.pid,signal.SIGKILL)
                stdout,stderr=process.communicate()
        finally:
            if awake and awake.poll() is None:awake.terminate();awake.wait(timeout=5)
        if identity(config())!=expected:raise ValueError('Owner changed during scheduled work')
        folder,binding=report_location(c,day);state=load(folder/'status.json')
        outcome='complete' if process.returncode==0 and not timed_out else ('timed_out' if timed_out else 'failed')
        journal=load(folder/'task-reminder.json')
        if action=='fallback' and journal.get('pages') and all(p.get('status')=='sent' for p in journal['pages']):outcome='fallback_sent'
        if action in ('prepare','refresh') and outcome!='complete' and state.get('status') in ('reading','summarizing') and state.get('binding')==binding:
            write(folder/'status.json',{**state,'status':'preparation_failed','failed_at':datetime.now(TZ).isoformat(),'error_type':outcome})
        if action in ('prepare','refresh') and outcome!='complete':
            try:cleaned=cleanup_models(c,day)
            except (OSError,subprocess.TimeoutExpired):cleaned=False
            if not cleaned:outcome='cleanup_pending'
        attempt.update(status=outcome,finished_at=datetime.now(TZ).isoformat(),next_after=time.time()+[300,900,1800][min(attempt['attempts']-1,2)])
        write(event,{'day':day,'action':action,'binding':expected,'status':outcome,'exit_code':process.returncode,'stdout':stdout[-60000:],'stderr':stderr[-60000:]})
        attempt['receipt']=str(event);write(path,ledger)


def tick(inspect=False):
    c=config();decision=decide(c)
    if inspect:return {**decision,'worker_running':busy(),'backend':'launchd'}
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (ROOT/'tick.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        valid=all(c.get(k) for k in ('owner','account','self_id','db_root','key_file'))
        write(ROOT/'status.json',{**decision,'checked_at':datetime.now(TZ).isoformat(),'binding':identity(c) if valid else None,'worker_running':busy()})
        if decision['action'] not in ('prepare','refresh','deliver','fallback','cleanup') or busy():return
        with (BASE/'briefing.lock').open('a') as brief:
            try:fcntl.flock(brief,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return
        with (ROOT/'worker.log').open('a') as log:
            subprocess.Popen([c['python'],str(Path(__file__).resolve()),'--work',decision['action'],'--day',decision['day'],'--binding',identity(c)],
                env={**os.environ,'WECHAT_ASSISTANT_HOME':str(BASE)},cwd=BASE,stdout=log,stderr=log,start_new_session=True)


def agent_label():return 'com.wechat-chat-assistant.scheduler.'+hashlib.sha256(str(BASE).encode()).hexdigest()[:12]


def stop(remove=False):
    label=agent_label();target='gui/'+str(os.getuid())+'/'+label
    exists=subprocess.run(['launchctl','print',target],capture_output=True).returncode==0
    if exists:subprocess.run(['launchctl','bootout',target],check=True,capture_output=True)
    path=Path.home()/'Library/LaunchAgents'/(label+'.plist')
    if remove and path.exists():
        archive=ROOT/'agent-backups'/(str(time.time_ns())+'.plist');archive.parent.mkdir(mode=0o700,parents=True,exist_ok=True);path.rename(archive)


def install(locked=False):
    c=config();identity(c)
    if not (BASE/'app/scheduler.py').is_file():raise RuntimeError('Scheduler source is not installed; update program first')
    if not locked and busy():raise RuntimeError('A briefing worker is active; wait before changing its service')
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    label=agent_label();path=Path.home()/'Library/LaunchAgents'/(label+'.plist');path.parent.mkdir(parents=True,exist_ok=True)
    original=path.read_bytes() if path.exists() else None
    was_loaded=subprocess.run(['launchctl','print','gui/'+str(os.getuid())+'/'+label],capture_output=True).returncode==0
    if original:
        backup=ROOT/'agent-backups'/(str(time.time_ns())+'.plist');backup.parent.mkdir(mode=0o700,parents=True,exist_ok=True);backup.write_bytes(path.read_bytes());backup.chmod(0o600)
    stop()
    value={'Label':label,'ProgramArguments':[c['python'],str(BASE/'app/scheduler.py'),'--tick'],'WorkingDirectory':str(BASE),
        'EnvironmentVariables':{'WECHAT_ASSISTANT_HOME':str(BASE)},'RunAtLoad':True,'StartInterval':30,
        'StartCalendarInterval':[{'Hour':0,'Minute':15},{'Hour':8,'Minute':0},{'Hour':9,'Minute':0}],
        'StandardOutPath':str(ROOT/'launchd.stdout.log'),'StandardErrorPath':str(ROOT/'launchd.stderr.log'),'Umask':0o077,'ProcessType':'Background'}
    data=plistlib.dumps(value);fd,temp=tempfile.mkstemp(dir=path.parent,prefix='.wechat-scheduler-')
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(data)
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    try:
        subprocess.run(['launchctl','bootstrap','gui/'+str(os.getuid()),str(path)],capture_output=True,check=True)
        subprocess.run(['launchctl','print','gui/'+str(os.getuid())+'/'+label],capture_output=True,check=True)
    except BaseException:
        subprocess.run(['launchctl','bootout','gui/'+str(os.getuid())+'/'+label],capture_output=True)
        archived=ROOT/'agent-backups'/(str(time.time_ns())+'-failed.plist');archived.parent.mkdir(mode=0o700,parents=True,exist_ok=True);path.rename(archived)
        if original:
            path.write_bytes(original);path.chmod(0o600)
            if was_loaded:subprocess.run(['launchctl','bootstrap','gui/'+str(os.getuid()),str(path)],capture_output=True,check=True)
        raise
    return {'label':label,'plist':str(path),'backend':'launchd'}


if __name__=='__main__':
    os.umask(0o077)
    parser=argparse.ArgumentParser();parser.add_argument('--tick',action='store_true');parser.add_argument('--inspect',action='store_true')
    parser.add_argument('--work',choices=['prepare','refresh','deliver','fallback','cleanup']);parser.add_argument('--day');parser.add_argument('--binding')
    try:
        args=parser.parse_args()
        result=worker(args.work,args.day,args.binding) if args.work else tick(args.inspect)
        if result is not None:print(json.dumps(result,ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'status':'failed','error':type(error).__name__,'message':str(error)},ensure_ascii=False),file=sys.stderr);sys.exit(2)
