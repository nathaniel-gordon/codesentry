"""unclosed-resource: the rule that used to crash the whole analyzer."""
from __future__ import annotations

from reviewer.analyzers import analyze_source


def rules(src: str) -> list[str]:
    """Rule ids reported for a snippet."""
    return [f.rule for f in analyze_source("t.py", src)]


def test_bare_open_is_reported():
    src = '"""m."""\n\n\ndef read(path):\n    """d."""\n    fh = open(path)\n    return fh.read()\n'
    assert "unclosed-resource" in rules(src)


def test_analysis_does_not_crash_on_bare_open():
    # Regression: pass_correctness used to raise AttributeError here, and the
    # agent loop turned that into an empty result instead of an error.
    findings = analyze_source("t.py", "def f(p):\n    h = open(p)\n    return h.read()\n")
    assert findings, "analyzer produced nothing for a file containing open()"


def test_with_statement_is_not_reported():
    src = ('"""m."""\n\n\ndef read(path):\n    """d."""\n'
           '    with open(path) as fh:\n        return fh.read()\n')
    assert "unclosed-resource" not in rules(src)


def test_try_finally_close_is_not_reported():
    src = ('"""m."""\n\n\ndef read(path):\n    """d."""\n    fh = open(path)\n'
           '    try:\n        return fh.read()\n    finally:\n        fh.close()\n')
    assert "unclosed-resource" not in rules(src)


def test_contextlib_closing_is_not_reported():
    src = ('"""m."""\nimport contextlib\n\n\ndef read(path):\n    """d."""\n'
           '    with contextlib.closing(open(path)) as fh:\n        return fh.read()\n')
    assert "unclosed-resource" not in rules(src)


def test_handle_stored_on_self_is_not_reported():
    src = ('"""m."""\n\n\nclass Writer:\n    """d."""\n\n    def open_log(self, path):\n'
           '        """d."""\n        self.fh = open(path, "w")\n')
    assert "unclosed-resource" not in rules(src)


def test_returned_handle_is_not_reported():
    src = ('"""m."""\n\n\ndef handle(path):\n    """d."""\n    return open(path)\n')
    assert "unclosed-resource" not in rules(src)
