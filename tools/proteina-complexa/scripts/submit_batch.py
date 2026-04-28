from __future__ import annotations

import argparse
import json
from pathlib import Path

from modal_app import DEFAULT_PIPELINE_CONFIG, design_binder


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Submit Proteina-Complexa Modal jobs from a JSON file.")
    parser.add_argument("jobs_json", type=Path, help="JSON file containing a list of job objects.")
    parser.add_argument("--pipeline-config", default=DEFAULT_PIPELINE_CONFIG)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    jobs = json.loads(args.jobs_json.read_text())
    calls = [
        (
            str(job["task_name"]),
            str(job["run_name"]),
            str(job.get("pipeline_config", args.pipeline_config)),
            list(job.get("overrides", [])),
        )
        for job in jobs
    ]
    for result in design_binder.starmap(calls):
        print(json.dumps(result))


if __name__ == "__main__":
    main()
