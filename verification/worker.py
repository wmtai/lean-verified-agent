"""Fixed entry point for separate export and verification containers.

Only the export stage reads candidate source/olean. The verification stage
reads serialized proof data and calls the pinned upstream Comparator frontend.
The host enforces container wall/memory/process/output limits.
"""

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


LOG_BYTES = 65536
MAX_EXPORT_BYTES = 16 * 1024 * 1024
ENVIRONMENT = {
    "PATH": "/opt/lean/bin:/usr/bin:/bin", "HOME": "/tmp",
    "LEAN_PATH": "/trusted/.lake/build/lib/lean:/tmp/work",
    "LEAN_ABORT_ON_PANIC": "1",
}


def limited_text(path):
    with path.open("rb") as handle:
        return handle.read(LOG_BYTES).decode("utf-8", errors="replace")


def command(argv, label):
    """Logs go to bounded tmpfs; controller also bounds the whole container."""
    stdout, stderr = Path(f"/tmp/{label}.stdout"), Path(f"/tmp/{label}.stderr")
    with stdout.open("wb") as out, stderr.open("wb") as err:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                cwd="/tmp/work", env=ENVIRONMENT, check=False)
    return {"returncode": result.returncode,
            "stdout": limited_text(stdout), "stderr": limited_text(stderr)}


def run(stage):
    Path("/tmp/work").mkdir()
    version = command(["/opt/lean/bin/lean", "--version"], "version")
    match = re.search(r"\bversion\s+(\d+\.\d+\.\d+)", version["stdout"])
    packet = {"protocol": 1, "stage": stage, "lean_version": match.group(1) if match else None}
    if version["returncode"] or packet["lean_version"] != "4.34.1":
        return dict(packet, status="INFRASTRUCTURE_ERROR", version_check=version)
    if stage == "verify":
        checked = command(["/opt/acceptance/verify_exports", "--verify"], "verify")
        status = {0: "VERIFIED", 1: "SUBMISSION_REJECTED"}.get(checked["returncode"], "INFRASTRUCTURE_ERROR")
        if status == "VERIFIED" and "COMPARATOR_ACCEPTED" not in checked["stdout"].splitlines():
            status = "INFRASTRUCTURE_ERROR"
        return dict(packet, status=status, comparator=checked)
    if stage != "export":
        raise ValueError("Expected export or verify stage")
    source = Path("/input/Candidate.lean").read_bytes()
    packet["source_sha256"] = hashlib.sha256(source).hexdigest()
    Path("/tmp/work/Solution.lean").write_bytes(source)
    compiled = command(["/opt/lean/bin/lean", "-j1", "-o", "Solution.olean", "Solution.lean"], "compile")
    packet["compilation"] = compiled
    if compiled["returncode"]:
        return dict(packet, status="ELABORATION_FAILED" if compiled["returncode"] == 1 else "INFRASTRUCTURE_ERROR")
    targets = Path("/trusted/export-targets.txt").read_text().splitlines()
    export_path = Path("/tmp/solution.ndjson")
    error_path = Path("/tmp/export.stderr")
    with export_path.open("wb") as out, error_path.open("wb") as err:
        # Missing required names are rejected by Comparator. Omitting them
        # here avoids the pinned exporter's panic for an absent declaration.
        exported = subprocess.run(["/opt/acceptance/lean4export", "--ignore-missing", "Solution", "--", *targets],
                                  cwd="/tmp/work", env=ENVIRONMENT, stdin=subprocess.DEVNULL,
                                  stdout=out, stderr=err, check=False)
    packet["exporter"] = {"returncode": exported.returncode,
                          "stderr": limited_text(error_path)}
    if exported.returncode:
        return dict(packet, status="SUBMISSION_REJECTED" if exported.returncode == 1 else "INFRASTRUCTURE_ERROR")
    if not 0 < export_path.stat().st_size <= MAX_EXPORT_BYTES:
        return dict(packet, status="OUTPUT_LIMIT_EXCEEDED")
    # The smoke test supplements formal comparison. It runs only in this
    # untrusted stage and cannot grant acceptance on its own.
    packet["smoke"] = command(["/opt/lean/bin/lean", "--run", "/opt/acceptance/Smoke.lean"], "smoke")
    if packet["smoke"]["returncode"]:
        return dict(packet, status="SUBMISSION_REJECTED")
    data = export_path.read_bytes()
    return dict(packet, status="EXPORTED", export_sha256=hashlib.sha256(data).hexdigest(),
                export_b64=base64.b64encode(data).decode("ascii"))


if __name__ == "__main__":
    try:
        response = run(sys.argv[1])
    except Exception as error:
        response = {"protocol": 1, "stage": sys.argv[1] if len(sys.argv) > 1 else None,
                    "status": "INFRASTRUCTURE_ERROR", "error": str(error)}
    print(json.dumps(response, separators=(",", ":")))
