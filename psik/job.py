from typing import Union, Dict, Tuple, List
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
            out = await runcmd(str(pre_submit))
        if isinstance(out, int):
            _logger.error('Error in pre_submit script.')
            return False

        jobndx, _ = self.summarize()

        out = await runcmd(str(self.base / 'scripts' / 'submit'), str(jobndx))
        if isinstance(out, int):
            _logger.error('Error submitting job.')
            return False
        native_job_id = int(out)
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
            out = await runcmd(str(self.base / 'scripts' / 'cancel'), *ids)
            if isinstance(out, int):
                _logger.error('cancel script returned %d', out)
                return False
        on_canceled = self.base / 'scripts' / 'on_canceled'
        if on_canceled.exists():
            out = await runcmd(str(on_canceled))
        if isinstance(out, int):
            _logger.error('on_canceled callback returned %d', out)
            return False
        return True

async def runcmd(prog, *args, ret=True, outfile=None):
    """Run the given command inside an asyncio subprocess.
    """
    stdout = None
    stderr = None
    if ret:
        stdout = asyncio.subprocess.PIPE
    if outfile:
        # TODO: consider https://pypi.org/project/aiofiles/
        f = open(outfile, 'ab')
        stdout = f
        stderr = f
    proc = await asyncio.create_subprocess_exec(
                    prog, *args,
                    stdout=stdout, stderr=stderr)
    stdout, stderr = await proc.communicate()
    # note stdout/stderr are binary
    if outfile:
        f.close()

    if ret and proc.returncode == 0:
        return stdout
    return proc.returncode
