"""Strict, bounded /proc maps snapshots with read-only transient retries.

Never skip an unknown record or synthesize permissions/address coverage.
Only format failures are retried; permission and I/O errors propagate.

Phone-VM /proc emulation (虚拟大师) has produced lines whose head was cut off,
leaving only the tail of a well-formed row. Such a fragment is excluded and
never becomes a readable range; only anonymous or system-property memory may
be excluded this way, because file-backed mappings back ownership proofs.
The same VM appends its own mappings after [stack], relabelled as
[anon:libc_malloc] and out of address order (one with its start address cut
to "67000-78be576000"). Such out-of-order anonymous rows are excluded too;
an out-of-order row naming a file still fails.
Its /proc layer also re-emits the last stretch of the file after [stack],
starting mid-line. A line that is an exact copy, or the tail, of a row
already accepted carries no new mapping and is dropped as a replay.
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


MAX_FRAGMENTS=64
MAX_REPLAYED=2048
_HEX=r'[0-9a-fA-F]'
_TAIL=r'(?P<dev>{h}{{1,8}}:{h}{{1,8}})\s+(?P<inode>[0-9]{{1,20}})(?:\s+(?P<name>.*))?'.format(h=_HEX)
# A row "start-end perms offset major:minor inode [name]" cut somewhere before
# its inode: the first token is the tail of the end address, of the
# permissions, of the offset or of the device. A token that still contains
# "start-end" is a complete (possibly unordered) row, never a fragment.
_FRAGMENTS=(
    re.compile(r'{h}{{1,16}}\s+[r-][w-][x-][ps]\s+{h}{{1,16}}\s+'.format(h=_HEX)+_TAIL),
    re.compile(r'(?:[ps]|[x-][ps]|[w-][x-][ps]|[r-][w-][x-][ps])\s+{h}{{1,16}}\s+'.format(h=_HEX)+_TAIL),
    re.compile(r'{h}{{1,16}}\s+'.format(h=_HEX)+_TAIL),
    re.compile(r'(?:{h}{{0,8}}:)?{h}{{1,8}}\s+(?P<inode>[0-9]{{1,20}})(?:\s+(?P<name>.*))?'.format(h=_HEX)),
)
_EXCLUDABLE_NAME=re.compile(r'|\[anon:[^\]\n]{0,96}\]|\[heap\]|\[stack(?::[0-9]{1,10})?\]|/dev/__properties__/u:object_r:[a-zA-Z0-9_]+:s0')


def _truncated_fragment(line):
    """Tail of a well-formed row whose head was lost. Metadata only.

    No start/end address can be recovered, so it is NEVER converted to a
    readable range. File-backed names are not excludable: dropping one could
    make an owned component look unmapped.
    """
    for pattern in _FRAGMENTS:
        match=pattern.fullmatch(line)
        if match:return _EXCLUDABLE_NAME.fullmatch((match.group('name') or '').strip()) is not None
    return False


def parse(text,*,excluded=None):
    if not isinstance(text,str) or len(text)>MAX_TEXT:
        raise MapsSnapshotError('process maps snapshot exceeds bounds',dict(reason='size'))
    rows=text.splitlines()
    if not rows or len(rows)>MAX_ROWS:
        raise MapsSnapshotError('process maps snapshot is empty or exceeds row bounds',dict(reason='row_count'))
    result=[];previous=0;excluded_count=0;replayed_count=0;offset=0;joined=None
    for index,line in enumerate(rows,1):
        line_offset=offset;offset+=len(line.encode('utf-8'))+1
        parts=line.split(maxsplit=5)
        formed=(len(parts)>=5 and re.fullmatch(r'[0-9a-fA-F]{1,16}-[0-9a-fA-F]{1,16}',parts[0])
               and re.fullmatch(r'[r-][w-][x-][ps]',parts[1])
               and re.fullmatch(r'[0-9a-fA-F]{1,16}',parts[2])
               and re.fullmatch(r'[0-9a-fA-F]{1,8}:[0-9a-fA-F]{1,8}',parts[3])
               and re.fullmatch(r'[0-9]{1,20}',parts[4]))
        valid=bool(formed)
        if valid:
            low,high=(int(value,16) for value in parts[0].split('-'))
            valid=(0<=low<high<=1<<64 and low>=previous)
        if not valid:
            context=dict(line_number=index,byte_offset=line_offset,line_sha256=hashlib.sha256(line.encode('utf-8')).hexdigest(),
                         line_preview=line[:240],previous_preview=rows[index-2][:240] if index>1 else '',
                         next_preview=rows[index][:240] if index<len(rows) else '')
            if joined is None or joined[0]!=len(result):
                joined=(len(result),'\n'+'\n'.join(row[5] for row in result)+'\n')
            # line+newline can only match inside one accepted row, at its end.
            # A blank line counts only when it opens such a replay (the next
            # line is itself a copy of an accepted row) or is the VM's extra
            # final newline after the complete list.
            following=rows[index] if index<len(rows) else None
            if line:replay=line+'\n' in joined[1]
            elif following is None:replay=bool(result)
            else:replay=bool(result and following and following+'\n' in joined[1])
            if replay:
                replayed_count+=1
                if replayed_count>MAX_REPLAYED:
                    raise MapsSnapshotError('too many replayed map lines',dict(reason='replay_limit',**context))
                if excluded is not None and replayed_count<=16:
                    excluded.append(dict(reason='replayed_line',authorized_range=False,**context))
                continue
            name=(parts[5] if len(parts)==6 else '').strip()
            unordered=formed and low<high and _EXCLUDABLE_NAME.fullmatch(name) is not None
            if unordered or _truncated_fragment(line):
                excluded_count+=1
                if excluded_count>MAX_FRAGMENTS:
                    raise MapsSnapshotError('too many truncated map fragments',dict(reason='fragment_limit',**context))
                if excluded is not None:
                    excluded.append(dict(reason='unordered_anonymous_row' if unordered else 'head_truncated_fragment',
                                         authorized_range=False,**context))
                continue
            detail=dict(reason='invalid_or_unordered_row',
                        tail_preview=[row[:200] for row in rows[max(0,index-4):index+48]],**context)
            raise MapsSnapshotError('process maps contains an invalid row at line '+str(index),detail)
        result.append((low,high,parts[1],int(parts[2],16),parts[5] if len(parts)==6 else '',line))
        previous=high
    if not result:
        raise MapsSnapshotError('no complete process mappings remain',dict(reason='no_complete_ranges'))
    if excluded is not None and replayed_count:
        excluded.append(dict(reason='replayed_line_total',authorized_range=False,count=replayed_count))
    return result


def _read_whole(path):
    """Whole file with as few read() calls as possible, bounded by the cap.

    Unbuffered, each call asks for everything still allowed: VM /proc layers
    were seen to lose the head of a line between two small reads. The call
    sizes are kept as evidence. /proc pseudo-files report zero stat size, so
    stat size never authorizes an unbounded read.
    """
    chunks=[];total=0
    with path.open('rb',buffering=0) as stream:
        while total<=MAX_TEXT:
            chunk=stream.read(MAX_TEXT+1-total)
            if not chunk:break
            chunks.append(chunk);total+=len(chunk)
    data=''.join(chunks) if chunks and isinstance(chunks[0],str) else b''.join(chunks).decode('utf-8')
    return data,[len(chunk) for chunk in chunks[:64]]


def read_snapshot(path):
    failures=[]
    for attempt in range(1,4):
        text,calls=_read_whole(path)
        excluded=[]
        try:
            rows=parse(text,excluded=excluded)
        except MapsSnapshotError as exc:
            failures.append(dict(attempt=attempt,read_calls=calls,read_bytes=len(text),**exc.detail))
            continue
        if failures or excluded:
            _remember(dict(signature=hashlib.sha256(repr([(e['reason'],e.get('line_sha256')) for e in excluded]).encode()).hexdigest()[:16],recovered=True,attempts=attempt,failures=failures,read_calls=calls,
                           excluded_fragments=excluded,complete_ranges=len(rows)))
        # An excluded fragment must not reach another parser that might
        # accidentally interpret its suffix as an address. Keep complete rows
        # byte-for-byte; do not sort, infer a missing range, or close a gap.
        return ('\n'.join(row[5] for row in rows)+('\n' if text.endswith('\n') else '')) if excluded else text
    report=dict(recovered=False,attempts=3,failures=failures)
    _remember(report)
    raise MapsSnapshotError('连续3次读取游戏内存映射格式异常；未跳过异常行、未使用异常映射继续操作，请导出诊断',report)


def _remember(report):
    """Keep failures always; collapse repeated recoveries so they cannot crowd one out."""
    for kept in _REPORTS:
        if report.get('recovered') and kept.get('signature')==report.get('signature'):
            kept['occurrences']=kept.get('occurrences',1)+1;return
    if len(_REPORTS)>=8:
        recovered=[kept for kept in _REPORTS if kept.get('recovered')]
        if not report.get('recovered') and recovered:_REPORTS.remove(recovered[0])
        elif not report.get('recovered'):_REPORTS.pop(0)
        else:return
    _REPORTS.append(report)


def diagnostics():
    return dict(schema='royale-replay.proc-maps-diagnostic.v3',read_only=True,
                skipped_rows=sum(len(r.get('excluded_fragments',[])) for r in _REPORTS),
                unknown_rows_skipped=0,excluded_records_authorize_memory=False,
                reports=list(_REPORTS)) if _REPORTS else None
