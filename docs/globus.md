# Using Psik to Launch Jobs at ORNL OLCF

Globus-compute provides a python package
for interfacing with a function-as-a-service
platform.  However, the platform is flexible
enough to allow traditional HPC/MPI jobs.

In order to use it, you will need to login
to globus (setting up `$HOME/.globus_compute/storage.db`)
or set the following environment variables,

    GLOBUS_COMPUTE_CLIENT_ID=nnn-uuid
    GLOBUS_COMPUTE_CLIENT_SECRET=blahblahblah

or, potentially with a newer release of Globus compute,
this environment variable may have been merged with the regular
Globus transfer id/secret pair:

    GLOBUS_CLIENT_ID=nnn-uuid
    GLOBUS_CLIENT_SECRET=blahblahblah

Then, to setup globus-compute as a backend,
configure it within your `psik.json` config file:

```json
{"prefix": "/tmp/psik/client",
 "backends": {
    "polaris": {
      "type": "globus",
      "queue_name": "UUID-for-your-Globus-compute-endpoint"
    }
  }
}
```

Note that `project_name`, `queue_name`, etc. are not
configurable through Globus-compute.
The job's resource spec is also dropped, since
node count, time limit, processors per node,
scheduler attributes, etc. are baked into the
endpoint's `globus_compute.yaml` (below).
In theory this could be accomplished using a
[multi-user endpoint with a templated config](https://globus-compute.readthedocs.io/en/stable/endpoints/multi_user.html),
but in practice this leads to hangs with no error messages
that cannot be effectively debugged.

Note also that this means `$mpirun` is not going to work
as expected.  Likely it will launch a
single copy of your process.  To work around this, use
explicit flags like `srun -n8 -c7 cmd` in your script.

You will also need to setup and run your globus endpoint
as documented in the next section.
If your client is running on the same host and virtual
environment as your server, you will need to set a
a unique `PSIK_CONFIG=/path/to/psik.json` for client
runs (so that .

Then run a submission script like below:

```yaml
name: test 
script: |
  #!/usr/bin/env rc
  printenv
  hostname
  echo $mpirun

backend: polaris
```

Launching the job is, as usual,
```shell
psik run job.yaml
```

## Running a globus compute endpoint

Most compute centers will require that you run your own
globus compute endpoint (e.g. on an HPC system login node).
This is also useful to see where/how the psik endpoint and the
globus endpoint configurations should connect.
In addition, because of its insecure python pickle-based
serialization strategy, Globus compute is very sensitive
to version mismatch between client and server.

Instructions for doing this are below.
The [splash-flows documentation](https://als-computing.github.io/splash_flows_globus)
was extremely helpful for defining this process.

1. Install globus-compute-endpoint and psik on your compute system.

    On the node where you will run a Globus compute endpoint,

        python3 -m venv venv
        . venv/bin/activate
        pip install globus-compute-endpoint psik

2. Create a psik config file (default location is `venv/etc/psik.json`)

```json
{ "prefix": "/tmp/psik/jobs",
  "rc_path": "/ccsopen/home/99r/bin/rc",
  "backends": {
    "default": {
      "type": "slurm"
    }
}
```

    Note that "rc" and the "default" backend must be configured.
    The job will be re-created from its spec and the default backend
    when it reaches the compute system, but only the
    "scripts/job" script will be run (not the submit script).

3. Create a compute config file.

    The following template comes from [als-computing example](https://github.com/als-computing/als_at_alcf_tomopy_compute/blob/main/template_config.yaml), and you will need to modify it for your environment.
    Additional information is provided by [Globus's config reference](https://globus-compute.readthedocs.io/en/stable/endpoints/config_reference.html).

```yaml
# compute-system:$HOME/venv/globus_compute.yaml
display_name: My Globus Endpoint
engine:
    type: GlobusComputeEngine # This engine uses the HighThroughputExecutor

    max_workers_per_node: 1 # Sets one worker per node
    prefetch_capacity: 0  # Increase if you have many more tasks than workers                                                    
    address:
        type: address_by_interface
        ifname: hsn0 # alt. bond0

    strategy: simple
    job_status_kwargs:
        max_idletime: 300 # Batch jobs idle for 300s after work ends
        strategy_period: 60 # queue polling interval for completed jobs

    provider:
        type: SlurmProvider # alt. PBSProProvider
        # The following are configured by psik via its template
        partition: batch-cpu
        account: mph122

        # optional args. to send to scheduler
        #scheduler_options: "#SBATCH -C gpumpu"

        launcher:
            type: SrunLauncher # alt. MpiExecLauncher
            #bind_cmd: --cpu-bind
            #overrides: --ppn 1

        # Node setup: activate necessary conda environment and such
        worker_init: ". $PWD/venv/bin/activate;"

        walltime: 00:60:00 # Jobs will end after 60 minutes
        nodes_per_block: 1 # All jobs will have 1 node
        init_blocks: 0
        min_blocks: 0
        max_blocks: 1 # No more than 1 job will be scheduled at a time
```

4. Use an existing Globus Confidential Client, or create a new one

    - In your browser, navigate to globus.org
    - Login
    - On the left, navigate to "Settings"
    - On the top navigation bar, select "Developers"
    - On the right under Projects, create a new project or select an existing one
    - Create a new registered app associated with your runner, or select an existing one (of type service account / application credential)
    - Generate a secret
    - Store the confidential client UUID and Secret (note: make sure you copy the Client UUID and not the Secret UUID)

    These credentials should be set as the environment variables
    `GLOBUS_COMPUTE_CLIENT_ID` and `GLOBUS_COMPUTE_CLIENT_SECRET`
    on both the compute client and server.

    Notes:

      * If you create a new service client, you will need to get permissions
        set by the correct person at ALCF, NERSC or other facility to be able
        to use it for transfer endpoints.

      * You can make sure you are signed into the correct account by entering:

            globus-compute-endpoint whoami

      * If you are signed into your personal Globus account,
        make sure to sign out completely using:

            globus-compute-endpoint logout

5. Start the globus-compute-endpoint

```
. ./venv/bin/activate
which globus-compute-endpoint # ensure this is your venv's program

# setup new configuration
globus-compute-endpoint configure --endpoint-config venv/globus_compute.yaml my_endpoint

globus-compute-endpoint start my_endpoint
# check for running endpoints
globus-compute-endpoint list
```
