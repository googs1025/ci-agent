"""CI log parsing utilities for failure diagnosis.

Extracts the most relevant error excerpt from a raw CI log and computes
a stable error signature that groups similar failures across runs.

Kept intentionally dependency-free so it is trivial to unit-test.

架构角色：纯函数工具层，在 GitHub 原始日志与 LLM 诊断之间做预处理。
核心职责：从动辄数千行的 CI 日志中定位错误锚点、裁剪出关键片段，
并将易变的运行时细节（时间戳、路径、数字）归一化为稳定签名，用于跨 run 聚类。
与其他模块的关系：被失败诊断服务调用，输出的 (excerpt, signature) 作为 LLM prompt 的输入；
无任何外部依赖，可直接单测。
"""

from __future__ import annotations

import hashlib
import re

# Ordered by specificity: more specific anchors first so we prefer e.g.
# "##[error]" (GitHub Actions marker) over the generic "error:" substring.
ERROR_ANCHORS: tuple[str, ...] = (
    "##[error]",
    "Traceback",
    "Exception",
    "FAILED",
    "FAIL ",
    "fatal:",
    "Error:",
    "ERROR:",
    "error:",
    "✗",
)

_RE_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*")
_RE_HEX = re.compile(r"0x[0-9a-fA-F]{4,}")
_RE_PATH = re.compile(r"(?:/[\w.\-]+){2,}")
_RE_BARE_INT = re.compile(r"\b\d+\b")


def extract_error_excerpt(
    log_text: str,
    max_lines: int = 200,
) -> tuple[str, str | None]:
    """Locate the last error anchor and return the surrounding excerpt.

    Args:
        log_text: raw log content (may contain thousands of lines)
        max_lines: upper bound on excerpt line count

    Returns:
        ``(excerpt, first_error_line)`` where ``first_error_line`` is the
        anchor line that was detected (used for signature hashing), or
        ``None`` if no anchor was found and we fell back to tail-only.

    取最后一个锚点而非第一个：CI 日志里前期的 "error" 字样往往是无关警告，
    真正导致 job 失败的错误几乎总在日志末尾。
    窗口分配 1/3 前文 + 2/3 后文，因为堆栈跟踪通常出现在错误行之后。
    """
    if not log_text:
        return "", None

    lines = log_text.splitlines()
    if not lines:
        return "", None

    anchor_idx = _find_last_anchor(lines)

    if anchor_idx is None:
        # No recognizable error marker — return the tail of the log.
        tail = lines[-max_lines:]
        return "\n".join(tail), None

    # Center the window on the anchor with a slight bias toward after-context
    # (the exception trace usually continues below the marker).
    before = max_lines // 3
    after = max_lines - before
    start = max(0, anchor_idx - before)
    end = min(len(lines), anchor_idx + after)
    excerpt = "\n".join(lines[start:end])
    return excerpt, lines[anchor_idx].strip()


def compute_signature(
    failing_step: str | None,
    first_error_line: str | None,
) -> str:
    """Compute a stable 12-char hash for grouping similar errors.

    Same error in two different runs (with different timestamps, hex IDs,
    line numbers) yields the same signature.

    签名由"步骤名 | 归一化错误行"两部分拼接后取 MD5 前 12 位，
    step 信息确保不同步骤的同类错误不会误判为同一根因。
    """
    step = (failing_step or "unknown").strip()
    line = _normalize_error_line(first_error_line or "")
    raw = f"{step}|{line}".encode("utf-8")
    return hashlib.md5(raw).hexdigest()[:12]


def _find_last_anchor(lines: list[str]) -> int | None:
    """Scan from the end; return index of the last line containing any anchor."""
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        for anchor in ERROR_ANCHORS:
            if anchor in line:
                return i
    return None


def _normalize_error_line(line: str) -> str:
    """Strip volatile substrings so the signature is stable across runs.

    按顺序替换：时间戳 → 十六进制地址 → 文件路径 → 裸数字，
    最后截断至 200 字符防止超长行撑大 hash 输入。
    """
    line = _RE_TIMESTAMP.sub("<TS>", line)
    line = _RE_HEX.sub("<HEX>", line)
    line = _RE_PATH.sub("/<PATH>", line)
    line = _RE_BARE_INT.sub("<N>", line)
    line = line.strip()
    if len(line) > 200:
        line = line[:200]
    return line
