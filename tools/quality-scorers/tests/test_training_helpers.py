from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.datasets import (  # noqa: E402
    build_pseudosequence_aliases,
    extract_anupp_download_links,
    mhci_el_split,
    mhcii_el_split,
    parse_hla_el_rows,
    parse_labeled_hex_fasta,
    parse_pseudosequence_text,
)
from training.embedding import chunk_sequence, mean_pool_last_hidden_state  # noqa: E402
from training.io_utils import is_valid_sequence, normalize_sequence, sequence_hash  # noqa: E402


class SequenceUtilityTests(unittest.TestCase):
    def test_normalize_sequence_removes_whitespace_and_uppercases(self) -> None:
        self.assertEqual(normalize_sequence(" acd\nef "), "ACDEF")

    def test_valid_sequence_rejects_non_standard_tokens(self) -> None:
        self.assertTrue(is_valid_sequence("ACDEFGHIKLMNPQRSTVWY"))
        self.assertFalse(is_valid_sequence("ACDX"))
        self.assertFalse(is_valid_sequence(""))

    def test_sequence_hash_uses_normalized_sequence(self) -> None:
        self.assertEqual(sequence_hash(" acd "), sequence_hash("ACD"))

    def test_chunk_sequence_uses_overlap(self) -> None:
        chunks = chunk_sequence("A" * 12, max_aa=5, overlap=2)
        self.assertEqual(chunks, ["A" * 5, "A" * 5, "A" * 5, "A" * 3])


class AnuppParserTests(unittest.TestCase):
    def test_extract_anupp_download_links_preserves_dataset_order(self) -> None:
        html = """
        <a href="train.fa">Download</a>
        <a href="/test.fa">Download</a>
        <a href="../amy17.fa">Download</a>
        <a href="amy37.fa">Download</a>
        """
        links = extract_anupp_download_links(html, "https://example.org/root/page/")
        self.assertEqual(links["hex1279"], "https://example.org/root/page/train.fa")
        self.assertEqual(links["hex142"], "https://example.org/test.fa")
        self.assertEqual(links["amy17"], "https://example.org/root/amy17.fa")
        self.assertEqual(links["amy37"], "https://example.org/root/page/amy37.fa")

    def test_parse_labeled_hex_fasta_infers_common_labels(self) -> None:
        text = ">p1 amyloidogenic\nAAAAAA\n>p2 non-amyloidogenic\nCCCCCC\n"
        rows, unresolved = parse_labeled_hex_fasta(text, dataset="hex1279")
        self.assertEqual(unresolved, [])
        self.assertEqual([row["label"] for row in rows], [1, 0])

    def test_parse_labeled_hex_fasta_reports_unresolved_headers(self) -> None:
        text = ">unlabeled\nAAAAAA\n"
        rows, unresolved = parse_labeled_hex_fasta(text, dataset="hex1279")
        self.assertEqual(rows, [])
        self.assertEqual(unresolved, ["unlabeled"])

    def test_parse_labeled_hex_fasta_uses_manual_labels_by_sequence(self) -> None:
        text = ">unlabeled\nAAAAAA\n"
        rows, unresolved = parse_labeled_hex_fasta(
            text,
            dataset="hex1279",
            manual_labels={"AAAAAA": 1},
        )
        self.assertEqual(unresolved, [])
        self.assertEqual(rows[0]["label"], 1)


class HlaParserTests(unittest.TestCase):
    def test_parse_pseudosequence_text_filters_invalid_sequences(self) -> None:
        parsed = parse_pseudosequence_text("HLA-A01:01 ACDE\nbad ACX\n")
        self.assertEqual(parsed, {"HLA-A01:01": "ACDE"})

    def test_parse_hla_el_rows_resolves_direct_alleles(self) -> None:
        pseudo = {"HLA-A01:01": "ACDEFG"}
        rows, stats = parse_hla_el_rows(
            "TEAARELGY 1 HLA-A01:01\nBADX 1 HLA-A01:01\nPEPTIDE 1 missing\n",
            mhc_class="MHC-I",
            split="train",
            source_file="c002_el",
            pseudosequence_aliases=build_pseudosequence_aliases(pseudo),
            allelelist={},
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["allele"], "HLA-A01:01")
        self.assertEqual(stats["included"], 1)
        self.assertEqual(stats["invalid_peptide"], 1)
        self.assertEqual(stats["unresolved_hla"], 1)

    def test_parse_hla_el_rows_skips_ambiguous_cell_lines(self) -> None:
        pseudo = {"HLA-A01:01": "ACDEFG", "HLA-B07:02": "CDEFGH"}
        rows, stats = parse_hla_el_rows(
            "TEAARELGY 1 Line.1\n",
            mhc_class="MHC-I",
            split="train",
            source_file="c002_el",
            pseudosequence_aliases=build_pseudosequence_aliases(pseudo),
            allelelist={"Line.1": ["HLA-A01:01", "HLA-B07:02"]},
        )
        self.assertEqual(rows, [])
        self.assertEqual(stats["ambiguous_cell_line"], 1)

    def test_hla_split_helpers_are_deterministic(self) -> None:
        self.assertEqual(mhci_el_split(Path("c000_el")), "test")
        self.assertEqual(mhci_el_split(Path("c001_el")), "valid")
        self.assertEqual(mhci_el_split(Path("c002_el")), "train")
        self.assertEqual(mhcii_el_split(Path("test_EL0.txt")), "test")
        self.assertEqual(mhcii_el_split(Path("train_EL4.txt")), "valid")
        self.assertEqual(mhcii_el_split(Path("train_EL0.txt")), "train")


@unittest.skipIf(importlib.util.find_spec("torch") is None, "torch is not installed locally")
class EmbeddingPoolingTests(unittest.TestCase):
    def test_mean_pool_excludes_special_and_padding_tokens(self) -> None:
        import torch

        hidden = torch.tensor(
            [
                [
                    [100.0, 100.0],
                    [1.0, 3.0],
                    [3.0, 5.0],
                    [200.0, 200.0],
                    [0.0, 0.0],
                ]
            ]
        )
        input_ids = torch.tensor([[0, 5, 6, 2, 1]])
        attention_mask = torch.tensor([[1, 1, 1, 1, 0]])
        pooled = mean_pool_last_hidden_state(hidden, input_ids, attention_mask, {0, 1, 2})
        self.assertTrue(torch.equal(pooled, torch.tensor([[2.0, 4.0]])))


if __name__ == "__main__":
    unittest.main()

