from __future__ import annotations

import argparse
import json
from pathlib import Path

from stl_repair.repair import RepairOptions, analyze_file, repair_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze and repair STL meshes for 3D printing.")
    parser.add_argument("input", help="Input STL/mesh file.")
    parser.add_argument("-o", "--output", help="Output STL path. Defaults to <name>_repaired.stl.")
    parser.add_argument("--analyze-only", action="store_true", help="Only print diagnostics; do not export.")
    parser.add_argument("--no-meshfix", action="store_true", help="Skip MeshFix manifold reconstruction.")
    parser.add_argument("--keep-components", action="store_true", help="Do not join disconnected components.")
    parser.add_argument(
        "--remove-small-components",
        action="store_true",
        help="Let MeshFix remove smaller disconnected components during repair.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    args = parser.parse_args()

    if args.analyze_only:
        report = analyze_file(args.input)
    else:
        report = repair_file(
            args.input,
            output_path=Path(args.output) if args.output else None,
            options=RepairOptions(
                use_meshfix=not args.no_meshfix,
                join_components=not args.keep_components,
                remove_small_components=args.remove_small_components,
            ),
        )

    print(json.dumps(report, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
