from typing import Union, Dict, Tuple, List, Any
from collections.abc import AsyncIterator
import logging
_logger = logging.getLogger(__name__)

import os
from pathlib import Path
from asyncio import sleep
from time import time as timestamp

from anyio import Path as aPath

from .models import JobSpec, JobAttributes, JobState
from .statfile import append_csv, create_file
from .job import Job
import psik.templates as templates

class JobManager:
    """ The JobManager class manages all job (directories) listed
        inside its prefix.  It can allocate new directory names,
        create job layouts inside a directory, and list all valid
        job directories.

        The last path component of the prefix
        must be a valid backend name -- which this manager
        (and its associated jobs) work with exclusively.

        If set, default job attributes are filled in for
        all jobs that do not have those attributes set already.
    """
    def __init__(self, prefix : Union[str,Path], backend : str,
                       defaults : JobAttributes = JobAttributes()):
        assert Path(prefix).is_dir(), "JobManager: prefix is not a dir"
        assert backend.count("/") == 0 and backend.count("\\") == 0, \
                    "Invalid backend name."
        templates.check(backend) # verify all templates are present

        pre = (Path(prefix) / backend).resolve()
        pre.mkdir(exist_ok=True)
        assert os.access(pre, os.W_OK)

        self.prefix = aPath(pre)
        self.backend  = backend
        self.defaults = defaults

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

    def _insert_defaults(self, attr : JobAttributes) -> None:
        """ Merge JobManager.defaults into .defaults into
            the JobAttributes structure.  This way JobSpec-s
            don't have to keep entering their project-id, etc.
        """
        for key, val in attr.model_dump().items():
            if val is None:
                val = getattr(self.defaults, key)
                if val is not None:
                    setattr(attr, key, val)
            if len(attr.custom_attributes) == 0 \
                    and len(self.defaults.custom_attributes) > 0:
                attr.custom_attributes.update(
                        self.defaults.custom_attributes)

    async def create(self, jobspec : JobSpec) -> Job:
        """Create a new job from the given JobSpec

           This function renders job templates,
           then calls create_job.
        """
        base = await self._alloc(jobspec) # allocate a base dir for this job
        self._insert_defaults(jobspec.attributes)
        data : Dict[str,Any] = {
                'job': jobspec.model_dump(),
                'base': str(base)
               }
        #  Replaces `data[job.attributes.custom_attributes]`
        #  with its key/val pairs specific to the backend in use.
        custom1 = jobspec.attributes.custom_attributes.get(self.backend, {})
        custom = [ {'key': k, 'value': v} for k, v in custom1.items() ]
        data['job']['attributes']['custom_attributes'] = custom
        
        tpl = templates.render_all(self.backend, templates.actions, data)

        return await create_job(base, jobspec, **tpl)

    async def ls(self) -> AsyncIterator[Job]:
        """ Async generator of Job entries.
        """
        async for jobdir in self.prefix.iterdir():
            if await (jobdir / 'spec.json').is_file():
                try:
                    yield await Job(jobdir)
                except Exception as e:
                    _logger.info("Unable to load %s", jobdir, exc_info=e)

async def create_job(base : aPath, jobspec : JobSpec,
                     submit : str, cancel : str, job : str) -> Job:
    """ Create job files from layout info.

            Fills out the "base / " subdirectory:
               - spec.json
               - status.csv
               - scripts/(pre_submit on_* submit cancel job run)
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
                      prepare_script(jobspec.script), 0o755)
    #(base/'scripts'/'run').unlink(missing_ok=True)
    default_action = "#!/usr/bin/env rc\n"
    for state in [JobState.active, JobState.completed,
                  JobState.failed, JobState.canceled]:
        action = jobspec.events.get(state, default_action)
        await create_file(base/'scripts'/f'on_{state.value}',
                          prepare_script(action), 0o755)
    await create_file(base/'scripts'/'pre_submit',
                      prepare_script(jobspec.pre_submit), 0o755)
    # log completion of 'new' status
    await append_csv(base/'status.csv', timestamp(), 0, 'new', 0)
    return await Job(base)

def prepare_script(s):
    if not s.startswith("#!"):
        s = "#!/usr/bin/env rc\n" + s
    if not s.endswith("\n"):
        s = s + "\n"
    return s
