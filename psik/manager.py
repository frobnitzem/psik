from typing import Union, Dict, Tuple, List, Any

from pathlib import Path
from time import sleep
from time import time as timestamp

from .models import JobSpec, JobAttributes
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
    def __init__(self, prefix : Union[str,Path],
                       defaults : JobAttributes = JobAttributes()):
        self.prefix = Path(prefix).resolve()
        # TODO: assert prefix is writable
        self.backend = self.prefix.name
        self.defaults = defaults

        templates.check(self.backend)
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
                sleep(0.001)

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
        data : Dict[str,Any] = {
                'job': jobspec.model_dump(),
                'base': str(base)
               }
        custom1 = jobspec.attributes.custom_attributes.get(self.backend, {})
        custom = [ {'key': k, 'value': v} for k, v in custom1.items() ]
        data['job']['attributes']['custom_attributes'] = custom

        tpl = templates.render_all(self.backend, templates.actions, data)

        return create_job(base, jobspec, **tpl)

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
               - scripts/(pre_submit on_* submit cancel job run)
               - empty work/ and log/ directories
    """
    assert base.is_dir()
    assert jobspec.directory is not None and Path(jobspec.directory).is_dir()
    (base/'scripts').mkdir()
    (base/'log').mkdir()
    create_file(base/'spec.json', jobspec.model_dump_json(indent=4), 0o644)
    create_file(base/'scripts'/'submit', submit, 0o755)
    create_file(base/'scripts'/'cancel', cancel, 0o755)
    create_file(base/'scripts'/'job', job, 0o755)
    create_file(base/'scripts'/'run', jobspec.script, 0o755)
    #(base/'scripts'/'run').unlink(missing_ok=True)
    default_action = "#!/usr/bin/env rc\n"
    for state in ["active", "completed", "failed", "canceled"]:
        create_file(base/'scripts'/f'on_{state}',
                    default_action, 0o755)
    create_file(base/'scripts'/f'pre_submit', default_action, 0o755)
    # TODO: put in special on_active and on_completed hooks
    #
    # log completion of 'new' status
    append_csv(base/'status.csv', timestamp(), 0, 'new', 0)
    return Job(base)
