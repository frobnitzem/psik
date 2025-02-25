# Using Psik to Launch Jobs at ORNL OLCF

ORNL is deploying a Facility API that uses token authentication
and interfaces to SLURM.

Presently, it is available for alpha-testers with
active allocations on the ACE testbed.
In order to use it, you will need to set the `OLCF_TOKEN`
environment variable for the process running psik.
This is needed because the submit and cancel scripts
reference this token.
Instructions on obtaining a token are explained
when joining the alpha-tester program.

To use the OLCF API, first configure a named queue
that uses it within your `psik.json` config file:

```
{ "backends": {
    "defiant": {
      "type": "olcf",
      "queue_name": "batch-gpu",
      "project_name": "csc266",
      "reservation_id": null,
      "attributes" {
        "--gpu-bind": "closest"
      }
    }
  }
}
```

Then run a submission script where you have set
`duration` and `node_count`, etc. to match the system's resources,
```
name: test 
script: |
  #!/usr/bin/env rc
  printenv
  hostname
  echo $mpirun

backend: defiant

resources:
    duration: 60 # minutes
    node_count: 2
    processes_per_node: 4    # 4 GPUs per node
    cpu_cores_per_process: 7
    gpu_cores_per_process: 1
```

Launching the job is, as usual,
```
OLCF_TOKEN=123
psik run job.yaml
```
