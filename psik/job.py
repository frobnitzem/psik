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

from .models import JobSpec, JobState, Callback, Transition, BackendConfig
from .statfile import read_csv, append_csv
from .exceptions import InvalidJobException, SubmitException, CallbackException
from .web import post_json
from .console import run_shebang, runcmd
from .templates import submit_at, cancel_at, poll_at

class Job:
    backend: BackendConfig

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
        self.backend = BackendConfig.model_validate_json(self.history[0].info)
        self.valid = True
        return self

    async def reached(self, jobndx: int, state: JobState,
                      info: str = "", fyi: bool = False) -> bool:
        """ Mark job as having reached the given jobndx,state.
            info is usually the job_id (when known).

            If the `fyi` parameter is True, no callbacks
            will be triggered.  Also, the history will only
            be updated if the transition is not yet present.

            May throw CallbackException.
        """
        t = timestamp()
        data  = Transition(time=t, jobndx=jobndx, state=state, info=info)
        if fyi: # filter out this transition if already seen
            if not self.valid:
                await self.read_info()
            for trs in self.history:
                if trs.jobndx == jobndx and trs.state == state:
                    return False
        self.history.append( data )
        await append_csv(self.base / 'status.csv', *data.fields())
        if fyi:
            return True

        if not self.valid:
            spec = await (self.base/'spec.json').read_text(
                                                    encoding='utf-8')
            self.spec = JobSpec.model_validate_json(spec)

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
                msg = f"{self.spec.callback} <- {cb}"
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
        native_job_id = await submit_at(self.backend.type, self, jobndx)
        if native_job_id is None:
            raise SubmitException("")

        try:
            await self.reached(jobndx, JobState.queued, native_job_id)
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
        await self.reached(jobndx, JobState.active)

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

        if retcode == 0:
            await self.reached(jobndx, JobState.completed)
        else:
            await self.reached(jobndx, JobState.failed, ret)

        return retcode

    async def poll(self) -> JobState:
        if not self.valid:
            await self.read_info()
        ans = await poll_at(self.backend.type, [self.stamp])
        return ans[0]

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
            await cancel_at(self.backend.type, ids)
