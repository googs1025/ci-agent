"""Unit tests for the log_extractor module."""

from ci_optimizer.log_extractor import (
    compute_signature,
    extract_error_excerpt,
)


class TestExtractErrorExcerpt:
    def test_empty_input(self):
        excerpt, first = extract_error_excerpt("")
        assert excerpt == ""
        assert first is None

    def test_finds_last_anchor(self):
        log = "\n".join(
            [
                "INFO: starting",
                "INFO: step 1",
                "Error: first error",
                "INFO: continuing",
                "FAILED second error",
            ]
        )
        excerpt, first = extract_error_excerpt(log, max_lines=10)
        assert "FAILED second error" in first
        assert "FAILED second error" in excerpt

    def test_github_actions_marker(self):
        log = "line1\n##[error]Process completed with exit code 1\nline3"
        _, first = extract_error_excerpt(log)
        assert "##[error]" in first

    def test_falls_back_to_tail_when_no_anchor(self):
        lines = [f"line-{i}" for i in range(500)]
        log = "\n".join(lines)
        excerpt, first = extract_error_excerpt(log, max_lines=100)
        assert first is None
        # should keep the tail (lines 400-499)
        assert "line-499" in excerpt
        assert "line-400" in excerpt
        assert "line-399" not in excerpt  # before tail window

    def test_respects_max_lines(self):
        lines = [f"line-{i}" for i in range(500)]
        lines.append("Error: oops")
        lines.extend([f"post-{i}" for i in range(500)])
        log = "\n".join(lines)
        excerpt, _ = extract_error_excerpt(log, max_lines=50)
        assert len(excerpt.splitlines()) <= 50

    def test_traceback_anchor(self):
        log = "line\nTraceback (most recent call last):\n  File 'x.py'\nValueError: bad"
        excerpt, first = extract_error_excerpt(log)
        # last matching anchor is Traceback line
        assert "Traceback" in first or "ValueError" in excerpt


class TestComputeSignature:
    def test_stable_across_timestamps(self):
        line_1 = "2026-04-16T10:30:00Z ERROR: connection refused"
        line_2 = "2026-04-16T11:45:00Z ERROR: connection refused"
        sig_1 = compute_signature("test", line_1)
        sig_2 = compute_signature("test", line_2)
        assert sig_1 == sig_2

    def test_stable_across_hex_ids(self):
        line_1 = "pod-abc123 crashed at 0xdeadbeef"
        line_2 = "pod-abc123 crashed at 0xcafef00d"
        sig_1 = compute_signature("k8s", line_1)
        sig_2 = compute_signature("k8s", line_2)
        assert sig_1 == sig_2

    def test_stable_across_paths(self):
        line_1 = "No such file: /home/runner/work/foo/foo/build/out.txt"
        line_2 = "No such file: /github/workspace/build/out.txt"
        sig_1 = compute_signature("build", line_1)
        sig_2 = compute_signature("build", line_2)
        assert sig_1 == sig_2

    def test_stable_across_numbers(self):
        sig_1 = compute_signature("test", "Retry attempt 42 failed")
        sig_2 = compute_signature("test", "Retry attempt 99 failed")
        assert sig_1 == sig_2

    def test_differs_on_different_errors(self):
        sig_1 = compute_signature("test", "npm ERR! peer dep conflict")
        sig_2 = compute_signature("test", "ENOMEM heap out of memory")
        assert sig_1 != sig_2

    def test_differs_on_different_steps(self):
        sig_1 = compute_signature("install", "Error: foo")
        sig_2 = compute_signature("build", "Error: foo")
        assert sig_1 != sig_2

    def test_none_inputs_produce_stable_hash(self):
        sig_1 = compute_signature(None, None)
        sig_2 = compute_signature(None, None)
        assert sig_1 == sig_2
        assert len(sig_1) == 12

    def test_returns_12_chars(self):
        sig = compute_signature("x", "y")
        assert len(sig) == 12
        assert all(c in "0123456789abcdef" for c in sig)
