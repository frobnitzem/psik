from typing import Union, Dict, Tuple, List, Optional
from io import StringIO
import logging
_logger = logging.getLogger(__name__)

import asyncio
from pathlib import Path
from time import time as timestamp

from .models import JobSpec
from .statfile import read_csv, append_csv

class Job:
    def __init__(self, base : Union[str, Path], read_info=True):
        """ Note: read_info must be True unless you
            only plan to call reached() and nothing else.
        """
        base = Path(base)
        self.base = base
        self.stamp = str(base.name)

        self.valid = False
        self.spec = JobSpec(script="")
        self.history : List[Tuple[float,int,str,int]] = []

        if read_info:
            self.read_info()

    def read_info(self):
        base = self.base
        spec = (base/'spec.json').read_text(encoding='utf-8')
        self.spec = JobSpec.model_validate_json(spec)
        history = read_csv(base / 'status.csv')
        self.history = self.history[:0]
        for step in history: # parse history
            self.history.append( (
                    float(step[0]), int(step[1]), step[2], int(step[3])) )
        self.valid = True

    def reached(self, jobndx : int, state : str, info=0):
        """ Mark job as having reached the given state.
            info is usually the job_id (when known).
        """
        t = timestamp()
        data = (t, jobndx, state, info)
        self.history.append( data )
        append_csv(self.base / 'status.csv', *data)

    def summarize(self):
        jobndx = 1

        status = {
            'queued'    : set(),
            'active'    : set(),
            'cancelled' : set(),
            'failed'    : set(),
            'completed' : set()
        }
        for t, ndx, state, info in self.history:
            if ndx >= jobndx:
                jobndx = ndx+1
            if state in status:
                status[state].add(ndx)

        status['queued'] -= status['active']
        status['active'] -= status['cancelled'] \
                          | status['failed']    \
                          | status['completed']
        return jobndx, status

    async def submit(self) -> bool:
        """Run pre_submit script (if applicable)
           and then the submit script.
        """
        if not self.valid:
            self.read_info()

        pre_submit = self.base / 'scripts' / 'pre_submit'
        if len(self.history) == 1 and pre_submit.exists():
            ret, out, err = await runcmd(str(pre_submit))
        if ret != 0:
            return False

        jobndx, _ = self.summarize()

        ret, out, err = await runcmd(str(self.base / 'scripts' / 'submit'), str(jobndx))
        if ret != 0:
            return False
        try:
            native_job_id = int(out)
        except Exception:
            _logger.error('%s: submit script returned unparsable result', self.stamp)
            native_job_id = -1
        self.reached(jobndx, 'queued', native_job_id)
        return True

    async def cancel(self) -> bool:
        # Prevent a race condition by recording this first.
        self.reached(0, 'canceled')
        self.read_info()

        native_ids = {}
        for t, ndx, state, info in self.history:
            if state == 'queued':
                native_ids[ndx] = info
            elif state == 'completed':
                del native_ids[ndx]
            elif state == 'failed':
                del native_ids[ndx]

        ids = [str(job_id) for ndx, job_id in native_ids.items()]
        if len(ids) > 0:
            ret, out, err = await runcmd(str(self.base / 'scripts' / 'cancel'), *ids)
            if ret != 0:
                return False
        on_canceled = self.base / 'scripts' / 'on_canceled'
        if on_canceled.exists():
            ret, out, err = await runcmd(str(on_canceled))
        return ret == 0

async def runcmd(prog : Union[Path,str], *args : str,
                 expect_ok : Optional[bool] = True) -> Tuple[int,str,str]:
    """Run the given command inside an asyncio subprocess.
       
       Returns (return code : int, stdout : str, stderr : str)
    """
    pipe = asyncio.subprocess.PIPE
    proc = await asyncio.create_subprocess_exec(
                    prog, *args,
                    stdout=pipe, stderr=pipe)
    stdout, stderr = await proc.communicate()
    # note stdout/stderr are binary

    out = stdout.decode('utf-8')
    err = stderr.decode('utf-8')
    if len(stdout) > 0:
        _logger.debug('%s stdout: %s', prog, out)
    if len(stderr) > 0:
        _logger.info('%s stderr: %s', prog, err)

    ret = -1
    if proc.returncode is not None:
        ret = proc.returncode
    if expect_ok != (proc.returncode == 0):
        _logger.error('%s returned %d', prog, ret)
    if expect_ok is None:
        _logger.info('%s returned %d', prog, ret)

    return ret, out, err
