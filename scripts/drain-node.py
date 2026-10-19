#!/usr/bin/env python3
"""Move the in-cluster API proxy off a cordoned node before draining it."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any


NAMESPACE = "tailscale"
DEPLOYMENT = "operator"
POLL_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 5.0


class DrainError(RuntimeError):
    pass


class IdentityMismatch(DrainError):
    pass


class RetryableObservation(DrainError):
    pass


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class Kubectl:
    def __init__(self, context: str, deadline: float):
        self.context = context
        self.deadline = deadline

    def run(
        self,
        args: list[str],
        *,
        stdin: str | None = None,
        pin_context: bool = True,
    ) -> CommandResult:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise DrainError("overall drain timeout expired")
        request_timeout = min(REQUEST_TIMEOUT_SECONDS, remaining)
        command = ["kubectl"]
        if pin_context:
            command.extend(["--context", self.context])
        command.extend([f"--request-timeout={request_timeout:.1f}s", *args])
        try:
            result = subprocess.run(
                command,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=remaining,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise DrainError("kubectl command exceeded the remaining overall timeout") from exc
        except OSError as exc:
            raise DrainError(f"could not run kubectl: {exc}") from exc
        return CommandResult(result.returncode, result.stdout, result.stderr)

    def json(self, args: list[str]) -> dict[str, Any]:
        result = self.run([*args, "-o", "json"])
        if result.returncode != 0:
            if is_ambiguous_transport_failure(result):
                raise RetryableObservation(command_error(result))
            raise DrainError(command_error(result))
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RetryableObservation(
                f"kubectl returned incomplete or invalid JSON for {' '.join(args)}"
            ) from exc
        if not isinstance(value, dict):
            raise DrainError(f"kubectl returned an unexpected object for {' '.join(args)}")
        return value


def sanitize_output(message: str) -> str:
    return re.sub(
        r"(?<![A-Za-z0-9.-])(?:[A-Za-z0-9-]+\.)+ts\.net\b",
        "tailscale-operator.<tailnet-name>.ts.net",
        message,
        flags=re.IGNORECASE,
    )


def command_error(result: CommandResult) -> str:
    message = result.stderr.strip() or result.stdout.strip() or "unknown kubectl error"
    message = sanitize_output(message)
    return f"kubectl failed (exit {result.returncode}): {message}"


def ensure_identity(value: Any, expected: str, label: str) -> None:
    actual = value.get("metadata", {}).get("uid") if isinstance(value, dict) else None
    if actual != expected:
        raise IdentityMismatch(f"{label} UID changed or did not match the expected value")


def ready(pod: dict[str, Any]) -> bool:
    return not pod.get("metadata", {}).get("deletionTimestamp") and any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in pod.get("status", {}).get("conditions", [])
    )


def controller_owner(resource: dict[str, Any], kind: str) -> dict[str, Any]:
    owners = [
        owner
        for owner in resource.get("metadata", {}).get("ownerReferences", [])
        if owner.get("controller") is True
    ]
    if len(owners) != 1 or owners[0].get("kind") != kind:
        raise IdentityMismatch(f"resource does not have exactly one controller owner of kind {kind}")
    return owners[0]


def matches_selector(labels: dict[str, Any], selector: dict[str, Any]) -> bool:
    return bool(selector) and all(labels.get(key) == value for key, value in selector.items())


def require_in_process_proxy(deployment: dict[str, Any]) -> None:
    containers = deployment.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    values = [
        env.get("value")
        for container in containers
        for env in container.get("env", [])
        if env.get("name") == "APISERVER_PROXY"
    ]
    if values != ["true"]:
        raise DrainError("Tailscale operator must have APISERVER_PROXY=true on exactly one container")


def deployment_state(
    kubectl: Kubectl,
    expected_uid: str,
    *,
    absent_pod_uid: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    deployment = kubectl.json(["get", "deployment", DEPLOYMENT, "-n", NAMESPACE])
    ensure_identity(deployment, expected_uid, "Tailscale operator Deployment")
    require_in_process_proxy(deployment)
    spec = deployment.get("spec", {})
    status = deployment.get("status", {})
    selector = spec.get("selector", {}).get("matchLabels", {})
    if spec.get("replicas", 1) != 1 or not selector:
        raise DrainError("Tailscale operator must be a singleton Deployment with a label selector")
    if status.get("observedGeneration", 0) < deployment.get("metadata", {}).get("generation", 0):
        raise RetryableObservation("Tailscale operator Deployment has not observed its current generation")
    if status.get("readyReplicas", 0) != 1:
        raise RetryableObservation("Tailscale operator Deployment is not Ready at 1/1")
    pods = kubectl.json(["get", "pods", "-n", NAMESPACE])
    if absent_pod_uid and any(
        pod.get("metadata", {}).get("uid") == absent_pod_uid
        for pod in pods.get("items", [])
    ):
        raise RetryableObservation("old Tailscale operator pod is still present")
    matching = [
        pod
        for pod in pods.get("items", [])
        if matches_selector(pod.get("metadata", {}).get("labels", {}), selector)
    ]
    if len(matching) != 1:
        raise RetryableObservation("expected exactly one Tailscale operator pod")
    pod = matching[0]
    if not ready(pod):
        raise RetryableObservation("Tailscale operator pod is not Ready or is terminating")
    resolve_deployment_owner(kubectl, pod, expected_uid)
    return deployment, pod


def resolve_deployment_owner(
    kubectl: Kubectl, pod: dict[str, Any], expected_deployment_uid: str
) -> None:
    replica_set_ref = controller_owner(pod, "ReplicaSet")
    replica_set = kubectl.json(
        ["get", "replicaset", replica_set_ref["name"], "-n", NAMESPACE]
    )
    ensure_identity(replica_set, replica_set_ref.get("uid", ""), "operator ReplicaSet")
    deployment_ref = controller_owner(replica_set, "Deployment")
    if deployment_ref.get("name") != DEPLOYMENT or deployment_ref.get("uid") != expected_deployment_uid:
        raise IdentityMismatch("Tailscale operator pod owner chain does not match the expected Deployment")


def validate_target_node(
    kubectl: Kubectl, *, node: str, expected_node_uid: str
) -> dict[str, Any]:
    target = kubectl.json(["get", "node", node])
    ensure_identity(target, expected_node_uid, f"node {node}")
    if target.get("spec", {}).get("unschedulable") is not True:
        raise DrainError(f"node {node} must remain cordoned")
    if not any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in target.get("status", {}).get("conditions", [])
    ):
        raise DrainError(f"node {node} is not Ready")
    return target


def preflight(
    kubectl: Kubectl,
    *,
    node: str,
    expected_cluster_uid: str,
    expected_node_uid: str,
    expected_operator_uid: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    namespace = kubectl.json(["get", "namespace", "kube-system"])
    ensure_identity(namespace, expected_cluster_uid, "kube-system namespace")
    target = validate_target_node(kubectl, node=node, expected_node_uid=expected_node_uid)
    deployment, pod = deployment_state(kubectl, expected_operator_uid)
    return target, pod


def eviction_body(pod: dict[str, Any]) -> str:
    metadata = pod.get("metadata", {})
    return json.dumps(
        {
            "apiVersion": "policy/v1",
            "kind": "Eviction",
            "metadata": {"name": metadata["name"], "namespace": NAMESPACE},
            "deleteOptions": {"preconditions": {"uid": metadata["uid"]}},
        }
    )


def is_pdb_refusal(result: CommandResult) -> bool:
    detail = f"{result.stderr}\n{result.stdout}".lower()
    return any(
        marker in detail
        for marker in ("429", "toomanyrequests", "disruption budget", "cannot evict pod")
    )


def is_ambiguous_transport_failure(result: CommandResult) -> bool:
    detail = f"{result.stderr}\n{result.stdout}".lower()
    return any(
        marker in detail
        for marker in (
            "connection reset",
            "connection refused",
            "unable to connect",
            "request canceled",
            "client.timeout exceeded",
            "unexpected eof",
            "unexpected end of json input",
            "eof",
            "i/o timeout",
            "context deadline exceeded",
            "tls handshake timeout",
            "no such host",
            "502 bad gateway",
            "503 service unavailable",
            "504 gateway timeout",
            "the server was unable to return a response",
        )
    )


def observe_replacement(
    kubectl: Kubectl,
    *,
    old_pod_uid: str,
    target_node: str,
    expected_operator_uid: str,
) -> dict[str, Any]:
    _, pod = deployment_state(
        kubectl,
        expected_operator_uid,
        absent_pod_uid=old_pod_uid,
    )
    if pod.get("spec", {}).get("nodeName") == target_node:
        raise IdentityMismatch("replacement Tailscale operator pod is still on the target node")
    return pod


def wait_for_replacement(
    kubectl: Kubectl,
    *,
    old_pod_uid: str,
    target_node: str,
    expected_operator_uid: str,
) -> dict[str, Any]:
    last_error = "operator replacement is not Ready off the target node"
    while time.monotonic() < kubectl.deadline:
        try:
            return observe_replacement(
                kubectl,
                old_pod_uid=old_pod_uid,
                target_node=target_node,
                expected_operator_uid=expected_operator_uid,
            )
        except RetryableObservation as exc:
            last_error = str(exc)
            if time.monotonic() >= kubectl.deadline:
                break
            time.sleep(min(POLL_SECONDS, max(0, kubectl.deadline - time.monotonic())))
    raise DrainError(f"timed out waiting for recovered API proxy: {last_error}")


def context_is_proxy(context: str) -> bool:
    return bool(re.fullmatch(r"tailscale-operator\..+\.ts\.net", context))


def active_context(kubectl: Kubectl, expected_context: str) -> None:
    result = kubectl.run(["config", "current-context"], pin_context=False)
    actual = result.stdout.strip() if result.returncode == 0 else ""
    if actual != expected_context or not context_is_proxy(actual):
        raise DrainError("active context must exactly match the expected Tailscale operator proxy context")


def run(args: argparse.Namespace) -> int:
    deadline = time.monotonic() + args.timeout
    kubectl = Kubectl(args.expected_context, deadline)
    active_context(kubectl, args.expected_context)
    _, proxy_pod = preflight(
        kubectl,
        node=args.node,
        expected_cluster_uid=args.expected_cluster_uid,
        expected_node_uid=args.expected_node_uid,
        expected_operator_uid=args.expected_operator_uid,
    )

    proxy_node = proxy_pod.get("spec", {}).get("nodeName")
    if proxy_node == args.node:
        old_uid = proxy_pod.get("metadata", {}).get("uid")
        if not old_uid:
            raise DrainError("Tailscale operator pod has no UID")
        print(
            "Phase 1/2: evicting the API proxy pod once through the PDB-aware Eviction API",
            flush=True,
        )
        body = eviction_body(proxy_pod)
        result = kubectl.run(
            [
                "create",
                "--raw",
                f"/api/v1/namespaces/{NAMESPACE}/pods/{proxy_pod['metadata']['name']}/eviction",
                "-f",
                "-",
            ],
            stdin=body,
        )
        if result.returncode != 0 and is_pdb_refusal(result):
            raise DrainError("operator pod eviction was refused by a PodDisruptionBudget; stopping")
        if result.returncode != 0 and not is_ambiguous_transport_failure(result):
            raise DrainError(command_error(result))
        if result.returncode != 0:
            print(
                "eviction response was ambiguous; observing state without retry",
                file=sys.stderr,
                flush=True,
            )
        print(
            "Waiting for the old pod UID to disappear and a Ready replacement off the target",
            flush=True,
        )
        wait_for_replacement(
            kubectl,
            old_pod_uid=old_uid,
            target_node=args.node,
            expected_operator_uid=args.expected_operator_uid,
        )
        print("API proxy replacement is Ready off the target", flush=True)
    else:
        print("API proxy is already Ready off the target; skipping proxy eviction", flush=True)

    active_context(kubectl, args.expected_context)
    _, final_proxy_pod = preflight(
        kubectl,
        node=args.node,
        expected_cluster_uid=args.expected_cluster_uid,
        expected_node_uid=args.expected_node_uid,
        expected_operator_uid=args.expected_operator_uid,
    )
    if final_proxy_pod.get("spec", {}).get("nodeName") == args.node:
        raise DrainError("Tailscale API proxy is still on the target node before bulk drain")
    print("Fresh active-context, cluster, node, Deployment, and owner checks passed", flush=True)

    # Keep the target identity and cordon check adjacent to the mutating drain
    # request; an operator may have changed node state during proxy recovery.
    validate_target_node(kubectl, node=args.node, expected_node_uid=args.expected_node_uid)

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise DrainError("overall drain timeout expired before bulk drain")
    drain_args = [
        "drain",
        args.node,
        "--ignore-daemonsets",
        f"--timeout={remaining:.1f}s",
    ]
    if args.delete_emptydir_data:
        drain_args.append("--delete-emptydir-data")
    print("Phase 2/2: running one standard node drain", flush=True)
    result = kubectl.run(drain_args)
    if result.returncode != 0:
        raise DrainError(command_error(result))
    if result.stdout:
        output = sanitize_output(result.stdout)
        print(output, end="" if output.endswith("\n") else "\n")
    if result.stderr:
        output = sanitize_output(result.stderr)
        print(output, end="" if output.endswith("\n") else "\n", file=sys.stderr)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", required=True, help="already-cordoned node to drain")
    parser.add_argument("--expected-context", required=True)
    parser.add_argument("--expected-cluster-uid", required=True)
    parser.add_argument("--expected-node-uid", required=True)
    parser.add_argument("--expected-operator-uid", required=True)
    parser.add_argument("--timeout", type=float, required=True, help="overall timeout in seconds")
    parser.add_argument(
        "--delete-emptydir-data",
        action="store_true",
        help="allow deletion of local emptyDir contents during the final drain",
    )
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0 or args.timeout > 3600:
        parser.error("--timeout must be greater than zero and at most 3600 seconds")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except DrainError as exc:
        print(f"drain stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
