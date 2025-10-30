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

           This function creates the job directory,
           merges backend.attributes with job.attributes,
           then calls create_job.

           If base is specified, any path at that directory
           is overwritten.
        """
        if base is None: # allocate a base dir for this job
            base = await self._alloc(jobspec)
        else:
            await base.mkdir(exist_ok=True)
        backend = self.config.backends[jobspec.backend]

        # override any specifically set jobspec.attributes
        attr = dict(backend.attributes)
        attr.update(jobspec.attributes)
        jobspec.attributes = attr

        return await create_job(base, jobspec, backend.model_dump_json())

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

async def create_job(base : aPath, jobspec : JobSpec,
                     backend: str) -> Job:
    """ Create job files from layout info.

            Fills out the "base / " subdirectory:
               - spec.json
               - status.csv
               - empty work/ and log/ directories
    """
    assert await base.is_dir()
    assert jobspec.directory is not None and \
            await aPath(jobspec.directory).is_dir()
    await (base/'scripts').mkdir()
    await (base/'log').mkdir()
    await create_file(base/'spec.json', jobspec.model_dump_json(indent=4), 0o644)
    # log completion of 'new' status
    await append_csv(base/'status.csv', timestamp(), 0, 'new', backend)
    return await Job(base)
