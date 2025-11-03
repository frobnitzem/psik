import asyncio
from typing import List, Optional
import os
import sys
import signal
import logging
from contextlib import redirect_stdout, redirect_stderr
_logger = logging.getLogger(__name__)

from psik import Job, JobState

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
            os.close(write_fd) # close the write end
            grandchild_pid_bytes = os.read(read_fd, 100)
            os.close(read_fd) # Close the read end
            try:
                pid, status = os.waitpid(pid, 0)
            except ChildProcessError as e:
                _logger.error(f"ChildProcessError waiting on {pid}: {e}")
            return grandchild_pid_bytes.decode().strip()
    except OSError as err:
        try:
            os.close(read_fd)
            os.close(write_fd)
        except:
            pass
        _logger.error(f'Fork #1 failed: %s', err)

    fork_job(write_fd, job, jobndx)
    return None

def fork_job(write_fd: int, job: Job, jobndx: int) -> None:
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
            # session leader exits
            os._exit(0)
        else:
            pass # grandchild continues below
    except OSError as err:
        _logger.error('Fork #2 failed: %s', err)
        os._exit(1)

    # 3. Redirect standard file descriptors
    with open(str(job.base/"log"/"console"), "a+") as f:
        # Use both context managers to redirect stdout and stderr to `f`
        with redirect_stdout(f), redirect_stderr(f):
            # 4. hand off to job.execute
            asyncio.run(job.execute(jobndx))
    os._exit(0)

async def poll(job: Job) -> None:
    return None

async def cancel(jobinfos: List[str]) -> None:
    for pid in jobinfos:
        try:
            os.kill(int(pid), signal.SIGTERM) # use SIGINT?
        except Exception as e:
            _logger.error(f"Error canceling {pid}: {e}")
    return None
