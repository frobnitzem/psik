# Using Psik to Launch Jobs via IRI Facility API

The IRI (Integrated Research Infrastructure) Facility API provides
a standardized REST API for submitting and managing jobs across
DOE computing facilities. This backend enables psik to submit jobs
to facilities like NERSC, ESNet, OLCF, and ALCF via the IRI API.

## Configuration

Configure an IRI backend in your `psik.json` config file:

```json
{
  "prefix": "/tmp/psik",
  "backends": {
    "iri_nersc": {
      "type": "iri",
      "queue_name": "regular",
      "project_name": "m1234",
      "attributes": {
        "resource_id": "perlmutter",
        "api_url": "https://api.iri.nersc.gov"
      }
    }
  }
}
```

### Required Configuration

- **`resource_id`** (in attributes): The compute resource identifier
  (e.g., `"perlmutter"` for NERSC's Perlmutter system)
- **`api_url`** (in attributes): Base URL for the IRI API
  (default: `https://api.iri.nersc.gov`)

### Optional Configuration

- **`queue_name`**: Queue or partition name (e.g., `"regular"`, `"debug"`)
- **`project_name`**: Account or project to charge for resource usage
- **`reservation_id`**: Reservation ID if using a reserved allocation

## Authentication

Each site accepts a different set of token types.

### Globus Auth

Many facilities accept a Globus access token with the following scope:

```
https://auth.globus.org/scopes/ed3e577d-f7f3-4639-b96e-ff5a8445d699/iri_api
```

See the [IRI API documentation](https://github.com/NERSC/iri-api-get-globus-token)
for example code to obtain this kind of token.

Note: Tokens expire after a period of time and will need to be refreshed.

### OLCF Auth

Visit my.olcf.ornl.gov, login under Account Type "Open" and look
on the left nav-bar for "S3M Access".

Generate a token using the following settings:

* OLCF Computing
* AmSC IRI API

## Providing the Token

The token MUST be provided via an environment variable:

    export IRI_TOKEN="your_access_token"

It is possible to change the default (`IRI_TOKEN`)
using a configuration setting:

   {
     "backends": {
       "iri_nersc": {
         "type": "iri",
         "attributes": {
           "resource_id": "perlmutter",
           "token": "$IRI_TOKEN"
         }
       }
     }
   }
   ```

## Submitting a Job

Create a job specification file (e.g., `job.json`):

```json
{
  "name": "Test IRI Job",
  "script": "#!/bin/bash\necho 'Hello from IRI'\nhostname\ndate\n",
  "backend": "iri_nersc",
  "resources": {
    "duration": 10,
    "node_count": 1,
    "process_count": 32
  }
}
```

Or use YAML format (`job.yaml`):

```yaml
name: Test IRI Job
script: |
  #!/bin/bash
  echo 'Hello from IRI'
  hostname
  date

backend: iri_nersc
resources:
  duration: 10
  node_count: 1
  process_count: 32
```

Submit the job:

```bash
psik submit job.json
# or
psik submit job.yaml
```

## Monitoring Jobs

Poll for job status updates:

```bash
psik poll <job_timestamp>
```

List all jobs:

```bash
psik ls
```

## Canceling Jobs

Cancel a running or queued job:

```bash
psik cancel <job_timestamp>
```

## Job State Mapping

The IRI backend maps IRI job states to psik states as follows:

| IRI State | Psik State |
|-----------|------------|
| QUEUED    | queued     |
| PENDING   | queued     |
| RUNNING   | active     |
| COMPLETED | completed  |
| FAILED    | failed     |
| CANCELLED | canceled   |

## Resource Specifications

The IRI backend supports the following resource specifications:

- **`duration`**: Maximum walltime in minutes
- **`node_count`**: Number of compute nodes
- **`process_count`**: Total number of processes
- **`processes_per_node`**: Processes per node
- **`cpu_cores_per_process`**: CPU cores per process
- **`gpu_cores_per_process`**: GPU cores per process
- **`exclusive_node_use`**: Request exclusive node access (boolean)

## Example: Multi-node GPU Job

```yaml
name: Multi-GPU Training
script: |
  #!/bin/bash
  module load pytorch
  srun python train.py

backend: iri_nersc
resources:
  duration: 60
  node_count: 4
  processes_per_node: 4
  gpu_cores_per_process: 1
  cpu_cores_per_process: 32
```

## Troubleshooting

### Authentication Errors

If you see `401 Unauthorized` errors:
- Verify your token is valid and not expired
- Ensure the token has the correct IRI API scope
- Check that `IRI_TOKEN` environment variable is set

### Resource Not Found

If you see `404 Not Found` errors:
- Verify the `resource_id` matches an available compute resource
- Check the IRI API documentation for valid resource IDs

### Job Submission Failures

Enable debug logging to see detailed error messages:

```bash
psik -vv submit job.yaml
```

## Limitations

- The IRI API is currently in development and may change
- Not all facilities support all IRI API features
- Token management requires manual refresh (no automatic renewal)
- File staging must be handled separately (IRI API focuses on job submission)

## See Also

- [IRI API Documentation](https://api.iri.nersc.gov/openapi.json)
- [IRI Science Portal](https://iri.science/)
- [Globus Auth Documentation](https://docs.globus.org/api/auth/)
