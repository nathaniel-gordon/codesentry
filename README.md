# CodeSentry — Automated Code Review Agent

> Enforce code quality automatically at every commit. CodeSentry runs a forward-chaining rules engine over diffs and source files, detecting complexity hotspots, security anti-patterns, style violations, and test coverage gaps — then writes structured review comments ready for GitHub PR integration or pre-commit enforcement.

## What CodeSentry Does

- **Forward-chaining rules engine** — declarative rule definitions, chain-of-inference firing
- **Complexity analysis** — cyclomatic complexity, cognitive complexity, deep nesting detection
- **Security scanning** — hardcoded secrets, SQL injection patterns, unsafe deserialization
- **Coverage auditing** — untested functions, missing edge-case tests
- **Pre-commit integration** — runs as a git pre-commit hook; blocks commits on critical findings

## Architecture

```
Source Diff / File Tree
    └─> RuleLoader          (declarative rule definitions)
    └─> ForwardChainer      (inference engine, rule activation)
    └─> ComplexityAnalyzer  (AST-based metrics)
    └─> SecurityScanner     (pattern matching rules)
    └─> ReviewFormatter     (structured PR comment output)
```

## Quickstart

```bash
python -m reviewer demo         # review synthetic code diff
python -m reviewer review src/  # review a real directory
```

## Pre-commit Setup

```bash
pre-commit install
pre-commit run --all-files
```

## Test

```bash
python tests/test_smoke.py
```

---

## 👤 Author & Contact

- **Author**: Nathaniel Gordon
- **Role**: Senior AI & Machine Learning Engineer
- **GitHub**: [github.com/nathaniel-gordon](https://github.com/nathaniel-gordon)
- **Portfolio / Upwork**: [upwork.com/freelancers/~015fe5a704f8943797](https://www.upwork.com/freelancers/~015fe5a704f8943797)
- **Email**: nathanielgordon346@gmail.com
- **Location**: Tallahassee, FL, USA
