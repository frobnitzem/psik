from typing import Union, Dict, Tuple, List, Any, Optional
from collections.abc import AsyncIterator
import logging
_logger = logging.getLogger(__name__)

import os
from pathlib import Path
from asyncio import sleep
from time import time as timestamp

from anyio import Path as aPath

from .models import JobSpec, BackendConfig, JobState
from .statfile import append_csv, create_file
from .job import Job
from .config import Config
import psik.templates as templates

class JobManager:
    """ The JobManager class manages all job (directories) listed
        inside its prefix.  It can allocate new directory names,
        create job layouts inside a directory, and list all valid
        job directories.

        The last path component of the prefix
        must be a valid backend system name -- which this manager
        (and its associated jobs) work with exclusively.

        If set, default job attributes are filled in for
        all jobs that do not have those attributes set already.
    """
    def __init__(self, config: Config) -> None:
        assert Path(config.prefix).is_dir(), "JobManager: prefix is not a dir"
        for btype in set([b.type for b in config.backends.values()]):
            templates.check(btype) # verify all templates are present

        pre = Path(config.prefix).resolve()
        pre.mkdir(exist_ok=True)
        assert os.access(pre, os.W_OK)

        self.prefix = aPath(pre)
        self.config = config

    async def _alloc(self, jobspec : JobSpec) -> aPath:
        """Allocate a new path where a job can be created.

           Set jobspec.directory if None.
        """
        while True:
            # Note: This naming convention limits jobs to 1000/second
            # which is probably too many actually.
            base = self.prefix / ("%.3f"%round(timestamp(), 3))
            try:
                await base.mkdir()
                break
            except FileExistsError:
                await sleep(0.001)

        # Ensure working directory exists.
        if jobspec.directory is None:
            workdir = base / 'work'
            await workdir.mkdir()
            jobspec.directory = str(workdir)

        return base

    async def create(self, jobspec: JobSpec,
                           base: Optional[aPath] = None) -> Job:
        """Create a new job from the given JobSpec

           This function renders job templates,
           then calls create_job.

           If base is specified, any path at that directory
           is overwritten.
        """
        if base is None: # allocate a base dir for this job
            base = await self._alloc(jobspec)
        else:
            await base.mkdir(exist_ok=True)
        backend = self.config.backends[jobspec.backend]

        data : Dict[str,Any] = {
                'job': jobspec.model_dump(),
                'base': str(base),
                'stamp': base.name,
                'psik': self.config.psik_path,
                'rc': self.config.rc_path
               }
        #  Replaces `data[job.backend.attributes]`
        #  with its key/val pairs specific to the backend in use.
        data['job']['backend'] = backend.model_dump()
          # backend's default attributes
        attr = data['job']['backend']['attributes']
          # override any specifically set jobspec.attributes
        attr.update(jobspec.attributes)
        # re-format so it can be traversed by the view
        del data['job']['attributes']
        data['job']['backend']['attributes'] = [
                 {'key': k, 'value': v} for k, v in attr.items()
             ]
        
        tpl = templates.render_all(backend.type, templates.actions, data)

        return await create_job(base, jobspec, self.config.rc_path, **tpl)

    async def ls(self) -> AsyncIterator[Job]:
        """ Async generator of Job entries.
        """
        jobs = []
        async for jobdir in self.prefix.iterdir():
            jobs.append(jobdir)
        jobs.sort()
        for jobdir in jobs:
            if await (jobdir / 'spec.json').is_file():
                try:
                    yield await Job(jobdir)
                except Exception as e:
                    _logger.info("Unable to load %s", jobdir, exc_info=e)

async def create_job(base : aPath, jobspec : JobSpec, rc_path : str,
                     submit : str, cancel : str, job : str) -> Job:
    """ Create job files from layout info.

            Fills out the "base / " subdirectory:
               - spec.json
               - status.csv
               - scripts/(submit cancel job run)
               - empty work/ and log/ directories
    """
    assert await base.is_dir()
    assert jobspec.directory is not None and \
            await aPath(jobspec.directory).is_dir()
    await (base/'scripts').mkdir()
    await (base/'log').mkdir()
    await create_file(base/'spec.json', jobspec.model_dump_json(indent=4), 0o644)
    await create_file(base/'scripts'/'submit', submit, 0o755)
    await create_file(base/'scripts'/'cancel', cancel, 0o755)
    await create_file(base/'scripts'/'job', job, 0o755)
    await create_file(base/'scripts'/'run',
                      prepare_script(jobspec.script, rc_path), 0o755)
    #(base/'scripts'/'run').unlink(missing_ok=True)
    # log completion of 'new' status
    await append_csv(base/'status.csv', timestamp(), 0, 'new', 0)
    return await Job(base)

def prepare_script(s : str, rc_path : str) -> str:
    if not s.startswith("#!"):
        s = f"#!{rc_path}\n" + s
    if not s.endswith("\n"):
        s = s + "\n"
    return s
