from pathlib import Path
from fcntl import flock, LOCK_UN, LOCK_SH, LOCK_EX, LOCK_NB

class FLock:
    def __init__(self, fd, flags):
        self.fd, self.op = fd, flags

    def __enter__(self):
        flock(self.fd, self.op)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        flock(self.fd, LOCK_UN)

class ReadLock(FLock):
    """ReadLock context manager based on
       https://github.com/misli/python-flock

       Example:

       with open('/tmp/file.lock', 'r') as f:
         with ReadLock(f):
           pass # do something here

         try:
           with noblocking_lock:
             pass # do something else here
         except BlockingIOError:
           pass
    """

    def __init__(self, fd, blocking=True):
        flags = LOCK_SH
        if blocking:
            flags |= LOCK_NB
        super().__init__(fd, flags)

class WriteLock(FLock):
    """WriteLock context manager based on
       https://github.com/misli/python-flock

       Example:

       with open('/tmp/file.lock', 'w') as f:
         with WriteLock(f):
           pass # do something here

         try:
           with WriteLock(f, False):
             pass # do something else here
         except BlockingIOError:
           pass
    """

    def __init__(self, fd, blocking=True):
        flags = LOCK_EX
        if blocking:
            flags |= LOCK_NB
        super().__init__(fd, flags)

def append_csv(f, *vals):
    if isinstance(f, str) or isinstance(f, Path):
        with open(f, 'a', encoding='utf-8') as f2:
            with WriteLock(f2):
                f2.write(','.join(map(str, vals)) + '\n')
    else:
        with WriteLock(f):
            f.write(','.join(map(str, vals)) + '\n')

def read_csv(f):
    if isinstance(f, str) or isinstance(f, Path):
        with open(f, 'r', encoding='utf-8') as f2:
            with ReadLock(f2):
                lines = f2.readlines()
    else:
        with ReadLock(f):
            lines = f.readlines()
    return [ l.strip().split(',') for l in lines ]

def create_file(name : Path, content : str, perm=None):
    with name.open('w', encoding='utf-8') as f:
        name.chmod(perm)
        f.write(content)
