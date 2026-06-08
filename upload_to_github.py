#!/usr/bin/env python3
"""
Upload the project files to GitHub without requiring git.exe.

Set GITHUB_TOKEN or GH_TOKEN with a token that has Contents: read/write access,
then run:

  python upload_to_github.py

The upload list is explicit so private broker exports do not accidentally land
in a public repository.
"""
from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path
from typing import Any

import requests


DEFAULT_OWNER = "heelandy"
DEFAULT_REPO = "catalyser_news"
DEFAULT_BRANCH = "main"

UPLOAD_FILES = [
    ".gitignore",
    "CHANGELOG.md",
    "MARKET_DATA_SOURCES.md",
    "README.md",
    "VERSION",
    "market_data_config.json",
    "requirements.txt",
    "upload_to_github.py",
    "futures_data_adapter.py",
    "catalyser_news.py",
    "fetch_nq_yahoo.py",
    "market_data_backfill.py",
    "market_data_verify.py",
    "macro_reaction_study.py",
    "macro_signal_performance.py",
    "macro_signal_trust.py",
    "macro_data_quality.py",
    "macro_probability_validation.py",
    "macro_timing_audit.py",
    "macro_pipeline_runner.py",
    "macro_pipeline_alerts.py",
    "macro_alert_notify.py",
    "dashboard/index.html",
    "dashboard/styles.css",
    "dashboard/app.js",
    "macro_events_history_2026_03_26_06_05.csv",
    "macro_events_history_2024_2026_high.csv",
    "macro_event_clusters_1m_7d.csv",
    "macro_event_clusters_5m_60d.csv",
    "macro_event_clusters_60m_2024_2026.csv",
    "macro_live_signal.csv",
    "macro_reactions_1m.csv",
    "macro_reaction_profiles_1m.csv",
    "macro_reactions_5m.csv",
    "macro_reaction_profiles_5m.csv",
    "macro_reactions_60m.csv",
    "macro_reaction_profiles_60m.csv",
    "macro_releases.csv",
    "macro_releases_calibrated.csv",
    "macro_signal_grades.csv",
    "macro_signal_performance.csv",
    "macro_signal_trust_weights.csv",
    "macro_live_signal_adjusted.csv",
    "macro_data_quality_report.json",
    "macro_data_quality_summary.csv",
    "macro_probability_validation_report.json",
    "macro_probability_validation.csv",
    "macro_timing_audit_report.json",
    "macro_timing_audit.csv",
    "market_data_backfill_report.json",
    "market_data_backfill_plan.csv",
    "market_data_verification_report.json",
    "market_data_verification_summary.csv",
    "market_data_verification_nq_in_batch_summary.csv",
    "news_summary.csv",
    "NQ_1min_data.csv",
    "NQ_5min_data.csv",
    "NQ_15min_data.csv",
    "NQ_60min_data.csv",
    "NQ_F_daily.csv",
    "NQ_F_daily_clean.csv",
]

UPLOAD_PATTERNS = [
    "market_data_verification_NQ_in_*_report.json",
    "market_data_verification_NQ_in_*_summary.csv",
]


class GitHubApi:
    def __init__(self, owner: str, repo: str, token: str) -> None:
        self.base = f"https://api.github.com/repos/{owner}/{repo}"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "nq-macro-catalyst-uploader",
            }
        )

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base}{path}"
        response = self.session.request(method, url, timeout=60, **kwargs)
        if response.status_code >= 400:
            raise SystemExit(f"{method} {path} failed: {response.status_code} {response.text}")
        if response.content:
            return response.json()
        return None

    def maybe_get_ref(self, branch: str) -> dict[str, Any] | None:
        response = self.session.get(f"{self.base}/git/ref/heads/{branch}", timeout=60)
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise SystemExit(f"GET branch ref failed: {response.status_code} {response.text}")
        return response.json()

    def create_blob(self, file_path: Path) -> str:
        content = base64.b64encode(file_path.read_bytes()).decode("ascii")
        payload = {"content": content, "encoding": "base64"}
        data = self.request("POST", "/git/blobs", json=payload)
        return data["sha"]

    def create_tree(self, entries: list[dict[str, str]], base_tree: str | None) -> str:
        payload: dict[str, Any] = {"tree": entries}
        if base_tree:
            payload["base_tree"] = base_tree
        data = self.request("POST", "/git/trees", json=payload)
        return data["sha"]

    def create_commit(self, message: str, tree_sha: str, parent_sha: str | None) -> str:
        payload: dict[str, Any] = {"message": message, "tree": tree_sha}
        if parent_sha:
            payload["parents"] = [parent_sha]
        data = self.request("POST", "/git/commits", json=payload)
        return data["sha"]

    def create_or_update_branch(self, branch: str, commit_sha: str, existing_ref: dict[str, Any] | None) -> None:
        if existing_ref:
            self.request("PATCH", f"/git/refs/heads/{branch}", json={"sha": commit_sha, "force": False})
        else:
            self.request("POST", "/git/refs", json={"ref": f"refs/heads/{branch}", "sha": commit_sha})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload selected project files to GitHub via the REST API.")
    parser.add_argument("--owner", default=DEFAULT_OWNER)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--message", default="Initial macro catalyst pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Print selected files without uploading")
    return parser.parse_args()


def selected_files(root: Path) -> list[Path]:
    files = []
    seen = set()

    def add_file(path: Path) -> None:
        rel = path.relative_to(root).as_posix()
        if rel not in seen:
            seen.add(rel)
            files.append(path)

    for name in UPLOAD_FILES:
        path = root / name
        if path.exists() and path.is_file():
            add_file(path)
        else:
            print(f"skip missing: {name}")

    for pattern in UPLOAD_PATTERNS:
        matches = sorted(path for path in root.glob(pattern) if path.is_file())
        if not matches:
            print(f"skip missing pattern: {pattern}")
        for path in matches:
            add_file(path)

    return files


def main() -> None:
    args = parse_args()
    root = Path.cwd()
    files = selected_files(root)

    print(f"Selected {len(files)} files:")
    for path in files:
        print(f"  {path.relative_to(root).as_posix()}")

    if args.dry_run:
        return

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise SystemExit("Set GITHUB_TOKEN or GH_TOKEN before uploading.")

    api = GitHubApi(args.owner, args.repo, token)
    existing_ref = api.maybe_get_ref(args.branch)
    parent_sha = None
    base_tree = None
    if existing_ref:
        parent_sha = existing_ref["object"]["sha"]
        commit = api.request("GET", f"/git/commits/{parent_sha}")
        base_tree = commit["tree"]["sha"]

    tree_entries = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        blob_sha = api.create_blob(path)
        tree_entries.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob_sha})

    tree_sha = api.create_tree(tree_entries, base_tree)
    commit_sha = api.create_commit(args.message, tree_sha, parent_sha)
    api.create_or_update_branch(args.branch, commit_sha, existing_ref)
    print(f"Uploaded {len(files)} files to https://github.com/{args.owner}/{args.repo}/commit/{commit_sha}")


if __name__ == "__main__":
    main()
