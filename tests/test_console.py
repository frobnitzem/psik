from psik.console import run_shebang

def test_run_shebang(tmp_path):
    # Create a script that spawns a background child process, which is a key test
    # for the process group termination functionality.
    SHELL_SCRIPT_CONTENT = r"""#!/bin/bash
    echo "Starting script..."
        # Run a background process (sleep) that would normally be left running (a zombie)
    # if we didn't use process groups.
    sleep 5 &
    CHILD_PID=$!
    echo "Child process started with PID: $CHILD_PID"

    # Sleep for a shorter time than the child, so the parent exits first
    sleep 2

    echo "Parent script exiting."
    # Wait for the child if you want, but for demonstration
    # we let the parent exit while the child is still sleeping.
    """

    STDOUT_PATH = tmp_path/'script_output.txt'
    STDERR_PATH = tmp_path/'script_error.txt'

    print(f"Running script. Output to {STDOUT_PATH}, Errors to {STDERR_PATH}")
    # Use a timeout shorter than the child process (e.g., 3s < 5s) to test SIGTERM on process group
    exit_code = run_shebang(
        script_content=SHELL_SCRIPT_CONTENT,
        stdout_file_path=STDOUT_PATH,
        stderr_file_path=STDERR_PATH,
        timeout=3
    )

    print("-" * 30)

    print(f"Script finished with exit code: {exit_code}")
    assert exit_code == 0

    print("\nContents of STDOUT file:")
    try:
        with open(STDOUT_PATH, 'r') as f:
            output = f.read()
            print(output)
            assert 'Child process started with PID' in output
    except FileNotFoundError:
        print("STDOUT file not found.")
        raise
