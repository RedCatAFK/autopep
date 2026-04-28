from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from preprocessing import preprocess_pdb_file, sanitize_name, write_preprocessed_outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract PDB sequence and geometry features before Proteina-Complexa ingestion."
    )
    parser.add_argument("pdb_path", type=Path, help="Input .pdb file.")
    parser.add_argument("--chains", default=None, help="Comma-separated chain IDs to include.")
    parser.add_argument("--target-input", default=None, help="Complexa target input spec, e.g. A1-150.")
    parser.add_argument("--target-name", default=None, help="Hydra-safe target name. Defaults to PDB stem.")
    parser.add_argument("--output-dir", type=Path, default=Path("preprocessed"), help="Directory for JSON/FASTA.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    target_name = sanitize_name(args.target_name or args.pdb_path.stem)
    result = preprocess_pdb_file(args.pdb_path, chains=args.chains, target_input=args.target_input)
    outputs = write_preprocessed_outputs(result, args.output_dir)
    target_input = json.dumps(result.target_input) if "," in result.target_input else result.target_input
    summary = {
        "target_name": target_name,
        "length": result.length,
        "sequence": result.sequence,
        "chain_sequences": result.chain_sequences,
        "target_input": result.target_input,
        "outputs": outputs,
        "hydra_overrides": [
            f"++generation.task_name={target_name}",
            f"++generation.target_dict_cfg.{target_name}.target_input={target_input}",
        ],
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
