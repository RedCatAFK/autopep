from __future__ import annotations

from collections.abc import Iterable

from .constants import DEFAULT_CHUNK_OVERLAP, DEFAULT_ESM2_MAX_AA
from .io_utils import normalize_sequence


def chunk_sequence(
    sequence: str,
    *,
    max_aa: int = DEFAULT_ESM2_MAX_AA,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    normalized = normalize_sequence(sequence)
    if len(normalized) <= max_aa:
        return [normalized]
    if overlap >= max_aa:
        raise ValueError("overlap must be smaller than max_aa")
    stride = max_aa - overlap
    chunks = []
    for start in range(0, len(normalized), stride):
        chunk = normalized[start : start + max_aa]
        if chunk:
            chunks.append(chunk)
        if start + max_aa >= len(normalized):
            break
    return chunks


def mean_pool_last_hidden_state(last_hidden_state, input_ids, attention_mask, special_token_ids):
    import torch

    token_mask = attention_mask.bool()
    for token_id in special_token_ids:
        token_mask = token_mask & (input_ids != int(token_id))
    token_mask_float = token_mask.unsqueeze(-1).to(last_hidden_state.dtype)
    counts = token_mask_float.sum(dim=1).clamp_min(1.0)
    return (last_hidden_state * token_mask_float).sum(dim=1) / counts


def embed_sequences(
    sequences: Iterable[str],
    *,
    model,
    tokenizer,
    device: str,
    batch_size: int,
    max_aa: int = DEFAULT_ESM2_MAX_AA,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
):
    import numpy as np
    import torch

    sequence_list = [normalize_sequence(sequence) for sequence in sequences]
    expanded: list[tuple[int, str]] = []
    for index, sequence in enumerate(sequence_list):
        for chunk in chunk_sequence(sequence, max_aa=max_aa, overlap=overlap):
            expanded.append((index, chunk))

    if not expanded:
        raise ValueError("No sequences to embed")

    model.eval()
    special_token_ids = set(tokenizer.all_special_ids)
    sums = None
    counts = np.zeros(len(sequence_list), dtype=np.int32)

    for start in range(0, len(expanded), batch_size):
        batch = expanded[start : start + batch_size]
        batch_sequences = [item[1] for item in batch]
        inputs = tokenizer(
            batch_sequences,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=max_aa + 2,
        )
        inputs = {key: value.to(device) for key, value in inputs.items()}
        with torch.inference_mode():
            outputs = model(**inputs)
            pooled = mean_pool_last_hidden_state(
                outputs.last_hidden_state,
                inputs["input_ids"],
                inputs["attention_mask"],
                special_token_ids,
            )
        pooled_np = pooled.detach().cpu().float().numpy()
        if sums is None:
            sums = np.zeros((len(sequence_list), pooled_np.shape[1]), dtype=np.float32)
        for row, (sequence_index, _) in zip(pooled_np, batch, strict=True):
            sums[sequence_index] += row
            counts[sequence_index] += 1

    if sums is None:
        raise ValueError("No embeddings produced")
    counts = counts.clip(min=1).reshape(-1, 1)
    return (sums / counts).astype("float32")
