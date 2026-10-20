"""Strict, bounded /proc maps snapshots with read-only transient retries.

Never skip an unknown record or synthesize permissions/address coverage.
Only format failures are retried; permission and I/O errors propagate.
"""
import hashlib
import re

MAX_TEXT=4*1024*1024
MAX_ROWS=32768
_REPORTS=[]


class MapsSnapshotError(ValueError):
    def __init__(self,message,detail):
        super().__init__(message)
        self.detail=detail


def _truncated_readonly_property(parts):
    """Recognize metadata only; no start/end address can be recovered from it.

    The known VM record contains just a hexadecimal suffix instead of an
    address range. It is NEVER converted to a readable range, including when
    the name happens to contain permission-policy terminology.
    """
    return (len(parts)==6 and re.fullmatch(r'[0-9a-fA-F]{1,16}',parts[0])
            and parts[1]=='r--s' and re.fullmatch(r'0{1,16}',parts[2])
            and re.fullmatch(r'[0-9a-fA-F]{1,8}:[0-9a-fA-F]{1,8}',parts[3])
            and re.fullmatch(r'[0-9]{1,20}',parts[4])
            and re.fullmatch(r'/dev/__properties__/u:object_r:[a-zA-Z0-9_]+:s0',parts[5]))


def parse(text,*,excluded=None):
    if not isinstance(text,str) or len(text)>MAX_TEXT:
        raise MapsSnapshotError('process maps snapshot exceeds bounds',dict(reason='size'))
    rows=text.splitlines()
    if not rows or len(rows)>MAX_ROWS:
        raise MapsSnapshotError('process maps snapshot is empty or exceeds row bounds',dict(reason='row_count'))
    result=[];previous=0;excluded_count=0
    for index,line in enumerate(rows,1):
        parts=line.split(maxsplit=5)
        valid=(len(parts)>=5 and re.fullmatch(r'[0-9a-fA-F]{1,16}-[0-9a-fA-F]{1,16}',parts[0])
               and re.fullmatch(r'[r-][w-][x-][ps]',parts[1])
               and re.fullmatch(r'[0-9a-fA-F]{1,16}',parts[2])
               and re.fullmatch(r'[0-9a-fA-F]{1,8}:[0-9a-fA-F]{1,8}',parts[3])
               and re.fullmatch(r'[0-9]{1,20}',parts[4]))
        if valid:
            low,high=(int(value,16) for value in parts[0].split('-'))
            valid=(0<=low<high<=1<<64 and low>=previous)
        if not valid:
            if _truncated_readonly_property(parts):
                excluded_count+=1
                if excluded_count>32:
                    raise MapsSnapshotError('too many truncated property records',dict(reason='property_record_limit'))
                if excluded is not None:
                    excluded.append(dict(reason='truncated_read_only_property_record',authorized_range=False,
                        line_number=index,line_sha256=hashlib.sha256(line.encode('utf-8')).hexdigest(),line_preview=line[:240]))
                continue
            detail=dict(reason='invalid_or_unordered_row',line_number=index,
                        line_sha256=hashlib.sha256(line.encode('utf-8')).hexdigest(),line_preview=line[:240])
            raise MapsSnapshotError('process maps contains an invalid row at line '+str(index),detail)
        result.append((low,high,parts[1],int(parts[2],16),parts[5] if len(parts)==6 else '',line))
        previous=high
    if not result:
        raise MapsSnapshotError('no complete process mappings remain',dict(reason='no_complete_ranges'))
    return result


def read_snapshot(path):
    failures=[]
    for attempt in range(1,4):
        # Read at most the cap plus one character. /proc pseudo-files report
        # zero stat size, so do not use stat size to authorize an unbounded read.
        with path.open('r',encoding='utf-8') as stream:text=stream.read(MAX_TEXT+1)
        excluded=[]
        try:
            rows=parse(text,excluded=excluded)
        except MapsSnapshotError as exc:
            failures.append(dict(attempt=attempt,**exc.detail))
            continue
        if failures or excluded:
            _remember(dict(recovered=True,attempts=attempt,failures=failures,
                           excluded_property_records=excluded,complete_ranges=len(rows)))
        # A malformed property record must not reach another parser that might
        # accidentally interpret its suffix as an address. Keep complete rows
        # byte-for-byte; do not sort, infer a missing range, or close a gap.
        return ('\n'.join(row[5] for row in rows)+('\n' if text.endswith('\n') else '')) if excluded else text
    report=dict(recovered=False,attempts=3,failures=failures)
    _remember(report)
    raise MapsSnapshotError('连续3次读取游戏内存映射格式异常；未跳过异常行、未使用异常映射继续操作，请导出诊断',report)


def _remember(report):
    if len(_REPORTS)<8:_REPORTS.append(report)


def diagnostics():
    return dict(schema='royale-replay.proc-maps-diagnostic.v2',read_only=True,
                skipped_rows=sum(len(r.get('excluded_property_records',[])) for r in _REPORTS),
                unknown_rows_skipped=0,excluded_records_authorize_memory=False,
                reports=list(_REPORTS)) if _REPORTS else None
