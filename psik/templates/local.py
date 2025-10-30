import asyncio
from typing import List, Optional
import os
import sys
import signal
import logging
_logger = logging.getLogger(__name__)

from psik import Job, JobState

def sigchld_handler(signum, frame):
    # Use a loop with os.WNOHANG to reap all terminated children (to handle race conditions)
    try:
        while True:
            # os.waitpid returns (0, 0) if no child is ready to be waited for
            pid, status = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                break # No more children to reap
            # Can log exit status here.
    except ChildProcessError:
        # Expected error if no children are left
        pass
    except Exception as e:
        # Handle unexpected errors
        _logger.error("Error during waitpid: %s", e)

async def submit(job: Job, jobndx: int) -> Optional[str]:
    """
    Implements the standard Unix double-fork pattern to
    run the job as a background process.
    """
    read_fd, write_fd = os.pipe()

    # 1. First fork: Allows the parent process to exit immediately.
    # The new child process runs in the background.
    try:
        pid = os.fork()
        if pid > 0: # ORIGINAL PARENT (P)
            signal.signal(signal.SIGCHLD, sigchld_handler)
            os.close(write_fd) # close the write end
            try:
                grandchild_pid_bytes = os.read(read_fd, 100)
            except InterruptedError:
                grandchild_pid_bytes = os.read(read_fd, 100)
            os.close(read_fd) # Close the read end
            return grandchild_pid_bytes.decode().strip()
    except OSError as err:
        try:
            os.close(read_fd)
            os.close(write_fd)
        except:
            pass
        _logger.error(f'Fork #1 failed: %s', err)
        return None

    # create a session leader
    os.setsid()

    #os.umask(0) # remove umask restrictions

    # 2. Second fork.
    # Prevents the job from being terminated accidentally by
    # SIGHUP when the controlling terminal is closed.
    try:
        pid = os.fork()
        if pid > 0:
            try:
                os.write(write_fd, str(pid).encode() + b'\n')
                os.close(write_fd)
            except Exception as e:
                _logger.error('Error writing PID to pipe: %s', e)
            # Exit child (the session leader)
            sys.exit(0)
    except OSError as err:
        _logger.error('Fork #2 failed: %s', err)
        sys.exit(1)

    # 3. Redirect standard file descriptors
    #sys.stdout.flush()
    #sys.stderr.flush()
    #si = open(os.devnull, 'r')
    #so = open(os.devnull, 'a+')
    #se = open(os.devnull, 'a+')
    #os.dup2(si.fileno(), sys.stdin.fileno())
    #os.dup2(so.fileno(), sys.stdout.fileno())
    #os.dup2(se.fileno(), sys.stderr.fileno())

    # 4. hand off to job.execute
    #asyncio.run(job.execute(jobndx))
    await job.execute(jobndx)
    sys.exit(0)
    return None

async def poll(jobids: List[str]) -> List[JobState]:
    return [JobState.failed for i in jobids]

async def cancel(jobinfos: List[str]) -> None:
    return None
