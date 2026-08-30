"""SARIF 2.1.0 output, so findings can be uploaded to GitHub code scanning.

SARIF is the only reason a static analyzer's results ever show up inline on a
pull request, and the `RULES` table already carries everything the format wants
per rule: a severity to map onto a level, a category to tag with, and a `why`
paragraph that becomes the rule's full description.

Two details matter for the format to be useful rather than merely valid:

* `partialFingerprints` deliberately excludes the line number. GitHub dedupes
  alerts across commits on the fingerprint, so hashing the line would report a
  brand-new alert every time an unrelated edit shifted the file.
* `invocations[0].executionSuccessful` is false when any file failed to
  analyze, and each failure is a `toolExecutionNotification`. A SARIF file that
  claims success while the analyzer crashed is how a silent regression ships.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from .analyzers import RULES, Finding, RuleSpec
from .review import ReviewResult

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
TOOL_NAME = "codesentry"
INFORMATION_URI = "https://github.com/nathaniel-gordon/codesentry"
FINGERPRINT_KEY = "codesentry/v1"

#: SARIF has three result levels; the tool has four severities.
LEVEL_FOR_SEVERITY = {"critical": "error", "high": "error",
                      "medium": "warning", "low": "note"}
#: GitHub reads `security-severity` as a CVSS-like number to bucket alerts.
SECURITY_SEVERITY = {"critical": "9.0", "high": "7.0", "medium": "4.0", "low": "2.0"}


def _rule_name(rule_id: str) -> str:
    """`eval-exec` -> `EvalExec`, the identifier form SARIF viewers display."""
    return "".join(part.capitalize() for part in rule_id.split("-"))


def _short_description(rule_id: str, spec: RuleSpec) -> str:
    """First sentence of the rule's rationale, used as the one-line summary."""
    head = spec.why.split(";")[0].split(". ")[0].strip()
    return head[:1].upper() + head[1:] if head else rule_id


def _driver_rules() -> tuple[list[dict], dict[str, int]]:
    """Every rule as a SARIF reportingDescriptor, plus id -> index."""
    descriptors: list[dict] = []
    index: dict[str, int] = {}
    for position, (rule_id, spec) in enumerate(sorted(RULES.items())):
        index[rule_id] = position
        descriptors.append({
            "id": rule_id,
            "name": _rule_name(rule_id),
            "shortDescription": {"text": _short_description(rule_id, spec)},
            "fullDescription": {"text": spec.why},
            "help": {"text": spec.why,
                     "markdown": f"**{rule_id}** ({spec.category})\n\n{spec.why}"},
            "defaultConfiguration": {"level": LEVEL_FOR_SEVERITY[spec.severity]},
            "properties": {
                "tags": [spec.category, spec.severity],
                "category": spec.category,
                "severity": spec.severity,
                "security-severity": SECURITY_SEVERITY[spec.severity],
            },
        })
    return descriptors, index


def fingerprint(finding: Finding) -> str:
    """Line-independent identity, so an alert survives edits above it."""
    payload = "|".join((finding.file, finding.rule, finding.function,
                        finding.message))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _result(finding: Finding, index: dict[str, int]) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "ruleId": finding.rule,
        "level": LEVEL_FOR_SEVERITY.get(finding.severity, "warning"),
        "message": {"text": f"{finding.message} Fix: {finding.suggestion}"},
        "locations": [{
            "physicalLocation": {
                "artifactLocation": {"uri": finding.file, "uriBaseId": "%SRCROOT%"},
                "region": {"startLine": max(1, finding.line)},
            },
        }],
        "partialFingerprints": {FINGERPRINT_KEY: fingerprint(finding)},
        "properties": {"category": finding.category, "severity": finding.severity,
                       "risk": round(finding.risk, 3)},
    }
    if finding.rule in index:
        entry["ruleIndex"] = index[finding.rule]
    if finding.function:
        entry["locations"][0]["logicalLocations"] = [
            {"name": finding.function, "kind": "function"}]
    return entry


def render_sarif(result: ReviewResult, version: str = "0.3.0") -> dict[str, Any]:
    """Build the SARIF log for one review as a plain dict."""
    descriptors, index = _driver_rules()
    notifications = [{
        "level": "error",
        "message": {"text": error.message},
        "descriptor": {"id": "analysis-failure"},
        "locations": [{"physicalLocation": {
            "artifactLocation": {"uri": error.file, "uriBaseId": "%SRCROOT%"}}}],
    } for error in result.errors if error.file]
    root_uri = "file:///" + os.path.abspath(result.root).replace(os.sep, "/").lstrip("/")
    return {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [{
            "tool": {"driver": {
                "name": TOOL_NAME,
                "version": version,
                "informationUri": INFORMATION_URI,
                "rules": descriptors,
            }},
            "originalUriBaseIds": {"%SRCROOT%": {"uri": root_uri.rstrip("/") + "/"}},
            "invocations": [{
                "executionSuccessful": result.ok,
                "toolExecutionNotifications": notifications,
            }],
            "results": [_result(f, index) for f in result.findings],
            "properties": {
                "healthScore": round(result.health.score, 1),
                "healthGrade": result.health.grade,
                "mode": result.mode,
            },
        }],
    }


def write_sarif(result: ReviewResult, path: str, version: str = "0.3.0") -> str:
    """Write the SARIF log to `path`; returns the absolute path."""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(render_sarif(result, version), handle, indent=2)
    return os.path.abspath(path)
