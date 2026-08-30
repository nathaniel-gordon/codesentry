"""The two critical-severity heuristics, on code that must and must not fire."""
from __future__ import annotations

import pytest

from reviewer.analyzers import (analyze_source, looks_like_secret_name,
                                looks_like_secret_value, looks_like_sql_statement)

HEADER = '"""Module."""\n\n\n'


def rules(body: str) -> list[str]:
    """Rule ids for a snippet, with a module docstring prepended."""
    return [f.rule for f in analyze_source("t.py", HEADER + body)]


# -- hardcoded-secret ------------------------------------------------------
SECRET_POSITIVES = [
    'API_TOKEN = "sk_live_9f3a2b7c4d5e6f70"\n',
    'stripe_secret = "rk_test_51Hb9xKLm4NpQ7"\n',
    'PRIVATE_KEY = "MIIBOgIBAAJBAKj34GkxFhD"\n',
]
SECRET_NEGATIVES = [
    'API_KEY_HEADER = "X-Api-Key"\n',
    'PASSWORD_FIELD = "user_password"\n',
    'TOKEN_ENV_VAR = "MYAPP_TOKEN"\n',
    'SECRET_NAME = "billing_secret"\n',
    'API_KEY = ""\n',
    'API_KEY = "changeme12345678"\n',
    'PASSWORD = "your-password-here"\n',
    'TOKEN_PATTERN = "aaaaaaaaaaaaaaaaaa"\n',
    'API_KEY_URL = "https://example.com/keys"\n',
]


@pytest.mark.parametrize("body", SECRET_POSITIVES)
def test_hardcoded_secret_fires(body):
    assert "hardcoded-secret" in rules(body)


@pytest.mark.parametrize("body", SECRET_NEGATIVES)
def test_hardcoded_secret_does_not_fire(body):
    assert "hardcoded-secret" not in rules(body)


def test_secret_name_allowlist():
    assert looks_like_secret_name("API_KEY")
    assert not looks_like_secret_name("API_KEY_HEADER")
    assert not looks_like_secret_name("TOKEN_ENV_VAR")
    assert not looks_like_secret_name("retries")


def test_secret_value_needs_two_character_classes():
    assert not looks_like_secret_value("MYAPP_ACCESS_TOKEN")
    assert not looks_like_secret_value("user_password_field")
    assert looks_like_secret_value("sk_live_9f3a2b7c4d5e6f70")


# -- sql-injection ---------------------------------------------------------
SQL_POSITIVES = [
    'def f(c, i):\n    """d."""\n    c.execute(f"DELETE FROM charges WHERE id = {i}")\n',
    'def f(c, i):\n    """d."""\n    q = "SELECT * FROM t WHERE id = " + str(i)\n    c.execute(q)\n',
    'def f(c, i):\n    """d."""\n    q = "UPDATE accounts SET balance = {0}".format(i)\n    c.execute(q)\n',
]
SQL_NEGATIVES = [
    'def f(n):\n    """d."""\n    msg = "update the cache for " + str(n)\n    return msg\n',
    'def f(n):\n    """d."""\n    msg = "select an option from the menu " + str(n)\n    return msg\n',
    'def f(c, i):\n    """d."""\n    c.execute("SELECT * FROM t WHERE id = ?", (i,))\n',
    'def f(n):\n    """d."""\n    return "dropped " + str(n) + " rows"\n',
]


@pytest.mark.parametrize("body", SQL_POSITIVES)
def test_sql_injection_fires(body):
    assert "sql-injection" in rules(body)


@pytest.mark.parametrize("body", SQL_NEGATIVES)
def test_sql_injection_does_not_fire(body):
    assert "sql-injection" not in rules(body)


def test_sql_head_needs_its_mandatory_clause():
    assert looks_like_sql_statement("DELETE FROM charges WHERE id = ")
    assert looks_like_sql_statement("select id from users where name = ")
    assert not looks_like_sql_statement("delete the temporary file ")
    assert not looks_like_sql_statement("update the cache for ")
    assert not looks_like_sql_statement("this SELECT is not at the start FROM here")
