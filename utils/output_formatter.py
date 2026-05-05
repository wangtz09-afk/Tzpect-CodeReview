"""Output formatters for various formats.

Supports SARIF (GitHub Advanced Security), HTML reports,
and enhanced JSON with full schema.
"""
import html
import json
import time
from datetime import datetime
from typing import Optional


def to_sarif(results: list, repo_path: str = "", branch: str = "") -> dict:
    """Convert review results to SARIF format (for GitHub Advanced Security).

    SARIF (Static Analysis Results Interchange Format) is the standard format
    for static analysis tools. Compatible with GitHub Code Scanning.

    Args:
        results: List of PipelineResult objects.
        repo_path: Repository path.
        branch: Git branch name.

    Returns:
        SARIF-formatted dict.
    """
    runs = []

    for r in results:
        review = r.review_result
        issues = review.get("issues", [])

        # Build SARIF rules
        rules = []
        seen_rules = set()
        for issue in issues:
            rule_id = issue.get("type", "unknown").upper()
            if rule_id not in seen_rules:
                seen_rules.add(rule_id)
                severity = issue.get("severity", "medium").lower()
                rules.append({
                    "id": rule_id,
                    "name": rule_id,
                    "shortDescription": {
                        "text": issue.get("description", "")[:120],
                    },
                    "fullDescription": {
                        "text": issue.get("description", ""),
                    },
                    "defaultConfiguration": {
                        "level": _sarif_level(severity),
                    },
                    "helpUri": f"https://github.com/search?q=repo:{repo_path}+{rule_id}",
                })

        # Build SARIF results
        sarif_results = []
        for issue in issues:
            severity = issue.get("severity", "medium").lower()
            location = issue.get("location", "")
            line_num = _parse_line(location)

            sarif_results.append({
                "ruleId": issue.get("type", "unknown").upper(),
                "level": _sarif_level(severity),
                "message": {
                    "text": issue.get("description", ""),
                },
                "locations": [{
                    "physicalLocation": {
                        "artifactLocation": {
                            "uri": r.file_path,
                        },
                        "region": {
                            "startLine": line_num,
                        },
                    },
                }],
                "relatedLocations": [{
                    "id": 1,
                    "message": {
                        "text": issue.get("suggestion", ""),
                    },
                }] if issue.get("suggestion") else [],
            })

        if sarif_results:
            runs.append({
                "tool": {
                    "driver": {
                        "name": "AI Code Review Agent",
                        "version": "1.0.0",
                        "informationUri": "https://github.com/user/code-review-agent",
                        "rules": rules,
                    },
                },
                "results": sarif_results,
                "invocations": [{
                    "endTimeUtc": datetime.utcnow().isoformat() + "Z",
                    "executionSuccessful": True,
                }],
            })

    return {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": runs,
    }


def to_html(results: list, repo_path: str = "", branch: str = "", commit_msg: str = "") -> str:
    """Convert review results to an HTML report.

    Creates a self-contained HTML page with:
    - Summary dashboard
    - Issue tables with severity coloring
    - Expandable code fix previews
    - Fix verification status

    Args:
        results: List of PipelineResult objects.
        repo_path: Repository path.
        branch: Git branch name.
        commit_msg: Git commit message.

    Returns:
        HTML string.
    """
    total_issues = sum(len(r.review_result.get("issues", [])) for r in results)
    total_tokens = sum(r.total_tokens for r in results)
    total_time = sum(r.elapsed_seconds for r in results)

    css = """
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #f6f8fa; color: #24292f; }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 { border-bottom: 1px solid #d0d7de; padding-bottom: 0.3em; }
        .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin: 20px 0; }
        .card { background: #fff; border: 1px solid #d0d7de; border-radius: 6px; padding: 16px; text-align: center; }
        .card .value { font-size: 2em; font-weight: 600; }
        .card .label { font-size: 0.875em; color: #57606a; }
        .severity-critical { color: #d1242f; background: #ffebe9; }
        .severity-high { color: #cf222e; background: #ffcecb; }
        .severity-medium { color: #9a6700; background: #fff8c5; }
        .severity-low { color: #57606a; background: #e8e8e8; }
        .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.85em; font-weight: 500; }
        table { width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #d0d7de; border-radius: 6px; overflow: hidden; }
        th { background: #f6f8fa; padding: 8px 16px; text-align: left; font-weight: 600; border-bottom: 1px solid #d0d7de; }
        td { padding: 8px 16px; border-bottom: 1px solid #d0d7de; }
        .file-header { background: #fff; border: 1px solid #d0d7de; border-radius: 6px; margin: 16px 0; padding: 16px; }
        .fix-preview { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 6px; padding: 12px; font-family: 'SFMono-Regular', Consolas, monospace; font-size: 0.85em; white-space: pre-wrap; overflow-x: auto; max-height: 400px; overflow-y: auto; }
        details { margin: 8px 0; }
        .decision-pass { color: #1a7f37; font-weight: 600; }
        .decision-warn { color: #9a6700; font-weight: 600; }
        .decision-fail { color: #cf222e; font-weight: 600; }
    </style>
    """

    body = f"""
    <div class="container">
        <h1>Code Review Report</h1>
        <p>
            <strong>Project:</strong> {html.escape(repo_path)} |
            <strong>Branch:</strong> {html.escape(branch)} |
            <strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </p>

        <div class="summary">
            <div class="card">
                <div class="value">{len(results)}</div>
                <div class="label">Files Reviewed</div>
            </div>
            <div class="card">
                <div class="value" style="color: #cf222e;">{total_issues}</div>
                <div class="label">Issues Found</div>
            </div>
            <div class="card">
                <div class="value">{total_tokens:,}</div>
                <div class="label">Total Tokens</div>
            </div>
            <div class="card">
                <div class="value">{total_time:.1f}s</div>
                <div class="label">Total Time</div>
            </div>
            <div class="card">
                <div class="value" style="color: #1a7f37;">{sum(1 for r in results if r.fix_code)}</div>
                <div class="label">Files Fixed</div>
            </div>
        </div>
    """

    for r in results:
        review = r.review_result
        quality = review.get("overall_quality", "N/A")
        issues = review.get("issues", [])

        body += f"""
        <div class="file-header">
            <h2><code>{html.escape(r.file_path)}</code></h2>
            <p>
                Language: {html.escape(r.language)} |
                Quality: {html.escape(quality)} |
                Tokens: {r.total_tokens:,} |
                Time: {r.elapsed_seconds:.1f}s
            </p>
        """

        # Verification decision
        if r.verification:
            decision = r.verification.get("final_decision", "?")
            confidence = r.verification.get("confidence", "?")
            can_merge = r.verification.get("can_merge", "?")
            decision_class = "decision-pass" if can_merge else "decision-fail"
            body += f'<p class="{decision_class}">Decision: {html.escape(decision)} (confidence: {html.escape(confidence)}, mergeable: {can_merge})</p>'

        # Fix verification
        if r.fix_code and hasattr(r, 'fix_analysis') and r.fix_analysis:
            valid = r.fix_analysis.is_valid
            risk = r.fix_analysis.regression_risk
            status_class = "decision-pass" if valid else "decision-warn"
            body += f'<p class="{status_class}">Fix Verification: {"Passed" if valid else "Warning"} (regression risk: {risk})</p>'

        if issues:
            body += f"""
            <h3>Issues ({len(issues)})</h3>
            <table>
                <tr><th>#</th><th>Severity</th><th>Type</th><th>Location</th><th>Description</th></tr>
            """
            for i, issue in enumerate(issues, 1):
                sev = issue.get("severity", "unknown").upper()
                sev_lower = issue.get("severity", "unknown").lower()
                loc = html.escape(issue.get("location", "?"))
                desc = html.escape(issue.get("description", "?"))[:150]
                itype = html.escape(issue.get("type", "?"))
                body += f"""
                    <tr>
                        <td>{i}</td>
                        <td><span class="badge severity-{sev_lower}">{sev}</span></td>
                        <td>{itype}</td>
                        <td><code>{loc}</code></td>
                        <td>{desc}</td>
                    </tr>
                """
            body += "</table>"

            # Suggestions
            body += "<h3>Suggestions</h3><ol>"
            for issue in issues:
                suggestion = html.escape(issue.get("suggestion", "N/A"))
                body += f"<li>{suggestion}</li>"
            body += "</ol>"

        # Fix preview
        if r.fix_code:
            body += f"""
            <details>
                <summary><strong>Fixed Code Preview</strong></summary>
                <div class="fix-preview">{html.escape(r.fix_code[:3000])}
{'...' if len(r.fix_code) > 3000 else ''}</div>
            </details>
            """

        body += "</div>"

    # Summary table
    body += """
    <h2>Summary</h2>
    <table>
        <tr><th>File</th><th>Language</th><th>Quality</th><th>Issues</th><th>Tokens</th><th>Decision</th></tr>
    """
    for r in results:
        issues = r.review_result.get("issues", [])
        quality = r.review_result.get("overall_quality", "N/A")
        decision = r.verification.get("final_decision", "?") if r.verification else "N/A"
        body += f"""
        <tr>
            <td><code>{html.escape(r.file_path)}</code></td>
            <td>{html.escape(r.language)}</td>
            <td>{html.escape(quality)}</td>
            <td>{len(issues)}</td>
            <td>{r.total_tokens:,}</td>
            <td>{html.escape(decision)}</td>
        </tr>
        """
    body += "</table></div>"

    return f"<html><head><meta charset='utf-8'>{css}</head><body>{body}</body></html>"


def to_enhanced_json(results: list) -> str:
    """Convert results to enhanced JSON with full schema.

    Includes all metadata, fix analysis, and verification details.

    Args:
        results: List of PipelineResult objects.

    Returns:
        JSON string.
    """
    output = {
        "schema_version": "1.0",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "summary": {
            "total_files": len(results),
            "total_issues": sum(len(r.review_result.get("issues", [])) for r in results),
            "total_tokens": sum(r.total_tokens for r in results),
            "total_time_seconds": sum(r.elapsed_seconds for r in results),
            "files_with_fixes": sum(1 for r in results if r.fix_code),
            "fix_validations_passed": sum(1 for r in results if r.fix_code and r.fix_analysis.is_valid),
            "fix_validations_failed": sum(1 for r in results if r.fix_code and not r.fix_analysis.is_valid),
        },
        "files": [],
    }

    for r in results:
        file_data = {
            "path": r.file_path,
            "language": r.language,
            "quality": r.review_result.get("overall_quality", "N/A"),
            "issues": r.review_result.get("issues", []),
            "issue_count": len(r.review_result.get("issues", [])),
            "stages": r.stages,
            "fix": {
                "generated": bool(r.fix_code),
                "code": r.fix_code[:5000] if r.fix_code else None,
                "iterations": r.fix_iterations,
                "analysis": {
                    "is_valid": r.fix_analysis.is_valid,
                    "regression_risk": r.fix_analysis.regression_risk,
                    "lines_added": r.fix_analysis.lines_added,
                    "lines_removed": r.fix_analysis.lines_removed,
                    "issues": [
                        {
                            "severity": i.severity,
                            "category": i.category,
                            "description": i.description,
                        }
                        for i in r.fix_analysis.issues
                    ],
                } if r.fix_code else None,
            },
            "test": r.test_result,
            "verification": r.verification,
            "tokens": r.total_tokens,
            "elapsed_seconds": round(r.elapsed_seconds, 2),
            "errors": r.errors,
        }
        output["files"].append(file_data)

    return json.dumps(output, ensure_ascii=False, indent=2)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _sarif_level(severity: str) -> str:
    """Map severity to SARIF level."""
    mapping = {
        "critical": "error",
        "high": "error",
        "medium": "warning",
        "low": "note",
    }
    return mapping.get(severity.lower(), "warning")


def _parse_line(location: str) -> int:
    """Extract line number from location string like 'line 42' or 'L42'."""
    import re
    match = re.search(r'line\s+(\d+)|L(\d+)|:(\d+)', location, re.IGNORECASE)
    if match:
        return int(match.group(1) or match.group(2) or match.group(3))
    return 1
