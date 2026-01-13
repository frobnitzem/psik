# Using Psik to Launch Jobs at ORNL OLCF

Globus-compute provides a python package
for interfacing with a function-as-a-service
platform.  The platform is based around Parsl,
which farms function calls out to a set of executors.

However, this design is a bit more complex than
we need, since psik just wants to launch a SLURM-like job.

Thus, we use an encapsulation method, where a local psik
sends a job to a "globus" backend by executing psik.submit()
on the remote side.  That remote psik is configured with
just two things -- a prefix holding psik job directories
and a backend for the remote side.

Configure it within your `psik.json` config file:

```json
{"prefix": "/tmp/psik/client",
 "backends": {
    "polaris": {
      "type": "globus",
      "queue_name": "UUID-for-your-Globus-compute-endpoint",
      "project_name": "/lustre/stf006/psik_jobs",
      "attributes": {
        "type": "slurm",
        "project_name": "stf006",
        "queue_name": "batch"
      }
    }
  }
}
```

Note that the Globus-compute endpoint ID goes into `queue_name`
and `project_name` can be used to set psik's prefix
on the remote system.

The inner `attributes` configure the backend used on the remote side.
In this case, local submit/cancel operations trigger slurm
submit/cancel on the remote side.

The job's resource spec is passed through and interpreted
by the remote (slurm) backend.


## Submitting a Job

In order to use it, you will need to login
to Globus (setting up `$HOME/.globus_compute/storage.db`)
or set the following environment variables,

    GLOBUS_COMPUTE_CLIENT_ID=nnn-uuid
    GLOBUS_COMPUTE_CLIENT_SECRET=blahblahblah

or, potentially with a newer release of Globus compute,
this environment variable may have been merged with the regular
Globus transfer id/secret pair:

    GLOBUS_CLIENT_ID=nnn-uuid
    GLOBUS_CLIENT_SECRET=blahblahblah

You will also need to setup and run your Globus endpoint
as documented in the next section and put its UUID
in your configuration as explained above.

Finally, run a normal submission script like below:

```yaml
name: test 
script: |
  #!/bin/bash
  printenv
  hostname
  echo $mpirun

backend: polaris
```

Launching the job is, as usual,
```shell
psik run job.yaml
```


## Running a Globus Compute endpoint

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

2. Create a compute config file.

    The following configuration comes from [Globus's config reference](https://globus-compute.readthedocs.io/en/stable/endpoints/config_reference.html), and uses process-pool engine, which is recommended for IO-bound work.  This is an appropriate choice, since these processes are only invoking psik front-end functions (submit/cancelling jobs) and doing disk I/O on polling.

```yaml
# compute-system:$HOME/venv/globus_compute.yaml
display_name: Psik Globus Endpoint
public: false
engine:
    type: ThreadPoolEngine
    max_workers: 2
```

3. (optional) Use an existing Globus Confidential Client, or create a new one

    This step is optional, but will allow you to store credentials
    needed to authenticate clients to this service.  This way you
    can launch clients without an interactive terminal (skipping
    terminal-based authentication to globus during the launch process).

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

4. Start the globus-compute-endpoint

```
. ./venv/bin/activate
which globus-compute-endpoint # ensure this is your venv's program

# setup new configuration
globus-compute-endpoint configure --endpoint-config local_endpoint.yaml psik_endpoint

globus-compute-endpoint start psik_endpoint
# check for running endpoints
globus-compute-endpoint list
```
