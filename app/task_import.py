#!/usr/bin/env python3
"""Local, owner-reviewed import. No model, network, source instructions or sends."""
import argparse,csv,fcntl,hashlib,io,json,os,re,secrets,sqlite3,sys,time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from local_memory import BASE,config,fingerprint,import_tasks
from history_reader import private_write

FIELDS={'title':('title','事项','任务','标题'),'contact':('contact','联系人','对接人'),
        'topic':('topic','项目','主题'),'category':('category','责任','分类'),
        'due_original':('due','due_original','日期','期限'),'details':('details','说明','详情')}
CATEGORIES={'self':'self','我来处理':'self','我来做':'self','followup':'followup','等对方推进':'followup','等对方':'followup','confirm':'confirm','待确认':'confirm','需要确认':'confirm'}


def rows_from_text(text,kind):
    if not isinstance(text,str) or not text.strip() or len(text.encode())>1_000_000:raise ValueError('请输入非空文本，文件不超过1MB。')
    if kind=='json':
        values=json.loads(text)
        if isinstance(values,dict):values=values.get('tasks')
        if not isinstance(values,list) or any(not isinstance(x,dict) for x in values):raise ValueError('JSON需要任务对象数组，或包含tasks数组。')
    elif kind=='csv':
        values=list(csv.DictReader(io.StringIO(text.lstrip('\ufeff'))))
    elif kind in ('text','txt','md'):
        values=[]
        for line in text.splitlines():
            if not line.strip() or line.lstrip().startswith('#') or re.fullmatch(r'\s*[-=]{3,}\s*',line):continue
            original=line.strip()
            title=re.sub(r'^\s*(?:(?:[-*•]|\d+[.、)])\s+)?(?:\[[ xX]\]\s*)?','',original).strip()
            contact=''
            if '｜' in title:contact,title=title.split('｜',1)
            values.append({'title':title,'contact':contact,'details':original})
    else:raise ValueError('仅支持粘贴文本、TXT、Markdown、CSV或JSON。')
    if not 1<=len(values)<=200:raise ValueError('一次导入1到200项；请先整理为每行一条。')
    result=[]
    for index,value in enumerate(values):
        row={'row_id':index,'selected':True,'status':'open','new_instance':False}
        for field,aliases in FIELDS.items():
            row[field]=str(next((value[k] for k in aliases if k in value and value[k] is not None),'' )).strip()
        if not row['title']:raise ValueError('第'+str(index+1)+'行缺少事项名称。CSV请使用title或事项列。')
        row['category']=CATEGORIES.get(row['category'],'self')
        row['topic']=row['topic'] or '其他事项'
        if len(row['title'])>200 or len(row['details'])>2500:raise ValueError('第'+str(index+1)+'项过长，请拆成具体事项后再导入。')
        result.append(row)
    return result


def existing_tasks(c):
    path=BASE/'memory'/fingerprint(c)/'memory.sqlite'
    if not path.exists():return []
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2);db.row_factory=sqlite3.Row
    try:return [dict(r) for r in db.execute('SELECT * FROM tasks')]
    finally:db.close()


def duplicate(rows,item):
    normalize=lambda s:re.sub(r'\s+','',s).casefold()
    return next((row for row in rows if normalize(row['title'])==normalize(item['title'])
        and not (row.get('topic') and item.get('topic') and normalize(row['topic'])!=normalize(item['topic']))
        and not (row.get('contact') and item.get('contact') and normalize(row['contact'])!=normalize(item['contact']))),None)


def execute(value):
    c=config()
    if not c.get('reader_verified') or not c.get('original_app_confirmed'):raise ValueError('请先完成本人微信读取验证，再导入待办。')
    folder=BASE/'imports';folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    if value.get('action')=='preview':
        text=value.get('text','');kind=value.get('format','text');rows=rows_from_text(text,kind)
        old=existing_tasks(c)
        for row in rows:
            found=duplicate(old,row)
            row['existing_status']=found['status'] if found else None
        token=secrets.token_hex(16);source=folder/(hashlib.sha256(text.encode()).hexdigest()+'.source.json')
        if not source.exists():private_write(source,{'name':Path(value.get('source_name','粘贴内容')).name,'format':kind,'text':text})
        state={'token':token,'binding':fingerprint(c),'at':int(time.time()),'source':str(source),
            'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'rows':rows,'status':'preview'}
        private_write(folder/(token+'.json'),state)
        return {'token':token,'rows':rows,'total':len(rows),'duplicates':sum(r['existing_status'] is not None for r in rows),
            'notice':'来源中的完成标记不会自动生效。请逐项核对；已有事项保留原状态，需同名的不同事项请补充项目或修改标题。'}
    if value.get('action')!='commit' or value.get('owner_confirmed') is not True:raise ValueError('请先预览并本人确认保存。')
    token=value.get('token','')
    if not re.fullmatch('[a-f0-9]{32}',token):raise ValueError('导入预览凭据无效。')
    with (folder/'import.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        path=folder/(token+'.json');state=json.loads(path.read_text())
        if state['binding']!=fingerprint(c):raise ValueError('账号已变化，请重新预览。')
        if state['status']=='committed':return state['result']
        if int(time.time())-state['at']>86400:raise ValueError('预览已过期，请重新预览。')
        if hashlib.sha256(Path(state['source']).read_bytes()).hexdigest()!=state['source_sha256']:raise ValueError('来源已变化，请重新预览。')
        rows=value.get('rows',[])
        if not isinstance(rows,list) or not 1<=len(rows)<=200:raise ValueError('没有选中可保存的事项。')
        seen=set();reviewed=[]
        for row in rows:
            number=row.get('row_id')
            if not isinstance(number,int) or number<0 or number>=len(state['rows']) or number in seen:raise ValueError('预览行已变化。')
            seen.add(number)
            if row.get('selected') is False:continue
            item={key:str(row.get(key,'')).strip() for key in FIELDS}
            item.update(row_id=number,status=row.get('status','open'),new_instance=row.get('new_instance') is True)
            if not 1<=len(item['title'])<=200 or len(item['details'])>2500 or len(item['due_original'])>200:raise ValueError('事项名称、说明或日期过长。')
            if item['category'] not in ('self','followup','confirm') or item['status'] not in ('open','done'):raise ValueError('请选择有效责任及完成状态。')
            if len(item['contact'])>200 or len(item['topic'])>30 or re.search(r'[\r\n\[\]（）]',item['topic']+item['contact']):raise ValueError('联系人和项目必须是简短单行文字。')
            reviewed.append(item)
        if not reviewed:raise ValueError('请至少选择一项。')
        receipt=folder/(token+'.review.json')
        if receipt.exists():
            previous=json.loads(receipt.read_text())
            if previous['rows']!=reviewed or previous['source_sha256']!=state['source_sha256']:raise ValueError('保存已开始，不能修改这次确认内容；请重新预览。')
        else:private_write(receipt,{'owner_reviewed_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                'source':state['source'],'source_sha256':state['source_sha256'],'rows':reviewed})
        digest=hashlib.sha256(receipt.read_bytes()).hexdigest();items=[]
        for row in reviewed:
            key=hashlib.sha256((state['source_sha256']+':'+str(row['row_id'])+':'+row['title']+':'+row['category']+':'+row['topic']+':'+row['contact']).encode()).hexdigest()
            if row['new_instance']:key+=':'+token
            items.append({**{k:row[k] for k in FIELDS},'import_key':'reviewed:'+key,'new_instance':row['new_instance'],'owner_confirmed_status':row['status'],
                'provenance':{'kind':'owner_import','path':str(receipt),'sha256':digest,'locator':'本人确认的第'+str(row['row_id']+1)+'项',
                    'original_source':state['source'],'original_sha256':state['source_sha256']}})
        result=import_tasks(items,c,reviewed=True)
        result.update(selected=len(reviewed),message='已保存；重复事项保留原完成状态。')
        state.update(status='committed',result=result);private_write(path,state)
        return result


if __name__=='__main__':
    os.umask(0o077)
    try:print(json.dumps(execute(json.load(sys.stdin)),ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'error':type(error).__name__,'message':str(error)},ensure_ascii=False));sys.exit(2)
