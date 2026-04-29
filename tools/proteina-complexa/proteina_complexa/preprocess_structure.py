from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .preprocessing import preprocess_structure_file, sanitize_name, write_preprocessed_outputs


def preprocess_structure_summary(
    structure_path: Path | str,
    *,
    chains: str | None = None,
    target_input: str | None = None,
    target_name: str | None = None,
    output_dir: Path | str = Path("preprocessed"),
) -> dict:
    path = Path(structure_path)
    safe_target_name = sanitize_name(target_name or path.stem)
    result = preprocess_structure_file(path, chains=chains, target_input=target_input)
    outputs = write_preprocessed_outputs(result, output_dir)
    hydra_target_input = json.dumps(result.target_input) if "," in result.target_input else result.target_input
    return {
        "target_name": safe_target_name,
        "length": result.length,
        "sequence": result.sequence,
        "chain_sequences": result.chain_sequences,
        "target_input": result.target_input,
        "outputs": outputs,
        "hydra_overrides": [
            f"++generation.task_name={safe_target_name}",
            f"++generation.target_dict_cfg.{safe_target_name}.source=preprocessed_targets",
            f"++generation.target_dict_cfg.{safe_target_name}.target_filename={safe_target_name}",
            f"++generation.target_dict_cfg.{safe_target_name}.target_input={hydra_target_input}",
        ],
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract CIF/PDB sequence and geometry features before Proteina-Complexa ingestion."
    )
    parser.add_argument("structure_path", type=Path, help="Input .cif, .mmcif, or .pdb file.")
    parser.add_argument("--chains", default=None, help="Comma-separated chain IDs to include.")
    parser.add_argument("--target-input", default=None, help="Complexa target input spec, e.g. A1-150.")
    parser.add_argument("--target-name", default=None, help="Hydra-safe target name. Defaults to structure stem.")
    parser.add_argument("--output-dir", type=Path, default=Path("preprocessed"), help="Directory for JSON/FASTA.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    summary = preprocess_structure_summary(
        args.structure_path,
        chains=args.chains,
        target_input=args.target_input,
        target_name=args.target_name,
        output_dir=args.output_dir,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
