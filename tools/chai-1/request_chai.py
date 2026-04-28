from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path("chai_outputs")


def make_fasta(*, sequence: str, entity_type: str, name: str) -> str:
    sequence = "".join(sequence.split()).upper()
    if not sequence:
        raise ValueError("Sequence is empty")
    if "\n" in name or "|" in name:
        raise ValueError("Name cannot contain newlines or pipe characters")
    return f">{entity_type}|name={name}\n{sequence}\n"


def read_fasta(args: argparse.Namespace) -> str:
    if args.fasta_file:
        fasta = Path(args.fasta_file).read_text()
    elif args.sequence:
        fasta = make_fasta(
            sequence=args.sequence,
            entity_type=args.entity_type,
            name=args.name,
        )
    else:
        raise ValueError("Provide either --fasta-file or --sequence")

    fasta = fasta.strip() + "\n"
    if not fasta.startswith(">"):
        raise ValueError("FASTA must start with a header line beginning with '>'")
    return fasta


def viewer_html(cif_text: str, *, title: str) -> str:
    title_json = json.dumps(title)
    cif_json = json.dumps(cif_text)
    escaped_title = html.escape(title)
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{escaped_title}</title>
  <script src="https://3Dmol.org/build/3Dmol-min.js"></script>
  <style>
    html, body, #viewer {{
      height: 100%;
      width: 100%;
      margin: 0;
    }}
  </style>
</head>
<body>
  <div id="viewer"></div>
  <script>
    const viewer = $3Dmol.createViewer("viewer", {{ backgroundColor: "white" }});
    viewer.addModel({cif_json}, "cif");
    viewer.setStyle({{}}, {{ cartoon: {{ color: "spectrum" }} }});
    viewer.zoomTo();
    viewer.render();
    document.title = {title_json};
  </script>
</body>
</html>
"""


def call_endpoint(
    *,
    url: str,
    api_key: str,
    fasta: str,
    num_trunk_recycles: int,
    num_diffn_timesteps: int,
    num_diffn_samples: int,
    seed: int,
    include_pdb: bool,
    include_viewer_html: bool,
    timeout: int,
) -> dict[str, Any]:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("Install requests to use this client: python -m pip install requests") from exc

    payload = {
        "fasta": fasta,
        "num_trunk_recycles": num_trunk_recycles,
        "num_diffn_timesteps": num_diffn_timesteps,
        "num_diffn_samples": num_diffn_samples,
        "seed": seed,
        "include_pdb": include_pdb,
        "include_viewer_html": include_viewer_html,
    }
    response = requests.post(
        url.rstrip("/") + "/predict",
        headers={"X-API-Key": api_key},
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def structures_from_response(result: dict[str, Any]) -> list[dict[str, Any]]:
    structures = result.get("structures") or result.get("cifs") or result.get("pdbs")
    if not isinstance(structures, list):
        raise ValueError("Response did not contain a structures list")
    return structures


def write_outputs(
    *,
    result: dict[str, Any],
    output_dir: Path,
    visualize: bool,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "response.json").write_text(json.dumps(result, indent=2))

    for structure in structures_from_response(result):
        rank = structure.get("rank", "unknown")

        cif_text = structure.get("cif")
        if cif_text:
            cif_name = structure.get("filename") or f"rank_{rank}.cif"
            cif_path = output_dir / cif_name
            cif_path.write_text(cif_text)

            if visualize:
                viewer_text = structure.get("viewer_html") or viewer_html(
                    cif_text,
                    title=cif_name,
                )
                viewer_name = structure.get("viewer_filename") or f"{cif_path.stem}.html"
                (output_dir / viewer_name).write_text(viewer_text)

        pdb_text = structure.get("pdb")
        if pdb_text:
            pdb_name = structure.get("pdb_filename") or f"rank_{rank}.pdb"
            (output_dir / pdb_name).write_text(pdb_text)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Call the Chai-1 Modal HTTP endpoint and save returned CIF files."
    )
    parser.add_argument("--url", default=os.environ.get("CHAI_MODAL_URL"))
    parser.add_argument("--api-key", default=os.environ.get("CHAI_API_KEY"))
    parser.add_argument("--fasta-file")
    parser.add_argument("--sequence")
    parser.add_argument("--name", default="query")
    parser.add_argument("--entity-type", default="protein")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--num-trunk-recycles", type=int, default=3)
    parser.add_argument("--num-diffn-timesteps", type=int, default=200)
    parser.add_argument("--num-diffn-samples", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--include-pdb", action="store_true")
    parser.add_argument(
        "--visualize",
        action="store_true",
        help="Write a standalone 3Dmol.js HTML viewer for each returned CIF.",
    )
    parser.add_argument(
        "--server-viewer-html",
        action="store_true",
        help="Ask the Modal endpoint to include viewer HTML in the JSON response.",
    )
    parser.add_argument("--timeout", type=int, default=3600)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.url:
        raise SystemExit("Set --url or CHAI_MODAL_URL")
    if not args.api_key:
        raise SystemExit("Set --api-key or CHAI_API_KEY")

    fasta = read_fasta(args)
    result = call_endpoint(
        url=args.url,
        api_key=args.api_key,
        fasta=fasta,
        num_trunk_recycles=args.num_trunk_recycles,
        num_diffn_timesteps=args.num_diffn_timesteps,
        num_diffn_samples=args.num_diffn_samples,
        seed=args.seed,
        include_pdb=args.include_pdb,
        include_viewer_html=args.server_viewer_html,
        timeout=args.timeout,
    )
    write_outputs(
        result=result,
        output_dir=args.output_dir,
        visualize=args.visualize,
    )
    print(f"Wrote outputs to {args.output_dir}")


if __name__ == "__main__":
    main()
