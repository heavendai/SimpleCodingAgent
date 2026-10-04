"""Trusted helper: apply inherited hard limits BEFORE exec; never import repo code.

Called with absolute path and Python -I -S from cwd=/, not as a repo module.
Using an exec helper avoids subprocess preexec_fn's multithreading hazards.
"""
import json
import os
import resource
import sys


def main():
    limits = json.loads(sys.argv[1])
    mapping = {"cpu_seconds": resource.RLIMIT_CPU, "address_space_bytes": resource.RLIMIT_AS,
               "file_bytes": resource.RLIMIT_FSIZE, "open_files": resource.RLIMIT_NOFILE,
               "processes": resource.RLIMIT_NPROC}
    for name, kind in mapping.items():
        _, existing_hard = resource.getrlimit(kind)
        requested = limits[name]
        value = min(requested, existing_hard) if existing_hard != resource.RLIM_INFINITY else requested
        resource.setrlimit(kind, (value, value))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.execve(sys.argv[2], sys.argv[2:], {})


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        print(f"Sandbox launcher refused to continue: {error}", file=sys.stderr)
        sys.exit(125)
