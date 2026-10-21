"""Read-only libdl discovery from ELF segment geometry, never the first VMA.

Only maps belonging to the freshly bound game are considered. A path is not
proof: every load segment, ELF header/program table and required export must
agree with the live object. Ambiguity or an unavailable read budget fails closed.
"""
import hashlib
import os
from pathlib import Path


class LoaderResolutionError(ValueError):
    def __init__(self, reason, diagnostic):
        self.diagnostic = diagnostic
        super().__init__('system loader verification failed: '+reason+
                         '; see loader-diagnostic.json (before native execution)')


def loader_groups(lines, library='libdl.so'):
    if len(lines) > 65536:
        raise ValueError('too many process mappings')
    groups = {}
    for line in lines:
        fields = line.split(None, 5)
        if len(fields) != 6 or Path(fields[5]).name != library:
            continue
        path = fields[5]
        if not path.startswith('/') or '\x00' in path:
            continue
        low, high = (int(value, 16) for value in fields[0].split('-'))
        offset = int(fields[2], 16)
        inode = int(fields[4])
        mode = fields[1]
        if not 0 < low < high or offset < 0 or len(mode) != 4 or inode <= 0:
            raise ValueError('invalid file-backed loader mapping')
        # Kernel file identity joins aliases but never unrelated libdl copies.
        group = groups.setdefault((fields[3], inode), dict(identity=(fields[3], inode), paths=set(), rows=[]))
        group['paths'].add(path)
        group['rows'].append((low, high, offset, mode))
    if len(groups) > 8:
        raise ValueError('too many loader objects')
    return list(groups.values())


def covered(rows, start, size, offset, executable=False):
    end = start+size
    cursor = start
    for low, high, file_offset, mode in sorted(rows):
        if high <= cursor:
            continue
        if low > cursor or 'r' not in mode or (executable and 'x' not in mode):
            return False
        if file_offset+cursor-low != offset+cursor-start:
            return False
        cursor = min(end, high)
        if cursor == end:
            return True
    return False


def load_biases(rows, elf, page):
    if page not in (4096, 16384, 65536):
        raise ValueError('unsupported system page size')
    segments = [p for p in elf.programs if p[0] == 1 and p[5]]
    if not segments or len(rows) > 128:
        raise ValueError('invalid loader load segments')
    candidates = set()
    for p in segments:
        if p[5] > p[6] or p[2] % page != p[3] % page:
            raise ValueError('invalid loader segment geometry')
        elf.slice(p[2], p[5])
        first = p[2]//page*page
        last = (p[2]+p[5]+page-1)//page*page
        for low, high, offset, mode in rows:
            if first <= offset < last:
                candidates.add(low-(p[3]//page*page+offset-first))
    valid = []
    for bias in sorted(candidates):
        if bias <= 0 or bias % page:
            continue
        if all(covered(rows, bias+p[3], p[5], p[2], bool(p[1] & 1)) for p in segments):
            valid.append(bias)
    return valid


def read_elf_file(path):
    # Bound the file read too, even if the VM exposes an unexpected libdl path.
    with Path(path).open('rb') as stream:
        before = os.fstat(stream.fileno())
        if not 64 <= before.st_size <= 128*1024*1024:
            raise ValueError('unbounded loader file')
        raw = stream.read(before.st_size+1)
        after = os.fstat(stream.fileno())
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or len(raw) != before.st_size:
        raise ValueError('loader file changed')
    return raw


def resolve_loader(session, elf_type, page=None, read_file=read_elf_file,
                   library='libdl.so', names=('dlopen', 'dlclose', 'dlerror')):
    """Same proof for libdl (dlopen) and, on VMs, libc's allocator exports."""
    page = os.sysconf('SC_PAGE_SIZE') if page is None else page
    original = session.verify()
    groups = loader_groups(original.splitlines(), library)
    diagnostic = dict(schema=1, page_size=page, mapped_objects=len(groups),
                      candidates=[], native_calls=False, game_memory_written=False)
    # Equivalent file aliases get deduplicated by bytes and mapped object/bias.
    choices = {}
    for number, group in enumerate(groups):
        note = dict(paths=sorted(group['paths']), mapping_count=len(group['rows']),
                    zero_offset_rows=sum(row[2] == 0 for row in group['rows']), files=[])
        diagnostic['candidates'].append(note)
        seen = set()
        for path in sorted(group['paths']):
            # /proc/<pid>/root handles an existing target mount namespace. No
            # map_files access, root-policy change or permission bypass is used.
            for source in (path, str(session.proc/'root')+path):
                entry = dict(source=source)
                note['files'].append(entry)
                try:
                    raw = read_file(source)
                    digest = hashlib.sha256(raw).hexdigest()
                    if digest in seen:
                        entry['result'] = 'duplicate file alias'
                        continue
                    seen.add(digest)
                    elf = elf_type(raw)
                    exports = elf.exports(set(names))
                    biases = load_biases(group['rows'], elf, page)
                    entry.update(result='ELF checked', load_bias_candidates=len(biases))
                    for bias in biases:
                        if len(choices) >= 4:
                            raise LoaderResolutionError('too many verified-layout candidates', diagnostic)
                        checks = [(bias, raw[:64]),
                                  (bias+elf.phoff, elf.slice(elf.phoff, len(elf.programs)*56))]
                        # Header/program table must be the same file at VA 0.
                        if not covered(group['rows'], bias, 64, 0) or not covered(
                                group['rows'], bias+elf.phoff, len(elf.programs)*56, elf.phoff):
                            entry['result'] = 'header is not mapped at ELF base'
                            continue
                        pins = {}
                        for name, pin in exports.items():
                            va = int(pin['va'], 0)
                            parts = [p for p in elf.programs if p[0] == 1 and p[1] & 1
                                     and p[3] <= va and va+pin['size'] <= p[3]+p[5]]
                            if len(parts) != 1 or not covered(group['rows'], bias+va, pin['size'],
                                    parts[0][2]+va-parts[0][3], True):
                                raise ValueError('loader export not uniquely executable')
                            pins[name] = dict(pin, address=hex(bias+va))
                            checks.append((bias+va, elf.at(va, pin['size'])))
                        if any(len(expected) > 4096 for address, expected in checks):
                            raise ValueError('loader verification range too large')
                        # Reserve room for the caller's final owner observations.
                        if session.used+sum(len(data) for _, data in checks) > 61440:
                            raise LoaderResolutionError('bounded read budget exhausted', diagnostic)
                        live = session.read_many([(address, len(data)) for address, data in checks])
                        if any(actual != expected for actual, (_, expected) in zip(live, checks)):
                            entry['result'] = 'live loader bytes differ'
                            continue
                        choices[(number, bias, digest)] = dict(identity=session.identity,
                            library=source, library_sha256=digest, base=hex(bias), exports=pins)
                        entry['result'] = 'live fingerprints verified'
                except LoaderResolutionError:
                    raise
                except (OSError, ValueError) as exc:
                    # No raw addresses, whole process map or unrelated app data.
                    entry['result'] = type(exc).__name__
                    if isinstance(exc, OSError):
                        entry['errno'] = exc.errno
                    else:
                        entry['reason'] = str(exc)[:160]
    if loader_groups(session.verify().splitlines(), library) != groups:
        raise LoaderResolutionError('loader mappings changed during verification', diagnostic)
    diagnostic['verified_candidates'] = len(choices)
    if len(choices) != 1:
        raise LoaderResolutionError('verified candidates='+str(len(choices))+
                                    ', mapped objects='+str(len(groups)), diagnostic)
    return next(iter(choices.values())), diagnostic
