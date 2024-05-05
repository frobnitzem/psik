from typing import Union, Dict, Tuple, List, Any
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
    def __init__(self, config : Config):
        assert Path(config.prefix).is_dir(), "JobManager: prefix is not a dir"
        templates.check(config.backend.type) # verify all templates are present

        pre = Path(config.prefix).resolve()
        pre.mkdir(exist_ok=True)
        assert os.access(pre, os.W_OK)

        self.prefix = aPath(pre)
        self.backend_t = config.backend.type
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

    def _insert_defaults(self, attr : BackendConfig) -> None:
        """ Merge JobManager.config.backend into
            the BackendConfig structure `attr`.  This way JobSpec-s
            don't have to keep entering their project-id, etc.
        """
        defaults = self.config.backend
        for key, val in attr.model_dump().items():
            if val is None:
                val = getattr(defaults, key)
                if val is not None:
                    setattr(attr, key, val)
            if len(attr.attributes) == 0 and len(defaults.attributes) > 0:
                attr.attributes.update(defaults.attributes)

    async def create(self, jobspec : JobSpec) -> Job:
        """Create a new job from the given JobSpec

           This function renders job templates,
           then calls create_job.
        """
        base = await self._alloc(jobspec) # allocate a base dir for this job
        self._insert_defaults(jobspec.backend)
        data : Dict[str,Any] = {
                'job': jobspec.model_dump(),
                'base': str(base),
                'psik': self.config.psik_path,
                'rc': self.config.rc_path
               }
        #  Replaces `data[job.backend.attributes]`
        #  with its key/val pairs specific to the backend_type in use.
        data['job']['backend']['attributes'] = [
                 {'key': k, 'value': v} for k, v in \
                     jobspec.backend.attributes.items()
             ]
        
        tpl = templates.render_all(self.backend_t, templates.actions, data)

        return await create_job(base, jobspec, self.config.rc_path, **tpl)

    async def ls(self) -> AsyncIterator[Job]:
        """ Async generator of Job entries.
        """
        async for jobdir in self.prefix.iterdir():
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
