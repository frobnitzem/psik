from typing import Union, Dict, Tuple, List, Optional, Set
from io import StringIO
import os
import sys
import logging
_logger = logging.getLogger(__name__)

import asyncio
from pathlib import Path
from time import time as timestamp

from anyio import Path as aPath

from .models import (
    JobSpec,
    JobState,
    Callback,
    Transition,
    BackendConfig,
    ExtraInfo,
)
from .statfile import read_csv, append_csv, WriteLock, open_file
from .exceptions import InvalidJobException, SubmitException, CallbackException
from .web import post_json
from .console import run_shebang, runcmd
from .backend import submit_at, cancel_at, poll_at

class Job:
    info: ExtraInfo

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
        self.history : List[Transition] = []

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
                self.history.append(Transition(time=float(step[0]),
                                               jobndx=int(step[1]),
                                               state=JobState(step[2]),
                                               info=step[3],
                                   ))
            except Exception as e:
                _logger.error("%s: Invalid row in status.csv: %s",
                              self.stamp, step)
        self.info = ExtraInfo.model_validate_json(self.history[0].info)
        self.valid = True
        return self

    async def reached(self, jobndx: int, state: JobState,
                      info: str = "", backdate: Optional[float] = None) -> bool:
        """ Mark job as having reached the given jobndx,state.
            info is usually the job_id (when known).

            If the `backdate` parameter is set, it will be recorded
            as the transition time, and no callbacks will be triggered.
            This follows the convention that whoever collects the
            timestamp runs the callback.

            May throw CallbackException.
        """
        if backdate is None:
            t = timestamp()
        else:
            t = backdate
        data  = Transition(time=t, jobndx=jobndx, state=state, info=info)
        #if backdate is not None: # filter out this transition if already seen
        #    if not self.valid:
        #        await self.read_info()
        #    for trs in self.history:
        #        if trs.jobndx == jobndx and trs.state == state:
        #            return False
        self.history.append( data )
        await append_csv(self.base / 'status.csv', *data.fields())
        if backdate is not None:
            return True

        if not self.valid:
            spec = await (self.base/'spec.json').read_text(
                                                    encoding='utf-8')
            self.spec = JobSpec.model_validate_json(spec)
        return await self.send_callback(jobndx, state, info)

    async def send_callback(self,
                            jobndx: int,
                            state: JobState,
                            info: str) -> bool:
        token = None
        if self.spec.cb_secret:
            token = self.spec.cb_secret.get_secret_value()
        if self.spec.callback is not None:
            cb = Callback(jobid = self.stamp,
                          jobndx = jobndx,
                          state = state,
                          info = info)
            token = None
            if self.spec.cb_secret:
                token = self.spec.cb_secret.get_secret_value()
            try:
                return await post_json(self.spec.callback,
                                       cb.model_dump_json(),
                                       token) is not None
            except Exception as e:
                msg = f"{cb} POST to {self.spec.callback}"
                raise CallbackException(msg) from e
        return True

    def summarize(self) -> Tuple[int, Dict[JobState, Set[int]]]:
        """ Sort jobndx values by JobState.
            
            returns (next available jobndx, mapping from state to jobndx)
        """
        jobndx = 1 # largest jobndx seen plus 1

        status : Dict[JobState, Set[int]] = \
                 dict( (s, set()) for s in JobState )
        del status[JobState.new]
        for t in self.history:
            ndx = t.jobndx
            if ndx >= jobndx:
                jobndx = ndx+1
            if t.state in status:
                status[t.state].add(ndx)

        # TODO: sanity checks to ensure jobs passed through queued
        # before reaching other states, cancelled/failed/completed
        done = status[JobState.canceled] \
             | status[JobState.failed]    \
             | status[JobState.completed]
        status[JobState.queued] -= status[JobState.active] | done
        status[JobState.active] -= done
        return jobndx, status

    async def submit(self) -> Tuple[int,str]:
        """ Run the job's submit script.
            Return the job's jobndx and native_job_id.
        """
        if not self.valid:
            await self.read_info()

        jobndx, _ = self.summarize()
        # inline some of self.reached so that we can
        # submit with the file lock held.
        async with await open_file(self.base/'status.csv', 'a',
                                   encoding='utf-8') as f:
            async with WriteLock(f):
                t0 = timestamp()
                native_job_id = await submit_at(self.info.backend.type, self, jobndx)
                if native_job_id is None:
                    raise SubmitException("Job submission failed.")
                trs = Transition(time=t0,
                                 jobndx=jobndx,
                                 state=JobState.queued,
                                 info=native_job_id)
                await f.write(','.join(map(str, trs.fields())) + '\n')
        self.history.append(trs)
        try:
            await self.send_callback(jobndx, JobState.queued, native_job_id)
        except CallbackException as e:
            _logger.error("%s: Error sending callback: %s",
                              self.stamp, e)

        return jobndx, native_job_id

    async def execute(self, jobndx: int, **env_vars) -> int:
        """ Hot start sets up the environment variables,
            then invokes self.spec.script.

            It records the script return code as success
            or failure.
        """
        try:
            await self.reached(jobndx, JobState.active)
        except CallbackException as e:
            _logger.error("%s: Error sending callback: %s", self.stamp, e)

        cwd = Path()
        try:
            if not self.valid:
                await self.read_info()

            # TODO: expand vars like $SLURM_JOB_NUM_NODES
            os.chdir(str(self.spec.directory))
            env = dict(self.spec.environment)
            env.update(env_vars)
            # should set mpirun and nodes here too...
            env["jobndx"] = str(jobndx)
            env["base"] = str(self.base)

            stdout_path = self.base/"log"/f"stdout.{jobndx}"
            stderr_path = self.base/"log"/f"stderr.{jobndx}"

            retcode = run_shebang(self.spec.script,
                                  str(stdout_path),
                                  str(stderr_path),
                                  timeout=self.spec.resources.duration,
                                  env=env)
            ret = str(retcode)
        except Exception as e:
            retcode = 7
            ret = f"psik.hot_start error: {e}"
        finally:
            os.chdir(str(cwd))

        try:
            if retcode == 0:
                await self.reached(jobndx, JobState.completed)
            else:
                await self.reached(jobndx, JobState.failed, ret)
        except CallbackException as e:
            _logger.error("%s: Error sending callback: %s", self.stamp, e)

        return retcode

    async def poll(self) -> None:
        if not self.valid:
            await self.read_info()
        await poll_at(self.info.backend.type, self)

    async def cancel(self) -> None:
        # Prevent a race condition by recording this first.
        await self.reached(0, JobState.canceled)
        #if not ok:
        #    raise InvalidJobException("Unable to update job status.")
        await self.read_info()

        native_ids: Dict[int,str] = {}
        for t in self.history:
            ndx = t.jobndx
            state = t.state
            if state == JobState.queued:
                native_ids[ndx] = t.info
            elif state == JobState.completed:
                del native_ids[ndx]
            elif state == JobState.failed:
                del native_ids[ndx]

        ids = [job_id for ndx, job_id in native_ids.items()]
        if len(ids) > 0:
            await cancel_at(self.info.backend.type, ids)
