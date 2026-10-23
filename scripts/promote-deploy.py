#!/usr/bin/env python3
"""Fast-forward the deploy branch to a commit that passed the deploy gate.

Flux reconciles `deploy`. The Deploy Gate workflow runs this only after the
contract suite and the render check pass for a `main` commit. Updates are
fast-forward only: a slow run for an older commit can never rewind `deploy`,
and a `deploy` holding commits that `main` lacks stops promotion instead of
being overwritten.

The token must be able to update a branch past workflow-file changes, which
the default workflow token cannot do; the workflow mints one from the deploy
promoter GitHub App.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Callable, Optional, Tuple

API_URL = "https://api.github.com"
Response = Tuple[int, dict]
Request = Callable[[str, str, Optional[dict]], Response]

OUTCOMES = {
    "created": "Created `{branch}` at {commit}.",
    "promoted": "Fast-forwarded `{branch}` to {commit}.",
    "current": "`{branch}` already contains {commit}; nothing to promote.",
    "skipped": "{commit} is no longer on `{source}`; not promoting it.",
}


class PromotionError(RuntimeError):
    """Promotion is impossible, or GitHub answered in a way the gate cannot trust."""


def github_client(token: str, api_url: str = API_URL) -> Request:
    def request(method: str, path: str, body: Optional[dict] = None) -> Response:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "anton-deploy-gate",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        call = urllib.request.Request(api_url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(call, timeout=30) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                return error.code, json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return error.code, {"message": raw.decode("utf-8", "replace")}

    return request


def _require(response: Response, expected: int, action: str) -> dict:
    status, body = response
    if status != expected:
        raise PromotionError(f"{action}: GitHub returned HTTP {status}: {body.get('message', body)}")
    return body


def _relation(request: Request, repository: str, base: str, head: str) -> str:
    """GitHub's compare status for base...head: ahead, behind, identical, or diverged."""
    body = _require(
        request("GET", f"/repos/{repository}/compare/{base}...{head}?per_page=1", None),
        200,
        f"compare {base[:12]}...{head[:12]}",
    )
    return body["status"]


def promote(request: Request, repository: str, commit: str, *, branch: str = "deploy",
            source: str = "main", attempts: int = 3) -> str:
    """Move `branch` forward to `commit`; return one of the OUTCOMES keys."""
    # A run can finish after main was rewritten; never promote a dropped commit.
    if _relation(request, repository, commit, source) not in ("ahead", "identical"):
        return "skipped"

    ref_path = f"/repos/{repository}/git/refs/heads/{branch}"
    for _ in range(attempts):
        status, body = request("GET", f"/repos/{repository}/git/ref/heads/{branch}", None)
        if status == 404:
            status, body = request("POST", f"/repos/{repository}/git/refs",
                                   {"ref": f"refs/heads/{branch}", "sha": commit})
            if status == 201:
                return "created"
            if status == 422:  # another run created it first; re-evaluate
                continue
            raise PromotionError(f"create {branch}: GitHub returned HTTP {status}: {body.get('message', body)}")

        current = _require((status, body), 200, f"read {branch}")["object"]["sha"]
        if current == commit:
            return "current"
        relation = _relation(request, repository, current, commit)
        if relation in ("behind", "identical"):
            return "current"
        if relation != "ahead":
            raise PromotionError(
                f"{branch} is at {current[:12]}, which has commits that are not on {source}. "
                f"Promotion stays stopped until {source} contains {branch}; see the deploy guide."
            )

        status, body = request("PATCH", ref_path, {"sha": commit, "force": False})
        if status == 200:
            return "promoted"
        if status != 422:  # 422: the branch moved after it was read; re-evaluate
            raise PromotionError(f"update {branch}: GitHub returned HTTP {status}: {body.get('message', body)}")

    raise PromotionError(f"{branch} kept moving; gave up after {attempts} attempts")


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Fast-forward the deploy branch to a validated commit.")
    parser.add_argument("--repository", required=True, help="owner/name")
    parser.add_argument("--commit", required=True, help="full SHA of the commit that passed the gate")
    parser.add_argument("--branch", default="deploy")
    parser.add_argument("--source", default="main")
    args = parser.parse_args(argv)

    token = os.environ.get("GH_TOKEN", "")
    if not token:
        print("::error::GH_TOKEN is not set; mint the deploy promoter token first", file=sys.stderr)
        return 2
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        print(f"::error::--commit must be a full 40-character SHA, got {args.commit!r}", file=sys.stderr)
        return 2

    client = github_client(token, os.environ.get("GITHUB_API_URL", API_URL))
    try:
        outcome = promote(client, args.repository, args.commit, branch=args.branch, source=args.source)
    except PromotionError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1

    message = OUTCOMES[outcome].format(branch=args.branch, commit=args.commit, source=args.source)
    print(f"::warning::{message}" if outcome == "skipped" else message)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
