# Hot-Start

The `psik hot-start` option is meant to be utilized in API-enabled
workflows as the script that runs on the remote compute resource.

Several things have to be setup properly for this to work.
First, psik needs to be installed on the remote resource,
and the job passed to its API should invoke psik as:

    jobstamp=123456.456
    jobndx=1
    psik hot-start $jobstamp $jobndx '{ contents of jobspec.json }'

That's the easy part.
The complicated part comes in the double-interpretation of the
`jobspec.json`.  A user will normally call

    psik run jobspec.json

with a backend targeting an API.  This will send the API call that
queues, then launches hot-start remotely.  On the remote side, however,
the workdir will probably be different, and the backend needs to be changed.
Currently, hot-start renames the backend to "default", and
does not change the workdir (`jobspec.directory`).
Other parts of the jobspec are left as-is.

This means the submission script is in charge of fixing up the workdir
to a path that makes sense on the remote host.  If the workdir
is given as `null`, then it is created as usual inside the remote's base jobdir.

The OLCF API script, for example, sets 'jobspec.directory' to None
before sending it to hot-start.
Note that it also string-formats the jobspec so that it can be passed
as a command-line parameter.  This would not be possible in the bash shell.
Other backends may have specific ways to configure their working directories.
