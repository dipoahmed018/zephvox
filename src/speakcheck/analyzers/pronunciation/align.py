"""Weighted Needleman-Wunsch alignment of expected vs heard phones."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from ...engine.phonemes import deletion_cost, insertion_cost, substitution_cost

OpType = Literal["match", "sub", "del", "ins"]


@dataclass(frozen=True)
class AlignOp:
    op: OpType
    expected: str | None
    heard: str | None
    ref_index: int | None  # index into the expected sequence
    hyp_index: int | None  # index into the heard sequence
    cost: float


def align(
    ref: Sequence[str],
    hyp: Sequence[str],
    sub: Callable[[str, str], float] = substitution_cost,
    dele: Callable[[str], float] = deletion_cost,
    ins: Callable[[str], float] = insertion_cost,
    penalty: Callable[[int, int], float] | None = None,
) -> tuple[float, list[AlignOp]]:
    """`penalty(i, j)` adds a position-dependent cost to pairing ref[i] with hyp[j]
    (e.g. to keep the pairing close in time)."""

    def pair(i: int, j: int) -> float:
        c = sub(ref[i], hyp[j])
        return c + penalty(i, j) if penalty else c

    n, m = len(ref), len(hyp)
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + dele(ref[i - 1])
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + ins(hyp[j - 1])
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            dp[i][j] = min(
                dp[i - 1][j - 1] + pair(i - 1, j - 1),
                dp[i - 1][j] + dele(ref[i - 1]),
                dp[i][j - 1] + ins(hyp[j - 1]),
            )

    ops: list[AlignOp] = []
    i, j = n, m
    while i > 0 or j > 0:
        # Prefer diagonal moves on ties so substitutions read naturally.
        if i > 0 and j > 0:
            c = pair(i - 1, j - 1)
            if abs(dp[i][j] - (dp[i - 1][j - 1] + c)) < 1e-9:
                kind: OpType = "match" if ref[i - 1] == hyp[j - 1] else "sub"
                ops.append(AlignOp(kind, ref[i - 1], hyp[j - 1], i - 1, j - 1, c))
                i, j = i - 1, j - 1
                continue
        if i > 0 and abs(dp[i][j] - (dp[i - 1][j] + dele(ref[i - 1]))) < 1e-9:
            ops.append(AlignOp("del", ref[i - 1], None, i - 1, None, dele(ref[i - 1])))
            i -= 1
        else:
            ops.append(AlignOp("ins", None, hyp[j - 1], None, j - 1, ins(hyp[j - 1])))
            j -= 1
    ops.reverse()
    return dp[n][m], ops
