#!/usr/bin/env python3
"""Verify that commits reach the cluster only through the Deploy Gate (ADR 0045).

Run with `mise exec -- python3 scripts/verify-deploy-gate.py <journey>`:

  steady      One read of the committed sync ref, the FluxInstance, the
              flux-system source, deploy against main, the gate run for main's
              head, and every Kustomization.
  follow SHA  After a push to main, wait until the cluster applies SHA (or a
              later main commit) from deploy, then prove it arrived only after
              the gate's Promote job finished.
  hook        Exercise the pre-push hook in a throwaway clone against a local
              bare remote. Nothing is pushed to GitHub or to this checkout.

`steady` and `follow` only read Git, GitHub and the cluster. Pass
`--evidence PATH` to keep a JSON record; `.private/` is ignored by Git.
Exit codes: 0 pass, 1 fail, 3 not settled yet.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEPLOY_REF = "refs/heads/deploy"
HELMRELEASE = "kubernetes/apps/flux-system/flux-instance/app/helmrelease.yaml"
WORKFLOW = "deploy-gate.yaml"
# A page outside the canonical docs sections, which validate-documentation.py
# (part of contracts:fast) rejects; the hook journey commits it to prove a refusal.
PROBE = "docs/docs/verify-deploy-gate-probe.md"
CLOCK_SKEW = 5  # seconds allowed between this machine's clock and GitHub's
PASS, WAIT, FAIL = "pass", "wait", "fail"
EXIT = {PASS: 0, FAIL: 1, WAIT: 3}
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def run(cmd, cwd=REPO, env=None, timeout=120):
    return subprocess.run([str(part) for part in cmd], cwd=cwd, env=env, capture_output=True,
                          text=True, timeout=timeout)


def output(cmd, cwd=REPO):
    result = run(cmd, cwd=cwd)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, cmd[:3]))} failed: {result.stderr.strip()[:300]}")
    return result.stdout.strip()


def now():
    return datetime.now(timezone.utc)


def stamp(moment):
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z") if moment else None


def parse_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None


def short(sha):
    return (sha or "")[:12]


def source_ref(spec_ref):
    """Normalize a GitRepository spec.ref to a full ref name."""
    spec_ref = spec_ref or {}
    if spec_ref.get("name"):
        return spec_ref["name"]
    if spec_ref.get("branch"):
        return f"refs/heads/{spec_ref['branch']}"
    return json.dumps(spec_ref, sort_keys=True)


def overall(statuses):
    statuses = list(statuses)
    if FAIL in statuses:
        return FAIL
    return WAIT if WAIT in statuses else PASS


# ---------------------------------------------------------------- evaluation


def evaluate_steady(state):
    """Return checks for one snapshot; see gather_steady for the state's shape."""
    checks = []

    def add(name, status, detail):
        checks.append({"check": name, "status": status, "detail": detail})

    intent = state["intent"]
    add("intent", PASS if intent == DEPLOY_REF else FAIL, f"main's {HELMRELEASE} sets sync.ref {intent}")

    instance = state["instance"]
    if instance["ref"] != DEPLOY_REF:
        add("instance", FAIL, f"FluxInstance sync.ref is {instance['ref']}; commits skip the gate")
    else:
        add("instance", PASS if instance["ready"] else WAIT,
            f"FluxInstance syncs {DEPLOY_REF}" + ("" if instance["ready"] else "; not Ready yet"))

    source = state["source"]
    reads = source_ref(source["ref"])
    add("source", PASS if reads == DEPLOY_REF else FAIL, f"flux-system GitRepository reads {reads}")

    main, deploy, behind = state["main"], state["deploy"], state["behind"]
    run_ = state["run"]
    if not deploy:
        add("promotion", FAIL, "the deploy branch does not exist")
    elif not state["deploy_on_main"]:
        add("promotion", FAIL, "deploy has commits that main lacks; promotion is stopped")
    elif behind == 0:
        add("promotion", PASS, f"deploy is at main {short(main)}")
    elif not run_ or run_["headSha"] != main:
        add("promotion", WAIT, f"deploy is {behind} behind main; no gate run for {short(main)} yet")
    elif run_["status"] != "completed":
        add("promotion", WAIT, f"deploy is {behind} behind main; the gate is {run_['status']} for {short(main)}")
    elif run_["conclusion"] == "success":
        add("promotion", FAIL, f"the gate passed {short(main)} but deploy is still {behind} behind")
    else:
        add("promotion", FAIL, f"held: the gate run for {short(main)} ended {run_['conclusion']}; "
                               f"deploy stays {behind} behind until a fix lands on main ({run_['url']})")

    want = f"{DEPLOY_REF}@sha1:{deploy}"
    revision = source["revision"]
    if reads == DEPLOY_REF and deploy:
        if not source["ready"]:
            add("fetch", FAIL, f"flux-system GitRepository is not Ready at {revision}")
        elif revision == want:
            add("fetch", PASS, f"Flux fetched deploy at {short(deploy)}")
        else:
            add("fetch", WAIT, f"Flux is at {revision}; deploy is {short(deploy)} (the source polls every minute)")

    lagging, failed = [], []
    for kustomization in state["kustomizations"]:
        if kustomization["ready"] == "True":
            if kustomization["source"] == "flux-system" and kustomization["applied"] != revision:
                lagging.append(kustomization["name"])
        elif kustomization["ready"] == "Unknown" or kustomization["reason"] in ("Progressing", "DependencyNotReady"):
            lagging.append(kustomization["name"])
        else:
            failed.append(f"{kustomization['name']} ({kustomization['reason']})")
    root = sum(1 for k in state["kustomizations"] if k["source"] == "flux-system")
    if failed:
        add("apply", FAIL, "not Ready: " + ", ".join(sorted(failed)))
    elif lagging:
        add("apply", WAIT, f"{len(lagging)} Kustomization(s) still applying: " + ", ".join(sorted(lagging)[:8]))
    else:
        add("apply", PASS, f"all {root} Kustomizations on flux-system applied {revision}")
    return checks


def evaluate_follow(sha, observed, run_, jobs):
    """Judge one follow journey.

    observed: {"reads", "seen_sha", "seen_at", "applied_at"} from watching the cluster.
    run_ and jobs: the gate run for the commit the cluster applied (or for SHA) and its jobs.
    """
    if observed["reads"] != DEPLOY_REF:
        return FAIL, f"flux-system reads {observed['reads']}; the gate cannot hold commits back"
    job = {j["name"]: j for j in jobs}
    if observed["seen_at"] is None:
        if run_ and run_["status"] == "completed" and run_["conclusion"] != "success":
            return FAIL, (f"held: the gate run for {short(sha)} ended {run_['conclusion']}; "
                          "the cluster kept the last passing commit")
        return WAIT, f"the cluster has not fetched {short(sha)} from deploy yet"
    seen = observed["seen_sha"]
    if not run_:
        return FAIL, f"the cluster applied {short(seen)} but no gate run exists for it"
    for name in ("Contracts", "Render", "Promote"):
        if job.get(name, {}).get("conclusion") != "success":
            return FAIL, (f"the cluster applied {short(seen)} although the gate's {name} job "
                          f"ended {job.get(name, {}).get('conclusion')}")
    promoted = parse_time(job["Promote"]["completedAt"])
    lead = (promoted - observed["seen_at"]).total_seconds()
    if lead > CLOCK_SKEW:
        return FAIL, f"the cluster fetched {short(seen)} {lead:.0f}s before Promote finished"
    if observed["applied_at"] is None:
        return WAIT, f"Flux fetched {short(seen)} but not every Kustomization applied it in time"
    via = "" if seen == sha else f" via later main commit {short(seen)}"
    return PASS, (f"{short(sha)} reached the cluster{via} {-lead:.0f}s after Promote finished; "
                  f"all Kustomizations applied it by {stamp(observed['applied_at'])}")


# ------------------------------------------------------------------- reading


def fetch():
    output(["git", "fetch", "--quiet", "origin", "main", "deploy"])


def ref_sha(ref):
    result = run(["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"])
    return result.stdout.strip() or None


def is_ancestor(older, newer):
    return run(["git", "merge-base", "--is-ancestor", older, newer]).returncode == 0


def contains(newer, older):
    """True when commit `newer` is `older` or descends from it, fetching once if unknown."""
    if newer == older:
        return True
    if run(["git", "cat-file", "-e", f"{newer}^{{commit}}"]).returncode != 0:
        fetch()
    return is_ancestor(older, newer)


def kube(*args):
    raw = output(["kubectl", "--request-timeout=15s", *args, "-o", "json"])
    return json.loads(raw)


def ready(obj):
    for condition in obj.get("status", {}).get("conditions", []):
        if condition["type"] == "Ready":
            return condition["status"], condition.get("reason", "")
    return "Unknown", "NoReadyCondition"


def read_cluster():
    repo = kube("-n", "flux-system", "get", "gitrepository", "flux-system")
    instance = kube("-n", "flux-system", "get", "fluxinstance", "flux")
    items = kube("get", "kustomizations.kustomize.toolkit.fluxcd.io", "-A")["items"]
    return {
        "source": {"ref": repo["spec"].get("ref"),
                   "revision": repo.get("status", {}).get("artifact", {}).get("revision", ""),
                   "ready": ready(repo)[0] == "True"},
        "instance": {"ref": instance["spec"].get("sync", {}).get("ref"), "ready": ready(instance)[0] == "True"},
        "kustomizations": [
            {"name": f"{k['metadata']['namespace']}/{k['metadata']['name']}",
             "source": k["spec"].get("sourceRef", {}).get("name"),
             "applied": k.get("status", {}).get("lastAppliedRevision"),
             "ready": ready(k)[0], "reason": ready(k)[1]}
            for k in items
        ],
    }


def gate_runs():
    raw = output(["gh", "run", "list", "--workflow", WORKFLOW, "--branch", "main", "--event", "push",
                  "--limit", "20", "--json", "databaseId,headSha,status,conclusion,url,createdAt"])
    return json.loads(raw or "[]")


def run_for(sha, runs):
    matching = [r for r in runs if r["headSha"] == sha]
    return matching[0] if matching else None


def run_jobs(run_id):
    raw = output(["gh", "run", "view", str(run_id), "--json", "jobs"])
    return [{"name": j["name"], "conclusion": j.get("conclusion"), "startedAt": j.get("startedAt"),
             "completedAt": j.get("completedAt")} for j in json.loads(raw)["jobs"]]


def committed_sync_ref():
    text = output(["git", "show", f"refs/remotes/origin/main:{HELMRELEASE}"])
    result = subprocess.run(["yq", "-o=json", ".spec.values.instance.sync.ref", "-"], input=text,
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def gather_steady():
    # Read the gate run before fetching: a run that completed earlier must
    # already show in the refs fetched afterwards.
    runs = gate_runs()
    fetch()
    main, deploy = ref_sha("refs/remotes/origin/main"), ref_sha("refs/remotes/origin/deploy")
    on_main = bool(deploy) and is_ancestor(deploy, main)
    behind = int(output(["git", "rev-list", "--count", f"{deploy}..{main}"])) if on_main else None
    return {"main": main, "deploy": deploy, "deploy_on_main": on_main, "behind": behind,
            "intent": committed_sync_ref(), "run": run_for(main, runs) or (runs[0] if runs else None),
            **read_cluster()}


def kube_context():
    result = run(["kubectl", "config", "current-context"])
    return result.stdout.strip().split(".")[0] or "unknown"


# ------------------------------------------------------------------ journeys


def steady(_args):
    state = gather_steady()
    checks = evaluate_steady(state)
    for check in checks:
        print(f"{check['status'].upper():4}  {check['check']:9}  {check['detail']}")
    verdict = overall(c["status"] for c in checks)
    return verdict, {"state": state, "checks": checks}


def follow(args):
    fetch()
    sha = ref_sha(args.sha)
    if not sha or not is_ancestor(sha, "refs/remotes/origin/main"):
        return FAIL, {"detail": f"{args.sha} is not on origin/main; push it to main first"}
    started = now()
    observed = {"reads": None, "seen_sha": None, "seen_at": None, "applied_at": None}
    deadline = time.monotonic() + args.timeout
    print(f"following {short(sha)}; the cluster is polled every {args.interval}s for up to {args.timeout:.0f}s",
          flush=True)
    while time.monotonic() < deadline:
        try:
            cluster = read_cluster()
        except (RuntimeError, json.JSONDecodeError) as error:
            print(f"cluster read failed, retrying: {error}", flush=True)
            time.sleep(args.interval)
            continue
        observed["reads"] = source_ref(cluster["source"]["ref"])
        if observed["reads"] != DEPLOY_REF:
            break
        revision = cluster["source"]["revision"]
        current = revision.rsplit(":", 1)[-1]
        if observed["seen_at"] is None and revision.startswith(DEPLOY_REF) and contains(current, sha):
            observed.update(seen_sha=current, seen_at=now())
            print(f"{stamp(observed['seen_at'])}  Flux fetched {revision}", flush=True)
        if observed["seen_at"] is not None:
            root = [k for k in cluster["kustomizations"] if k["source"] == "flux-system"]
            if all(k["ready"] == "True" and k["applied"] == revision for k in root):
                observed["applied_at"] = now()
                print(f"{stamp(observed['applied_at'])}  all {len(root)} Kustomizations on flux-system applied it",
                      flush=True)
                break
        time.sleep(args.interval)
    target = observed["seen_sha"] or sha
    run_ = run_for(target, gate_runs())
    jobs = run_jobs(run_["databaseId"]) if run_ else []
    verdict, detail = evaluate_follow(sha, observed, run_, jobs)
    print(f"{verdict.upper():4}  follow     {detail}")
    return verdict, {"sha": sha, "started_at": stamp(started), "detail": detail, "run": run_, "jobs": jobs,
                     "observed": {**observed, "seen_at": stamp(observed["seen_at"]),
                                  "applied_at": stamp(observed["applied_at"])}}


def push(clone, refspec, break_glass=False):
    """Push to the throwaway remote; return the exit code and the lines that explain it."""
    env = {k: v for k, v in os.environ.items() if k != "ANTON_BREAK_GLASS"}
    if break_glass:
        env["ANTON_BREAK_GLASS"] = "1"
    result = run(["git", "push", "verify", refspec], cwd=clone, env=env, timeout=900)
    lines = ANSI.sub("", result.stdout + result.stderr).strip().splitlines()
    reasons = [line for line in lines if Path(PROBE).name in line]
    return result.returncode, reasons + lines[-6:]


def remote_ref(remote, branch):
    result = run(["git", "--git-dir", remote, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"])
    return result.stdout.strip() or None


def hook(args):
    scratch = Path(tempfile.mkdtemp(prefix="anton-verify-hook-"))
    clone, remote = scratch / "clone", scratch / "remote.git"
    cases = []

    def case(name, expect_ok, pushed, ref, want):
        code, tail = pushed
        ok = (code == 0) == expect_ok and ref == want
        cases.append({"case": name, "status": PASS if ok else FAIL, "push_exit": code,
                      "remote_ref": ref, "expected_ref": want, "output_tail": tail})
        print(f"{(PASS if ok else FAIL).upper():4}  hook       {name}: push exit {code}, remote ref {short(ref) or 'absent'}",
              flush=True)

    head = None
    try:
        output(["git", "clone", "--quiet", REPO, clone], cwd=scratch)
        output(["git", "remote", "remove", "origin"], cwd=clone)  # nothing can reach GitHub or this checkout
        output(["git", "init", "--quiet", "--bare", remote], cwd=scratch)
        output(["git", "remote", "add", "verify", remote], cwd=clone)
        # A global core.hooksPath would otherwise send the shim to a shared hooks directory.
        output(["git", "config", "core.hooksPath", clone / ".git" / "hooks"], cwd=clone)
        output(["bash", "scripts/install-git-hooks.sh"], cwd=clone)
        head = output(["git", "rev-parse", "HEAD"], cwd=clone)
        print(f"throwaway clone at {short(head)}; each push runs contracts:fast, which takes a while", flush=True)

        case("a passing commit reaches main", True, push(clone, f"{head}:refs/heads/main"),
             remote_ref(remote, "main"), head)

        (clone / PROBE).write_text("This page sits outside the documentation sections on purpose.\n")
        output(["git", "add", PROBE], cwd=clone)
        output(["git", "-c", "user.name=verify-deploy-gate", "-c", "user.email=verify@localhost",
                "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "probe: fails contracts:fast"], cwd=clone)
        bad = output(["git", "rev-parse", "HEAD"], cwd=clone)
        case("a commit failing contracts:fast is refused", False, push(clone, f"{bad}:refs/heads/main"),
             remote_ref(remote, "main"), head)

        case("deploy without break-glass is refused", False, push(clone, f"{head}:refs/heads/deploy"),
             remote_ref(remote, "deploy"), None)

        case("break-glass deploy of a main commit is accepted", True,
             push(clone, f"{head}:refs/heads/deploy", break_glass=True), remote_ref(remote, "deploy"), head)
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        cases.append({"case": "setup", "status": FAIL, "error": str(error)})
        print(f"FAIL  hook       setup: {error}", flush=True)
    finally:
        if args.keep:
            print(f"kept {scratch}")
        else:
            shutil.rmtree(scratch, ignore_errors=True)
    verdict = overall(c["status"] for c in cases) if len(cases) == 4 else FAIL
    return verdict, {"clone_head": head, "cases": cases, "kept": str(scratch) if args.keep else None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="journey", required=True)
    sub.add_parser("steady", help="check that the gate, deploy and Flux agree right now")
    follow_parser = sub.add_parser("follow", help="prove a main commit reached the cluster only after Promote")
    follow_parser.add_argument("sha")
    follow_parser.add_argument("--timeout", type=float, default=900)
    follow_parser.add_argument("--interval", type=float, default=5)
    hook_parser = sub.add_parser("hook", help="exercise the pre-push hook against a local bare remote")
    hook_parser.add_argument("--keep", action="store_true", help="keep the throwaway clone for debugging")
    for journey in sub.choices.values():
        journey.add_argument("--evidence", type=Path, help="write a JSON record of the run here")
    args = parser.parse_args(argv)

    started = now()
    try:
        verdict, record = {"steady": steady, "follow": follow, "hook": hook}[args.journey](args)
    except (RuntimeError, subprocess.SubprocessError, OSError, json.JSONDecodeError) as error:
        verdict, record = FAIL, {"error": str(error)}
        print(f"FAIL  {args.journey}: {error}")
    print(f"verdict: {verdict}")
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps({
            "journey": args.journey, "verdict": verdict, "started_at": stamp(started), "finished_at": stamp(now()),
            "checkout": output(["git", "rev-parse", "HEAD"]), "kube_context": kube_context(), **record,
        }, indent=2, default=str) + "\n")
        print(f"evidence: {args.evidence}")
    return EXIT[verdict]


if __name__ == "__main__":
    sys.exit(main())
