from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
import traceback
from typing import Any

from stl_repair.repair import RepairOptions, repair_file


def _write_status(path: Path, payload: dict[str, Any]) -> None:
    current: dict[str, Any] = {}
    if path.exists():
        try:
            current = json.loads(path.read_text())
        except Exception:
            current = {}
    current.update(payload)
    current["updated_at"] = time.time()
    path.write_text(json.dumps(current))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one STL repair job and persist status.")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--no-meshfix", action="store_true")
    parser.add_argument("--keep-components", action="store_true")
    parser.add_argument("--remove-small-components", action="store_true")
    args = parser.parse_args()

    status_path = Path(args.status)
    output_path = Path(args.output)
    _write_status(
        status_path,
        {
            "id": args.job_id,
            "pid": os.getpid(),
            "status": "running",
            "stage": "repairing",
            "started_at": time.time(),
            "output_name": output_path.name,
        },
    )

    try:
        report = repair_file(
            args.input,
            output_path=output_path,
            options=RepairOptions(
                use_meshfix=not args.no_meshfix,
                join_components=not args.keep_components,
                remove_small_components=args.remove_small_components,
            ),
        )
    except Exception as exc:
        _write_status(
            status_path,
            {
                "status": "failed",
                "stage": "failed",
                "error": str(exc),
                "traceback": traceback.format_exc(limit=8),
                "finished_at": time.time(),
            },
        )
        return 1

    _write_status(
        status_path,
        {
            "status": "complete",
            "stage": "complete",
            "report": report,
            "download_url": f"/download/{output_path.name}",
            "finished_at": time.time(),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
