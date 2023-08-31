# PSI/K - a Portable Submission Interface for Jobs

PSI/K is a partial implementation of the
[Exaworks Job API Spec](https://exaworks.org/job-api-spec/)
that provides strong guarantees about callback
execution and queue polling.

It provides these by introducing a strong convention
for internal tracking of job information using
a directory tree:

```
prefix/
  backend/
    `<timestamp>`/
      spec.json  - JobSpec data
      status.csv - timestamp,jobndx,JobState,info -- history for job state
          timestamp is a system local time (output of time.time() call)
          jobndx is an integer sequence number of an instance of job: 1, 2, ...
          JobState is one of the values in :class:`JobState`
          info is an integer correponding to a scheduler's jobid (for queued)
          or a return status code (other states)
      scripts/ - directory containing
        pre_submit   - script run on submitting node once before submitting the
                        first instance of the job
                        An error will prevent job submission.
        on_active    - script to run when job starts
        on_completed - script to run from `job` on successful exit
        on_failed    - script to run from `job` on failing exit
        on_canceled  - script to run on cancelling node after cancellation succeeds
        submit       - Submit job.rc to the backend.
                       Submit is provided with the job serial number as its
                       only argument.

        cancel       - Ask the backend to cancel job.rc.
                       Has no effect if job has already completed / failed.

                       Cancel is provided with a list of native job-ids
                       as arguments.

        job          - script run during the job (working directory is ../work)
                       `job` is provided with the

        run          - user's run-script -- invoked by job
      work/ - directory where work is done
              may be a symbolic link to a node-local filesystem
      log/  - directory holding logs in the naming scheme,
           stdout.1 - from first run of job
           stderr.1
           stdout.2 - from second run of job
           stderr.2, etc.
```

Because of this, PSI/K can provide a nice command-line replacement
for a batch queue system that transfers across many backends:

    % psik --help
    Usage: psik [OPTIONS] COMMAND [ARGS]...

    Commands:
      cancel   Cancel a job.
      ls       List jobs.
      reached  Record that a job has entered the given state.
      run      Run a job from a result.yaml file.
      status   Read job status information and history.


## Comparison

Compared to another implementation of a portable API spec,
[PSI/J](https://exaworks.org/psij-python/#docs),
PSI/K uses mostly the same key data models, with a few changes
to the data model, and three changes to the execution semantics:

1. Callback scripts are inserted into the job rather than polling the backend.
2. The user's job script is responsible for calling $mpirun
   in order to invoke parallel steps.
3. The default launcher is backend-dependent (e.g. srun for slurm, etc.).

`JobSpec`:
  - name : str
  - ~~executable~~
  - ~~arguments~~
  - _script_ -- executable plus arguments have been replaced with script
  - directory : str
  - inherit\_environment : bool = True
  - environment : Dict[str,str] = {}
  - ~~stdin\_path~~
  - ~~stdout\_path~~
  - ~~stderr\_path~~
  - resources : ResourceSpec = ResourceSpec()
  - attributes : JobAttributes = JobAttributes()
  - ~~pre\_launch~~
  - _pre\_submit_ : str -- pre\_launch has been replaced with pre\_submit. It is a script, not a filename. It is run just before submitting the job.
  - ~~post\_launch~~
  - launcher=None
  - _events_ : Dict[JobState : str] = {} -- callbacks

Stdin/stdout/stderr paths have been removed.  All input
and output files are captured in a well-known location.

Instead of script file paths, the PSI/K JobSpec accepts
full scripts and arranges to write them to well-known locations (see above).
The execution semantics is changed because `script` is not
launched inside the specified launcher.  Instead, `script`
is run during the normal job execution.  It has access to
several environment variables so it can arrange parallel
execution itself.  See (`Environment during job execution`) below.

The `events` tag is also new.  Rather than polling a job-queue
backent, PSI/K inserts calls to the job's `scripts/on_{event}.rc`
scripts each time a job changes state.  These scripts
are pre-filled with scripts from `JobSpec.events`, when
they exist.  It is also possible for a user to modify the
callback files directly.

The `ResourceSpec` and `JobAttributes` models are identical, except
`ResourceSpec` is fixed at `psij.ResourceSpecV1`, and
`duration` has been fixed as required job-time in units of minutes,
and moved out of `JobAttributes` and into `ResourceSpec`.

Internally, PSI/K implements each backend by including three templates:

psik/templates/
 * `<backend>-submit.rc` -- Submit a job to the queue.
                          Output to stderr is printed to the user's terminal.
                          On success, print only the backend's native job\id
                          to stdout and return 0.
                          On failure, must return nonzero. 
 * `<backend>-job.rc`    -- Job submitted to the queue.
                          Should insert job resource and attributes
                          in a way the backend understands.
                          Must call psik logging and callbacks
                          at appropriate points. 
                          Must setup "Environment during job execution"
                          as specified below.
 * `<backend>-cancel.rc` -- Ask the backend to cancel the job.
                          Must call psik logging and callbacks
                          at appropriate points.

## Environment during job execution

The following shell variables are defined during job execution:

- mpirun -- A space-separated invocation to `JobSpec.launcher`.
            Executing `$mpirun <programname>` will
            launch the program across all resources allocated to the job
            using the launcher specified.
- nodes  -- number of nodes allocated to the job
- base   -- base directory for psik's tracking of this job
- jobid  -- backend-specific job id for this job


## Configuration

PSI/K uses a json-formatted configuration file to
store information about where run directories are maintained,
what backend to use, and what default attributes to apply
to jobs (e.g. project\_name).

The default location for this is `$HOME/.config/psik.json`,
but it can be overridden with the `--config` option.

An example configuration file is below:

    {
    "prefix": "/tmp/.psik",
    "backend": "local",
    "default_attr": {
        "project_name": "project_automate",
        "custom_attributes": {
                "srun": {"--gpu-bind": "closest"},
                "jsrun": {"-b": "packed:rs"}
            }
        }
    }
