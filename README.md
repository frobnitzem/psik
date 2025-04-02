[![CI](https://github.com/frobnitzem/psik/actions/workflows/python-package.yml/badge.svg)](https://github.com/frobnitzem/psik/actions)
[![Coverage](https://codecov.io/github/frobnitzem/psik/branch/main/graph/badge.svg)](https://app.codecov.io/gh/frobnitzem/psik)

# Psi\_k - a Portable Submission Interface for Jobs

Psi\_k ($\Psi_k$) is a partial implementation of the
[Exaworks Job API Spec](https://exaworks.org/job-api-spec/)
that provides strong guarantees about callback
execution and queue polling.

## Installation and Getting Started

$\Psi_k$ is a simple python package put together with
[python-poetry](https://python-poetry.org/),
so it's easy to install:

    pip install 'git+https://github.com/frobnitzem/psik.git@main[facilities]'

If you're building a package with poetry, use poetry
add instead of pip install.

Running scripts, however, also requires
access to the `rc` shell -- a simple, lightweight sh-like
shell that does lists right and fixes bash's known problems
with quoting.

You can download, compile, install and use the rc shell using
[getrc.sh](https://github.com/frobnitzem/rcrc/blob/main/getrc.sh).
To put rc into your python virtual environment, call it like,

    getrc.sh $VIRTUAL_ENV


### Configuration

Psi\_K uses a json-formatted configuration file to
store information about where its (browsable) database
of runs are maintained, what backend to use, and what
default attributes to apply to jobs (e.g. project\_name).

The default location for this is `$HOME/.config/psik.json`,
but it can be overridden with the `--config` option,
or the `PSIK_CONFIG` environment variable.

An example configuration file is below:

    {
    "prefix": "/tmp/.psik",
    "backends": {
      "default": {
        "type": "local",
        "project_name": "project_automate",
        "attributes": {
            "-b": "packed:rs"
          }
        }
      }
    }

The "local" backend type just runs processes in the background
and is used for testing.
The "at" backend is more suitable for running locally,
and uses POSIX batch command.  However, it's broken on OSX.
Adding more backends is easy.
For HPC systems, "slurm" and "lsf" backends are implemented.
In the future, facility-provided API-s should be added
as backends.


## Writing a jobspec.json file

The `jobspec.json` file requires, at a minimum,
a script, e.g.

    { "script": "#!/usr/bin/env rc\necho moo\n",
      "backend": "default"
    }

Other properties (like a `ResourceSpec`) are listed in the
[JobSpec datatype definition](psik/models.py).

### Environment during job execution

When writing scripts, it's helpful to know that
the following shell variables are defined during job execution:

- mpirun -- An '\x01'-separated invocation to `JobSpec.launcher`.
            Executing `$mpirun <programname>` (from an rc shell) or
            `popen2(os.environ['mpirun'].split('\x01') + ['programname'])`
            from python will launch the program across all resources
            allocated to the job using the launcher specified.
- nodes  -- number of nodes allocated to the job
- base   -- base directory for psik's tracking of this job
- jobndx -- job step serial number (1-based) provided at launch time
- jobid  -- backend-specific job id for this job (if available)
- psik   -- the path to the psik program (or a literal "psik" if unknown)
- rc     -- the path to an rc shell (or /usr/bin/env rc if unknown)

See [psik/templates/partials/job\_body] for all the details.

## How it works

Psi\_k provides job tracking by adhering to a strong convention
for storing information about each job using a directory tree:

```
prefix/
   `<timestamp>`/
      spec.json  - JobSpec data
      status.csv - timestamp,jobndx,JobState,info -- history for job state
          timestamp is a system local time (output of time.time() call)
          jobndx is an integer sequence number of an instance of job: 1, 2, ...
          JobState is one of the values in :class:`JobState`
          info is an integer correponding to a scheduler's jobid (for queued)
          or a return status code (other states)
      scripts/ - directory containing
        submit       - Submit job.rc to the backend.
                       Submit is provided with the jobndx serial number as its
                       only argument.

        cancel       - Ask the backend to cancel all job indexes.
                       Has no effect if job has already completed / failed.

                       Cancel is provided with a list of native job-ids
                       as arguments.

        job          - (job.rc) script run during the job.
                       Its working directory is usually ../work, but templated
                       as {{job.directory}}.  job.rc is invoked by submit and
                       provided with the jobndx serial number as
                       its only argument.

        run          - user's run-script -- the payload invoked by job.rc
      work/ - directory where work is done
              may be a symbolic link to a node-local filesystem
              (e.g. when JobSpec.directory was set manually)
      log/  - directory holding logs in the naming scheme,
           console        - log messages from psik itself
           stdout.$jobndx - stdout and stderr logs from `run` portion of job.rc
           stderr.$jobndx - Note that jobndx is sequential from 1.
```

## Command-Line Interface

Because of this, $\Psi_k$ can provide a nice command-line replacement
for a batch queue system that transfers across many backends:

    % psik --help
    Usage: psik [OPTIONS] COMMAND [ARGS]...

    Commands:
      cancel   Cancel a job.
      ls       List jobs.
      reached  Record that a job has entered the given state.
      rm       Remove job tracking directories for the given jobstamps.
      run      Create a job directory from a jobspec.json file.
      status   Read job status information and history.

## Python interface

Psi\_k can also be used as a python package:

    from psik import Config, JobManager, JobSpec, JobAttributes, ResourceSpec

    cfg = Config(prefix="/proj/SB1/.psik", backends={"default":{
                        "type": "slurm",
                        "queue_name": "batch",
                        "project_name": "plaid"}})
    mgr = JobManager(cfg)
    rspec = ResourceSpec(duration = "60",
                         process_count = 2,
                         gpu_cores_per_process=1
                        )
    spec = JobSpec(name = "machine info",
                   script = """hostname; pwd;
                               cat /proc/cpuinfo /proc/meminfo
                               nvidia-smi
                               echo $mpirun,$nodes,$base,$jobndx,$jobid
                            """,
                   resources = rspec
                  )
    job = await mgr.create(spec)
    await job.submit()

    # Three redundant ways to check on job status:

    ## Read job status updates directly from the filesystem.
    print( await (job.base/'status.csv').read_text() )

    ## Reload job information from its file path.
    await job.read_info()
    print( job.history )

    ## Re-initialize / clone the Job from its file path.
    job = await Job(job.base)
    print( job.history )

This example shows most of the useful settings for
JobSpec information -- which makes up a majority of the code.
Other than `script`, all job information is optional.
However, the backend may reject jobs without enough
resource and queue metadata.  To avoid this, spend some time
setting up your backend attributes in `$PSIK_CONFIG`.

## Webhooks

Your jobs can include a "callback" URL.
If set, the callback will be sent [`psik.Callback`](psik/models.py)
messages whenever the job changes state.
This includes transitions into all states except the `new` state.

Callbacks arrive via POST message.
The body is encoded as 'application/json'.

If the job included a `cb_secret` value, then
the server can check callbacks to ensure they were
not forged.  A valid callback will contain
an `x-hub-signature-256` header that matches
`psik.web.sign_message(message, header_value)`.
The `psik.web.verify_signature` function does
a verification for you.
The scheme uses hmac256 the same way as [github webhooks](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries).

Note: Those state changes originate from the jobscript
itself calling `psik reached`.


## Comparison

Compared to another implementation of a portable API spec,
[PSI/J](https://exaworks.org/psij-python/#docs),
Psi\_k uses mostly the same key data models, with a few changes
to the data model, and three changes to the execution semantics:

1. Callback scripts are inserted into job.rc rather than polling the backend.
2. The user's job script is responsible for calling $mpirun
   in order to invoke parallel steps.
3. The default launcher is backend-dependent (e.g. srun for slurm, etc.).

`JobSpec`:
  - name : str
  - ~~executable~~
  - ~~arguments~~
  - _script_ -- executable plus arguments have been replaced with script
  - directory : Optional[str] -- defaults to `<job base>`/work
  - inherit\_environment : bool = True
  - environment : Dict[str,str] = {}
  - ~~stdin\_path~~
  - ~~stdout\_path~~
  - ~~stderr\_path~~
  - resources : ResourceSpec = ResourceSpec()
  - ~~attributes : JobAttributes~~
  - backend : str -- name of backend configured in `psik.json`
  - ~~pre\_launch~~ -- pre\_launch has been removed, since it is basically identical to launching two jobs in series
  - ~~post\_launch~~
  - ~~launcher~~ -- launcher has been removed and the `$mpirun` environment variable is defined within job scripts instead
  - _callback_  -- a callback URL to which the executor can report job progress
  - _cb_secret_ -- a secret token which the executor can use to sign its callbacks
  - _client_secret_ -- used internally by a server to validate any webhooks received

Stdin/stdout/stderr paths have been removed.  All input
and output files are captured in a well-known location.

Instead of script file paths, the $\Psi_k$ JobSpec accepts
full scripts and arranges to write them to well-known locations (see above).
The execution semantics is changed because `script` is not
launched inside the specified launcher.  Instead, `script`
is run during the normal job execution.  It has access to
several environment variables so it can arrange parallel
execution itself.  See (`Environment during job execution`) below.

The `callback` field is also new.  Rather than polling a job-queue
backend, $\Psi_k$ inserts calls to `$psik reached`
each time a job changes state.  This logs the start of a new
job state.

The `ResourceSpec` model is identical, except
it is fixed at `psij.ResourceSpecV1`, and
`duration` has been added (in fixed units of minutes).
`BackendConfig` derives from `JobAttributes`, but contains
only backend configuration values, not job attributes.

## Adding a new batch queue backend to Psi\_k

Internally, $\Psi_k$ implements each backend by including three templates:

psik/templates/

 * `<backend>/submit`  -- Submit a job to the queue.
                          Output to stderr is printed to the user's terminal.
                          On success, print only the backend's native job\id
                          to stdout and return 0.
                          On failure, must return nonzero. 

 * `<backend>/job`     -- Job submitted to the queue.
                          Should translate job resource and backend config
                          in a way the backend understands.
                          Must call psik logging at appropriate points. 
                          Must setup "Environment during job execution"
                          as specified above.

 * `<backend>/cancel`  -- Ask the backend to cancel the job.
                          Must call psik logging at appropriate points.

To add a backend, implement all 3 templates.
You probably also need an empty `__init__.py`
file so that the templates are included in the package.
This should be all you need for your new backend to be
picked up by the `psik/templates/renderer.py`.

# Developing

To develop on psik's source code, clone our
repo on github and check out your local copy.

    git clone ssh://git@github.com/your-userid/psik.git
    cd psik
    git remote add upstream https://github.com/frobnitzem/psik.git

Then install its dependencies into a virtual environment
managed by the poetry tool.

    pip3 install poetry
    poetry install
    poetry run pytest --cov=psik tests/ --cov-report html

Then create a new branch and edit away.

    git checkout -b new_feature
    git commit -a
    git push -u origin new_feature

Don't forget to create an issue and/or pull request with
your suggestions.

