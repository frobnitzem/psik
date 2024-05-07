from typing import Union, Dict, Tuple, List, Optional, Set
from io import StringIO
import logging
_logger = logging.getLogger(__name__)

import asyncio
from pathlib import Path
from time import time as timestamp

from anyio import Path as aPath

from .models import JobSpec, JobState, Callback
from .statfile import read_csv, append_csv
from .exceptions import InvalidJobException, SubmitException
from .web import post_json

class Job:
    def __init__(self, base : Union[str, Path, aPath]):
        """ Construct a job from the information
            in its base directory (filesystem path).

            Note: This class is not fully initialized
                  with actual job metadata until it is `await`-ed.
                  This allows for all I/O to be asynchronous.
        """
        base = aPath(base)
        self.base = base
        self.stamp = str(base.name)

        self.valid = False
        self.spec = JobSpec(script="")
        self.history : List[Tuple[float,int,JobState,int]] = []

    # Await this class to read metadata from the filesystem.
    def __await__(self):
        return self.read_info().__await__()

    async def read_info(self) -> 'Job':
        """ Asynchronously read all job metadata from the filesystem.
        """
        base = self.base
        spec = await (base/'spec.json').read_text(encoding='utf-8')
        self.spec = JobSpec.model_validate_json(spec)
        history = await read_csv(base / 'status.csv')
        self.history = self.history[:0]
        for step in history: # parse history
            try:
                self.history.append(( float(step[0]), int(step[1]),
                                      JobState(step[2]), int(step[3]) ))
            except Exception as e:
                _logger.error("%s: Invalid row in status.csv: %s",
                              self.stamp, step)
        self.valid = True
        return self

    async def reached(self, jobndx : int, state : JobState,
                      info : int = 0) -> bool:
        """ Mark job as having reached the given state.
            info is usually the job_id (when known).
        """
        t = timestamp()
        data  = (t, jobndx, state, info)
        data1 = (t, jobndx, state.value, info)
        self.history.append( data )
        await append_csv(self.base / 'status.csv', *data1)
        if not self.valid:
            base = self.base
            spec = await (base/'spec.json').read_text(encoding='utf-8')
            self.spec = JobSpec.model_validate_json(spec)
        if self.spec.callback is not None:
            cb = Callback(jobndx = jobndx, state = state, info = info)
            token = None
            if self.spec.cb_secret:
                token = self.spec.cb_secret.get_secret_value()
            return await post_json(self.spec.callback,
                                   cb.model_dump_json(),
                                   token) is not None
        return True

    def summarize(self) -> Tuple[int, Dict[JobState, Set[int]]]:
        """ Sort jobndx values by JobState.
            
            returns (next available jobndx, mapping from state to jobndx)
        """
        jobndx = 1

        status : Dict[JobState, Set[int]] = \
                 dict( (s, set()) for s in JobState )
        del status[JobState.new]
        for t, ndx, state, info in self.history:
            if ndx >= jobndx:
                jobndx = ndx+1
            if state in status:
                status[state].add(ndx)

        # TODO: sanity checks to ensure jobs passed through queued
        # before reaching other states, cancelled/failed/completed
        done = status[JobState.canceled] \
             | status[JobState.failed]    \
             | status[JobState.completed]
        status[JobState.queued] -= status[JobState.active] | done
        status[JobState.active] -= done
        return jobndx, status

    async def submit(self) -> Tuple[int,int]:
        """ Run the job's submit script.
            Return the job's jobndx and native_job_id.
        """
        if not self.valid:
            await self.read_info()

        jobndx, _ = self.summarize()

        ret, out, err = await runcmd(str(self.base / 'scripts' / 'submit'), str(jobndx))
        if ret != 0:
            raise SubmitException(err)
        try:
            native_job_id = int(out)
        except Exception:
            _logger.error('%s: submit script returned unparsable result: %s',
                          self.stamp, out)
            native_job_id = 0
        await self.reached(jobndx, JobState.queued, native_job_id)
        return jobndx, native_job_id

    async def cancel(self) -> None:
        # Prevent a race condition by recording this first.
        await self.reached(0, JobState.canceled)
        #if not ok:
        #    raise InvalidJobException("Unable to update job status.")
        await self.read_info()

        native_ids = {}
        for t, ndx, state, info in self.history:
            if state == JobState.queued:
                native_ids[ndx] = info
            elif state == JobState.completed:
                del native_ids[ndx]
            elif state == JobState.failed:
                del native_ids[ndx]

        ids = [str(job_id) for ndx, job_id in native_ids.items()]
        if len(ids) > 0:
            ret, out, err = await runcmd(str(self.base / 'scripts' / 'cancel'),
                                         *ids)
            if ret != 0:
                raise SubmitException(err)

async def runcmd(prog : Union[Path,str], *args : str,
                 cwd : Union[Path,str,None] = None,
                 expect_ok : Optional[bool] = True) -> Tuple[int,str,str]:
    """Run the given command inside an asyncio subprocess.
       
       Returns (return code : int, stdout : str, stderr : str)
    """
    pipe = asyncio.subprocess.PIPE
    proc = await asyncio.create_subprocess_exec(
                    prog, *args, cwd=cwd,
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
