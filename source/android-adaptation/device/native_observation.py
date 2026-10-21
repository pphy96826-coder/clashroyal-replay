"""Bounded source result reads with distinct empty/oversize diagnostics."""
import json

MAX_SOURCE_BYTES=262144


def source_json(address,size,read_memory,details):
    if type(size) is not int or size<0:raise ValueError('invalid native source result size')
    if size==0:raise ValueError('原生执行结果为空；source_error='+str(details.get('native_source_error','unknown'))+
        '，watched_towers='+str(details.get('watched_towers','unknown'))+'；未提交播放')
    if size>MAX_SOURCE_BYTES:raise ValueError('原生执行结果超出读取上限：'+str(size)+' > '+str(MAX_SOURCE_BYTES))
    if type(address) is not int or address<=0:raise ValueError('invalid native source result address')
    raw=read_memory(address,size)
    if len(raw)!=size:raise ValueError('short native source result read')
    value=json.loads(raw.decode('utf-8'))
    if not isinstance(value,dict):raise ValueError('native source result must be an object')
    return value
