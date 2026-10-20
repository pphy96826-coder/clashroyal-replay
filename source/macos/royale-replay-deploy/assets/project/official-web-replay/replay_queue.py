"""Immutable queued HTML; only pure parsing runs alongside a native replay."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import uuid


class ReplayQueue:
    def __init__(self, directory):
        self.directory=Path(directory)/'replay-queue'
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.lock=threading.RLock()
        self.index=self.directory/'index.json'
        self.items=json.loads(self.index.read_text(encoding='utf-8')) if self.index.exists() else []
        for row in self.items:
            if row['state']=='parsing':row['state']='queued'
            elif row['state']=='playing':row['state']='interrupted'
        self.save()

    def save(self):
        fd,name=tempfile.mkstemp(prefix='queue-',suffix='.tmp',dir=self.directory)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as out:json.dump(self.items,out,ensure_ascii=False)
            os.replace(name,self.index)
        finally:
            if os.path.exists(name):os.unlink(name)

    def snapshot(self):
        with self.lock:return json.loads(json.dumps(self.items))

    def add(self, html):
        path=Path(html).expanduser().resolve()
        evidence=None
        if path.name.endswith('.diagnostic.json'):
            if not path.is_file() or not 0<path.stat().st_size<=4*1024*1024:raise ValueError('诊断证据过大或不存在')
            evidence=json.loads(path.read_text(encoding='utf-8'))
            from diagnostic_prefix import preview_inputs
            preview_inputs(evidence['preparation'],evidence['report'],evidence['receipt'],authorized=evidence.get('user_authorized') is True)
            path=path.with_name(path.name.removesuffix('.diagnostic.json')+'.html')
        if not path.is_file() or path.suffix.lower() not in ('.html','.htm') or not 0<path.stat().st_size<=25*1024*1024:
            raise ValueError('队列只接受25MB以内的HTML文件')
        raw=path.read_bytes()
        if not 0<len(raw)<=25*1024*1024:raise ValueError('读取期间文件大小发生变化')
        if evidence and hashlib.sha256(raw).hexdigest()!=evidence['source_sha256']:raise ValueError('诊断原HTML不符')
        with self.lock:
            if len(self.items)>=128 or sum(row['bytes'] for row in self.items)+len(raw)>256*1024*1024:
                raise ValueError('队列上限128场或256MB，请先移除已完成记录')
            key=uuid.uuid4().hex
            with (self.directory/(key+'.html')).open('xb') as out:out.write(raw)
            row=dict(id=key,name=path.name,sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),state='queued')
            if evidence:
                data=json.dumps(evidence,ensure_ascii=False).encode()
                with (self.directory/(key+'.diagnostic.json')).open('xb') as out:out.write(data)
                row.update(diagnostic_only=True,diagnostic_sha256=hashlib.sha256(data).hexdigest(),name=path.name+'（未完成诊断预览）')
            self.items.append(row);self.save();return dict(row)

    def source(self, key):
        if not isinstance(key,str) or len(key)!=32 or any(c not in '0123456789abcdef' for c in key):
            raise ValueError('invalid queue ID')
        with self.lock:
            row=next(r for r in self.items if r['id']==key)
            path=self.directory/(key+'.html')
            if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('队列HTML校验不符')
            return path

    def set_state(self,key,state,**details):
        with self.lock:
            row=next(r for r in self.items if r['id']==key)
            row.update(details,state=state);self.save()

    def diagnostic(self,key):
        self.source(key)
        with self.lock:
            row=next(r for r in self.items if r['id']==key)
            if not row.get('diagnostic_only'):return None
            raw=(self.directory/(key+'.diagnostic.json')).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=row['diagnostic_sha256']:raise ValueError('队列诊断证据已改变')
            value=json.loads(raw)
            if value.get('source_sha256')!=row['sha256'] or value.get('user_authorized') is not True:raise ValueError('队列诊断授权不符')
            return value

    def next_ready(self):
        with self.lock:
            # Preserve order: do not jump over a file still being parsed.
            for row in self.items:
                if row['state'] in ('queued','parsing'):return None
                if row['state']=='ready':return dict(row)
            return None
