"""Capture the fixed disposable Compose gate without PowerShell stderr conversion."""

import argparse
import subprocess
import sys
from pathlib import Path


def run_logged(command, log_path, *, cwd=None, output=None):
    """Stream both native outputs as bytes and preserve the child's exit code."""
    output = output if output is not None else sys.stdout.buffer
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Open the evidence file first: if logging is unavailable, do not start a job.
    with log_path.open("wb") as saved:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        try:
            while chunk := process.stdout.read1(64 * 1024):
                saved.write(chunk)
                saved.flush()
                output.write(chunk)
                output.flush()
            return process.wait()
        except BaseException:
            # Stop the client if capture fails or the operator interrupts. Any
            # disposable containers are reset by the next gate; no pass is recorded.
            process.kill()
            process.wait(timeout=10)
            raise
        finally:
            process.stdout.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    if not (root / "compose.test.yaml").is_file():
        print("compose.test.yaml missing; test gate not started.")
        return 2
    command = [
        "docker",
        "compose",
        "-p",
        "personal-jarvis-tests",
        "-f",
        "compose.test.yaml",
        "up",
        "--build",
        "--abort-on-container-exit",
        "--exit-code-from",
        "tests",
    ]
    try:
        return run_logged(command, args.log, cwd=root)
    except OSError as exc:
        print(f"Compose output capture failed ({type(exc).__name__}); gate incomplete.")
        return 2
    except KeyboardInterrupt:
        print("Compose gate interrupted; no pass recorded.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
