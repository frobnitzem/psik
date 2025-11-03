# Functionality to help deal with the system / process
# interface.

from typing import Optional, Dict, List, Union, Tuple
import asyncio
import os
import sys
import signal
import subprocess
from pathlib import Path
import logging
_logger = logging.getLogger(__name__)


"""
from contextlib import contextmanager

@contextmanager
def set_env(inherit_environment: bool = True, **environ):
    # Stash the original env.
    old_environ = dict(os.environ)

    # create the new one
    if not inherit_environment:
        os.environ.clear()
    os.environ.update(environ)

    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(old_environ)
"""

# Global variable to hold the running process object
current_process: Optional[subprocess.Popen] = None

def signal_handler(sig, frame):
    """
    Custom signal handler to propagate the signal to the child process.
    """
    global current_process

    # Check if a child process is running
    if current_process and current_process.poll() is None:
        _logger.warning("\nParent Python process caught signal %d. Propagating to child process (PID: %d)...", sig, current_process.pid)
        try:
            # Send the received signal to the process group (PGID = -PID)
            # This ensures the script and all its children are terminated.
            os.killpg(current_process.pid, sig)
            
            # Wait a short period for the child process to clean up
            current_process.wait(timeout=5)
            
        except ProcessLookupError:
            # Child already died, which is fine
            pass
        except subprocess.TimeoutExpired:
            _logger.error("Child PID %d failed to terminate after propagation, sending SIGKILL.", current_process.pid)
            os.killpg(current_process.pid, signal.SIGKILL)
            current_process.wait()

    # Re-raise the signal to terminate the Python process itself after cleanup
    #sys.exit(128 + sig)
    os._exit(128+sig)

def parse_shebang(script: str) -> List[str]:
    """
    parses the first line of a script file to extract
    the shebang interpreter command.

    Args:
        script: The script

    Returns:
        A list of strings representing the interpreter command and its arguments,
        e.g., ['/bin/bash'], or ['/usr/bin/env', 'python3'], or None if no shebang is found.
    """
    # Check for shebang format: #!
    if not script.startswith('#!'):
        return []

    return script[2:].split('\n', 1)[0].strip().split()

def run_shebang(
    script_content: str,
    stdout_file_path: str,
    stderr_file_path: str,
    timeout: Optional[int] = None,
    env: Optional[Dict[str, str]] = None
) -> int:
    """
    Executes a shell script string, directing stdout/stderr to specified files.

    It creates a new process group for the script (using preexec_fn) so that
    when the main process is terminated, a signal can be sent to the entire
    group, ensuring all child processes are also killed.

    Args:
        script_content: The content of the shell script to execute.
        stdout_file_path: Path to the file for standard output redirection.
        stderr_file_path: Path to the file for standard error redirection.
        timeout: Optional maximum time in minutes to wait for the script to finish.
        env: Optional dictionary of environment variables to set for the process.

    Returns:
        The exit code of the script, or 9 if it times out or an error occurs.
    """

    global current_process
    if timeout is not None: # convert minutes to seconds
        timeout = 60*timeout

    # 1. Register signal handlers
    # This must be done *before* starting the process
    # Note: SIGKILL and SIGSTOP cannot be caught/handled
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    interpreter = parse_shebang(script_content)
    if not interpreter:
        _logger.debug("Script does not contain a shebang pattern. Defaulting to /bin/bash")
        interpreter = ["/bin/bash"]
    
    # 1. Open the files for redirection
    try:
        # 'w' mode to overwrite existing files
        with open(stdout_file_path, 'wb') as stdout_f, \
             open(stderr_file_path, 'wb') as stderr_f:

            # 1. Define the pre-execution function
            # This function runs in the child process *before* execve.
            # It sets the child's process group ID (PGID) to its PID.
            # This is key for process group termination.
            def set_new_pgrp():
                os.setpgid(0, 0)

            # 1. Execute the script using a shell interpreter
            # /bin/bash is a common choice for shebang scripts.
            # The script content is piped to bash's standard input.
            current_process = subprocess.Popen(
                interpreter,
                stdin=subprocess.PIPE,
                stdout=stdout_f,
                stderr=stderr_f,
                preexec_fn=set_new_pgrp, # Set up the process group
                env=env
            )
            assert current_process.stdin is not None

            # 1. Write the script content to the process's standard input
            # and close stdin to signal EOF, allowing the interpreter to start execution.
            current_process.stdin.write(
                    script_content.encode(sys.getdefaultencoding())
                )
            current_process.stdin.close()

            # 1. Wait for the process to complete
            try:
                # wait for the process to terminate, with an optional timeout
                return_code = current_process.wait(timeout=timeout)
                #return return_code
            except subprocess.TimeoutExpired:
                minutes = timeout/60 if timeout else 0
                _logger.warning("Script execution timed out after %d minutes. Killing process group.", minutes)
                # Kill the entire process group if a timeout occurs
                try:
                    os.killpg(current_process.pid, signal.SIGTERM)
                    try:
                        current_process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        _logger.error("SIGTERM grace period expired. Sending SIGKILL.")
                        os.killpg(current_process.pid, signal.SIGKILL)
                        current_process.wait()
                except ProcessLookupError:
                    # Process already exited, which is fine
                    pass
                return 9
            except Exception as e:
                _logger.error("An error occurred while waiting for the process: %s", e)
                return 9

    except FileNotFoundError as e:
        _logger.error("Error: One of the specified output file paths is invalid: %s", e)
        return 9
    except Exception as e:
        _logger.error("An unexpected error occurred: %s", e)
        return 9
    finally:
        current_process = None
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.SIG_DFL)

    return return_code

async def runcmd(prog : Union[Path,str], *args : str,
                 cwd : Union[Path,str,None] = None,
                 expect_ok : Optional[bool] = True) -> Tuple[int,str,str]:
    """Run the given command inside an asyncio subprocess.
       
       Returns (return code : int, stdout : str, stderr : str)
    """
    pipe = asyncio.subprocess.PIPE
    proc = await asyncio.create_subprocess_exec(
                    prog, *args, cwd=cwd,
                    stdout=pipe, stderr=pipe)
    stdout, stderr = await proc.communicate()
    # note stdout/stderr are binary

    out = stdout.decode('utf-8')
    err = stderr.decode('utf-8')
    if len(stdout) > 0:
        _logger.info('%s stdout: %s', prog, out)
    if len(stderr) > 0:
        _logger.warning('%s stderr: %s', prog, err)

    ret = -1
    if proc.returncode is not None:
        ret = proc.returncode
    if expect_ok != (proc.returncode == 0):
        _logger.error('%s returned %d', prog, ret)
    if expect_ok is None:
        _logger.info('%s returned %d', prog, ret)

    return ret, out, err

