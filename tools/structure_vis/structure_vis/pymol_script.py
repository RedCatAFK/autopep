from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SUPPORTED_SUFFIXES = {".pdb", ".cif", ".mmcif", ".pdb.gz", ".cif.gz", ".mmcif.gz"}


@dataclass(frozen=True)
class StructureInput:
    path: Path
    object_name: str
    role: str = "structure"


def validate_structure_files(paths: Iterable[Path]) -> list[Path]:
    resolved: list[Path] = []
    for raw_path in paths:
        path = raw_path.expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Structure file does not exist: {path}")
        if structure_suffix(path) not in SUPPORTED_SUFFIXES:
            suffixes = ", ".join(sorted(SUPPORTED_SUFFIXES))
            raise ValueError(f"Unsupported structure file type for {path}. Expected one of: {suffixes}")
        resolved.append(path)
    if not resolved:
        raise ValueError("At least one .pdb, .cif, or .mmcif file is required.")
    return resolved


def structure_suffix(path: Path) -> str:
    suffixes = path.suffixes
    if len(suffixes) >= 2 and suffixes[-1].lower() == ".gz":
        return "".join(suffix.lower() for suffix in suffixes[-2:])
    return path.suffix.lower()


def object_name_for(path: Path, index: int, role: str = "obj") -> str:
    stem = path.name
    for suffix in sorted(SUPPORTED_SUFFIXES, key=len, reverse=True):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    stem = re.sub(r"[^A-Za-z0-9_]+", "_", stem).strip("_") or "structure"
    return f"{role}_{index:02d}_{stem}"


def build_inputs(paths: Iterable[Path], role: str = "obj", start_index: int = 1) -> list[StructureInput]:
    return [
        StructureInput(path=path, object_name=object_name_for(path, index, role=role), role=role)
        for index, path in enumerate(paths, start=start_index)
    ]


def pml_string(value: str | Path) -> str:
    text = str(value)
    return '"' + text.replace("\\", "/").replace('"', '\\"') + '"'


def pml_ident(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", value)


def common_preamble() -> str:
    return """reinitialize
set retain_order, 1
set bg_rgb, [1, 1, 1]
set antialias, 2
set depth_cue, 0
set ray_opaque_background, 0
set cartoon_fancy_helices, 1
set cartoon_smooth_loops, 1
set stick_radius, 0.16
set sphere_scale, 0.25
"""


def build_multi_view_script(inputs: list[StructureInput], style: str = "cartoon") -> str:
    colors = [
        "marine",
        "orange",
        "forest",
        "magenta",
        "cyan",
        "salmon",
        "purpleblue",
        "yelloworange",
    ]
    lines = [common_preamble()]
    for item in inputs:
        lines.append(f"load {pml_string(item.path)}, {item.object_name}")
    lines.extend(
        [
            "hide everything, all",
            f"show {style}, all",
            "show sticks, organic",
            "show spheres, inorganic or solvent",
        ]
    )
    for index, item in enumerate(inputs):
        color = colors[index % len(colors)]
        lines.append(f"color {color}, {item.object_name}")
        lines.append(f"set cartoon_transparency, 0.08, {item.object_name}")
    lines.extend(
        [
            "set two_sided_lighting, 1",
            "orient all",
            "zoom all, 6",
            "group loaded_structures, " + " ".join(item.object_name for item in inputs),
        ]
    )
    return "\n".join(lines) + "\n"


def build_compare_script(
    reference: StructureInput,
    mobile: StructureInput,
    extras: list[StructureInput] | None = None,
    style: str = "cartoon",
    distance_cutoff: float = 2.0,
) -> str:
    extras = extras or []
    all_inputs = [reference, mobile, *extras]
    lines = [common_preamble()]
    for item in all_inputs:
        lines.append(f"load {pml_string(item.path)}, {item.object_name}")
    lines.extend(
        [
            "hide everything, all",
            f"show {style}, all",
            "show sticks, organic",
            "color slate, all",
            f"color marine, {reference.object_name}",
            f"color orange, {mobile.object_name}",
        ]
    )
    for item in extras:
        lines.append(f"set cartoon_transparency, 0.65, {item.object_name}")
    lines.extend(
        [
            f"super {mobile.object_name} and polymer.protein and name CA, {reference.object_name} and polymer.protein and name CA",
            f"set cartoon_transparency, 0.18, {reference.object_name}",
            f"set cartoon_transparency, 0.18, {mobile.object_name}",
            "set dash_width, 2.5",
            "set dash_gap, 0.25",
            "set label_size, 16",
            _embedded_diff_python(reference.object_name, mobile.object_name, distance_cutoff),
            "group comparison, "
            + " ".join([reference.object_name, mobile.object_name, "diff_distances", "diff_summary"]),
            "orient comparison",
            "zoom comparison, 6",
        ]
    )
    return "\n".join(lines) + "\n"


def _embedded_diff_python(reference_object: str, mobile_object: str, distance_cutoff: float) -> str:
    payload = {
        "reference_object": reference_object,
        "mobile_object": mobile_object,
        "distance_cutoff": distance_cutoff,
    }
    return f"""python
from pymol import cmd, stored
import math

payload = {json.dumps(payload, sort_keys=True)}
ref = payload["reference_object"]
mob = payload["mobile_object"]
cutoff = float(payload["distance_cutoff"])

def atom_key(atom):
    return (atom.chain, atom.resi)

ref_atoms = cmd.get_model(f"{{ref}} and polymer.protein and name CA").atom
mob_atoms = cmd.get_model(f"{{mob}} and polymer.protein and name CA").atom
mob_by_key = {{atom_key(atom): atom for atom in mob_atoms}}
deviations = []

for ref_atom in ref_atoms:
    mob_atom = mob_by_key.get(atom_key(ref_atom))
    if mob_atom is None:
        continue
    distance = math.dist(ref_atom.coord, mob_atom.coord)
    deviations.append((atom_key(ref_atom), distance, ref_atom, mob_atom))

stored.structure_diff_b = {{}}
for (chain, resi), distance, _ref_atom, _mob_atom in deviations:
    stored.structure_diff_b[(ref, chain, resi)] = distance
    stored.structure_diff_b[(mob, chain, resi)] = distance

cmd.alter(f"{{ref}} or {{mob}}", "b=stored.structure_diff_b.get((model, chain, resi), 0.0)")
maximum = max([distance for _key, distance, _ref_atom, _mob_atom in deviations] or [1.0])
cmd.spectrum("b", "blue_white_red", f"{{ref}} or {{mob}}", minimum=0.0, maximum=maximum)

for index, ((chain, resi), distance, ref_atom, mob_atom) in enumerate(deviations, start=1):
    if distance < cutoff:
        continue
    safe_chain = "".join(ch if ch.isalnum() else "_" for ch in chain) or "blank"
    safe_resi = "".join(ch if ch.isalnum() else "_" for ch in resi) or str(index)
    distance_name = f"diff_{{index:03d}}_{{safe_chain}}_{{safe_resi}}"
    cmd.distance(distance_name, f"{{ref}} and index {{ref_atom.index}}", f"{{mob}} and index {{mob_atom.index}}")
    cmd.set("dash_color", "red", distance_name)
    cmd.set("dash_radius", 0.08, distance_name)
    cmd.group("diff_distances", distance_name)

if deviations:
    rmsd = math.sqrt(sum(distance * distance for _key, distance, _ra, _ma in deviations) / len(deviations))
    largest = max(deviations, key=lambda item: item[1])
    label = f"CA pairs: {{len(deviations)}} | RMSD after super: {{rmsd:.2f}} A | max: {{largest[1]:.2f}} A at {{largest[0][0]}}{{largest[0][1]}}"
else:
    label = "No matched CA atoms found. Check chain and residue numbering."

cmd.pseudoatom("diff_summary", pos=[0, 0, 0], label=label)
cmd.hide("spheres", "diff_summary")
cmd.show("labels", "diff_summary")
cmd.rebuild()
python end"""


def write_manifest(
    output_dir: Path,
    command: str,
    inputs: list[StructureInput],
    pml_path: Path,
    metadata: dict[str, object] | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "command": command,
        "pymol_script": str(pml_path),
        "inputs": [
            {"path": str(item.path), "object_name": item.object_name, "role": item.role}
            for item in inputs
        ],
        "metadata": metadata or {},
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path
