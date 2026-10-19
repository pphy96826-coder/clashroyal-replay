"""Find one ELF load bias from all file-backed PT_LOAD segments, including aliases."""

PAGE=4096


def load_bias(lines,path,elf,file_offset=0,anchor=None):
    rows=[]
    for line in lines:
        fields=line.split()
        if len(fields)<6 or fields[-1]!=path:continue
        low,high=(int(v,16) for v in fields[0].split('-'))
        rows.append((low,high,int(fields[2],16),fields[1]))
    segments=[p for p in elf.programs if p[0]==1 and p[5]]
    if not rows or not segments:raise ValueError('mapped ELF has no file-backed load segments')
    candidates={low-(p[3]//PAGE)*PAGE for low,high,offset,mode in rows for p in segments
        if offset==file_offset+(p[2]//PAGE)*PAGE}
    valid=[]
    for bias in candidates:
        if bias<=0 or bias%PAGE:continue
        if anchor is not None and bias+anchor[0]!=anchor[1]:continue
        okay=True
        for p in segments:
            start=bias+p[3];end=start+p[5];covered=start
            for low,high,offset,mode in sorted(rows):
                if high<=covered:continue
                if low>covered or 'r' not in mode:break
                if offset+covered-low!=file_offset+p[2]+covered-start:break
                covered=min(high,end)
                if covered==end:break
            if covered!=end:okay=False;break
        if okay:valid.append(bias)
    if len(valid)!=1:raise ValueError('ELF load bias absent or ambiguous after segment verification')
    return valid[0]


def game_mapping(lines,apk,profile,translated=False):
    mode='r--p' if translated else 'r-xp'
    rows=[line for line in lines if len(line.split())>=6 and line.split()[1]==mode
        and int(line.split()[2],16)==profile['mapping_file_offset'] and line.split()[-1]==apk]
    if len(rows)!=1:raise ValueError('installed APK mapping changed; require new binary identification')
    low,high=(int(value,16) for value in rows[0].split()[0].split('-'))
    if high-low!=profile['executable_span']:raise ValueError('library extent changed')
    return low,high,rows[0]
