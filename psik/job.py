from typing import Union, Dict

import os
import asyncio
from pathlib import Path
import importlib.resources
from functools import cache
from time import sleep
from time import time as timestamp

import pystache

from .models import JobSpec, JobAttributes
from .statfile import read_csv, append_csv, create_file

class Job:
    def __init__(self, base : Union[str, Path], read_info=True):
        """ Note: read_info must be True unless you
            only plan to call reached() and nothing else.
        """
        self.base = Path(base)
        self.stamp = base.name

        if read_info:
            spec = (base/'spec.json').read_text(encoding='utf-8')
            self.spec = JobSpec.model_validate_json(spec)
            self.history = read_csv(base / 'status.csv')
            for step in self.history: # parse history
                step[0] = float(step[0])
                step[1] = int(step[1])
                step[3] = int(step[3])
        else:
            self.spec = None
            self.history = []

    def reached(self, jobidx : int, state : str, info=0):
        """ Mark job as having reached the given state.
            info is usually the job_id (when known).
        """
        t = timestamp()
        append_csv(self.base / 'status.csv', t, state, info)
        self.history.append( [t, jobidx, state, info] )

    async def submit(self) -> bool:
        # subst must be run from a cache-directory
        #Path(self.config.cachedir).chdir()
        # ensure run-script exists, otherwise call subst to create it.
        out = await runcmd(str(self.base / 'scripts' / 'submit.rc'))
        if isinstance(out, int):
            return False
        native_job_id = int(out)
        self.reached(0, 'queued', native_job_id)
        return True

@cache
def read_template(backend, act):
    s = importlib.resources.read_text(__package__ + '.templates',
                                      f"{backend}-{act}.rc")
    return pystache.parse(s)

template_types = ['submit', 'cancel', 'job']

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
    def __init__(self, prefix : Union[str,Path],
                       defaults : JobAttributes = JobAttributes()):
        self.prefix = Path(prefix).resolve()
        # TODO: assert prefix is writable
        self.backend = self.prefix.name
        self.defaults = defaults

        for act in template_types:
            try:
                read_template(self.backend, act)
            except FileNotFoundError:
                raise KeyError(f"'{self.backend}' backed is missing a template for {act}.")

        assert self.prefix.is_dir(), "JobManager: prefix is not a dir"

    def _alloc(self, jobspec : JobSpec) -> Path:
        """Allocate a new path where a job can be created.

           Set jobspec.directory if None.
        """
        while True:
            base = self.prefix / str(round(timestamp(), 3))
            try:
                base.mkdir()
                break
            except FileExistsError:
                time.sleep(0.001)

        if jobspec.directory is None:
            workdir = base / 'work'
            workdir.mkdir()
            jobspec.directory = str(workdir)

        return base

    def _insert_defaults(self, attr : JobAttributes):
        for key, val in attr.model_dump().items():
            if val is None:
                val = getattr(self.defaults, key)
                if val is not None:
                    setattr(attr, key, val)
            if len(attr.custom_attributes) == 0 \
                    and len(self.defaults.custom_attributes) > 0:
                attr.custom_attributes.update(
                        self.defaults.custom_attributes)

    def create(self, jobspec : JobSpec) -> Job:
        """Create a new job from the given JobSpec

           This function renders job templates,
           then calls create_job.
        """
        base = self._alloc(jobspec) # allocate a base dir for this job
        self._insert_defaults(jobspec.attributes)
        templates = dict((act, read_template(self.backend, act)) \
                          for act in ['submit', 'cancel', 'job'])
        # note: can specify partials={'script': script},
        # note: alt. escape fn: "'" + x.replace("'", "''") + "'",
        r = pystache.Renderer(
                    escape=lambda x: x,
                    missing_tags='strict'
        )
        data = {'job': jobspec.model_dump(),
                'base': str(base)
               }
        custom = data['job']['attributes']['custom_attributes'].get(
                                    self.backend, {})
        data['job']['attributes']['custom_attributes'] = \
          [ {'key': k, 'value': v} for k, v in custom ]
        for act, v in templates.items():
            templates[act] = r.render(v, data)

        return create_job(base, jobspec, **templates)

    # populate a list of jobs
    def ls(self) -> Dict[str, Job]:
        jobs = {}
        for jobdir in self.prefix.glob("*"):
            if (jobdir / 'spec.json').exists():
                try:
                    jobs[jobdir.name] = Job(jobdir)
                except Exception as e:
                    print("Unable to load ", jobdir, ":")
                    print(e)
        return jobs

def create_job(base : Path, jobspec : JobSpec,
               submit : str, cancel : str, job : str) -> Job:
    """ Create job files from layout info.

            Fills out the "base / " subdirectory:
               - spec.json
               - status.csv
               - on_*.rc
               - scripts/(submit.rc cancel.rc job.rc run)
               - empty work/ and out/ directories
    """
    assert base.is_dir()
    assert Path(jobspec.directory).is_dir()
    (base/'scripts').mkdir()
    (base/'out').mkdir()
    create_file(base/'spec.json', jobspec.model_dump_json(indent=4), 0o644)
    create_file(base/'scripts'/'submit.rc', submit, 0o755)
    create_file(base/'scripts'/'cancel.rc', cancel, 0o755)
    create_file(base/'scripts'/'job.rc', job, 0o755)
    create_file(base/'scripts'/'run', jobspec.script, 0o755)
    #(base/'scripts'/'run').unlink(missing_ok=True)
    default_action = "#!/usr/bin/env rc\n"
    for state in ["active", "completed", "failed", "canceled"]:
        create_file(base/'scripts'/f'on_{state}.rc',
                    default_action, 0o755)
    # TODO: put in special on_active and on_completed hooks
    #
    # log completion of 'new' status
    append_csv(base/'status.csv', timestamp(), 0, 'new', 0)
    return Job(base)

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
