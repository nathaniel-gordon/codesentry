"""Smoke test for codesentry."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reviewer.analyzers import analyze_source

def test_smoke():
    sample_code = """
def bad_func(x):
    eval(x)
    return x
"""
    findings = analyze_source("test.py", sample_code)
    assert len(findings) > 0
    assert any(f.category == "security" or "eval" in f.message.lower() or f.rule.lower() == "eval" for f in findings)
    print(f"codesentry smoke test passed: {len(findings)} findings detected")

if __name__ == "__main__":
    test_smoke()
