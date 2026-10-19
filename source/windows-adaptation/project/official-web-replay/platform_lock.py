"""Nonblocking interprocess file locks: Windows msvcrt or POSIX fcntl."""
import errno
import os
LOCK_EX=2
LOCK_NB=4

def flock(file,flags):
    if flags!=LOCK_EX|LOCK_NB:raise ValueError('only nonblocking exclusive locks supported')
    if os.name=='nt':
        import msvcrt
        # Do not read byte0: another Windows process may hold a mandatory
        # byte-range lock there. fstat is safe before the nonblocking lock.
        if os.fstat(file.fileno()).st_size==0:file.write(b'\0');file.flush()
        file.seek(0)
        try:msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as error:
            if error.errno in (errno.EACCES,errno.EAGAIN,errno.EDEADLK):raise BlockingIOError('lock is already held') from error
            raise
    else:
        import fcntl
        fcntl.flock(file,fcntl.LOCK_EX|fcntl.LOCK_NB)
