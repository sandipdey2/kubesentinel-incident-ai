"""Build data/runbooks.csv from verbatim Kubernetes documentation excerpts.

    python scripts/build_runbooks.py      (after scripts/fetch_data.py)

Each runbook is 2-4 sentences copied verbatim from one kubernetes.io page
(CC BY 4.0, The Kubernetes Authors). The build fails if any sentence is not found
on its page. The `kubesentinel_policy` column is NOT from the documentation: it is
this project's own approval rule and is labelled as such everywhere it appears.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "data" / "raw" / "k8s_docs"

RUNBOOKS = [
 ("RB-01", "crashloopbackoff", "CrashLoopBackOff", "pod-lifecycle", [
  "CrashLoopBackOff state: This indicates that the backoff delay mechanism is currently in effect for a given container that is in a crash loop, failing and restarting repeatedly.",
  "The CrashLoopBackOff can be caused by issues like the following: Application errors that cause the container to exit.",
  "To investigate the root cause of a CrashLoopBackOff issue, a user can: Check logs: Use kubectl logs <name-of-pod> to check the logs of the container."],
  "Read-only investigation needs no approval."),
 ("RB-02", "crashloopbackoff", "Configuration consumed from ConfigMaps", "configmap", [
  "Pods can consume ConfigMaps as environment variables, command-line arguments, or as configuration files in a volume.",
  "ConfigMaps consumed as environment variables are not updated automatically and require a pod restart.",
  "The Pod and the ConfigMap must be in the same namespace."],
  "Editing a ConfigMap or restarting a Deployment is a WRITE action and needs human approval."),
 ("RB-03", "crashloopbackoff", "Rolling back a Deployment", "deployment", [
  "Rolling Back a Deployment Sometimes, you may want to rollback a Deployment; for example, when the Deployment is not stable, such as crash looping.",
  "By default, all of the Deployment's rollout history is kept in the system so that you can rollback anytime you want (you can change that by modifying revision history limit).",
  "This means that when you roll back to an earlier revision, only the Deployment's Pod template part is rolled back."],
  "kubectl rollout undo is a WRITE action and needs human approval."),
 ("RB-04", "oomkilled", "Memory limits and OOM kills", "resources", [
  "Containers may not use more CPU than is specified in their cpu limit. memory limits are enforced by the kernel with out of memory (OOM) kills.",
  "When a container uses more than its memory limit, the kernel may terminate it.",
  "A container may use more memory than its memory limit, but if it does, it may get killed."],
  "Changing resources.limits is a WRITE action and needs human approval."),
 ("RB-05", "oomkilled", "Exceeding a container memory limit", "assign-memory", [
  "But a Container is not allowed to use more than its memory limit.",
  "The Container could use all of the memory available on the Node where it is running which in turn could invoke the OOM Killer.",
  "Further, in case of an OOM Kill, a container with no resource limits will have a greater chance of being killed."],
  ""),
 ("RB-06", "imagepullbackoff", "ImagePullBackOff", "images", [
  "The status ImagePullBackOff means that a container could not start because Kubernetes could not pull a container image (for reasons such as invalid image name, or pulling from a private registry without imagePullSecret).",
  "The BackOff part indicates that Kubernetes will keep trying to pull the image, with an increasing back-off delay."],
  "Fixing the image reference is a WRITE action and needs human approval."),
 ("RB-07", "imagepullbackoff", "Pods stuck Waiting on image pulls", "debug-pods", [
  "My pod stays waiting If a Pod is stuck in the Waiting state, then it has been scheduled to a worker node, but it can't run on that machine.",
  "The most common cause of Waiting pods is a failure to pull the image."],
  ""),
 ("RB-08", "imagepullbackoff", "Private registry credentials", "private-reg", [
  "Create a Secret based on existing credentials A Kubernetes cluster uses the Secret of kubernetes.io/dockerconfigjson type to authenticate with a container registry to pull a private image.",
  "Note: Typing secrets on the command line may store them in your shell history unprotected, and those secrets might also be visible to other users on your PC during the time that kubectl is running."],
  "Creating Secrets is a WRITE action; KubeSentinel never handles registry passwords."),
 ("RB-09", "pending", "Pods stuck in Pending", "debug-pods", [
  "My pod stays pending If a Pod is stuck in Pending it means that it can not be scheduled onto a node.",
  "Look at the output of the kubectl describe ... command above."],
  ""),
 ("RB-10", "pending", "CPU requests and scheduling", "assign-cpu", [
  "A Pod is scheduled to run on a Node only if the Node has enough CPU resources available to satisfy the Pod CPU request.",
  "The CPU request for a Pod is the sum of the CPU requests for all the Containers in the Pod.",
  "Provided the system has CPU time free, a container is guaranteed to be allocated as much CPU as it requests."],
  "Lowering requests or adding nodes is a WRITE action and needs human approval."),
 ("RB-11", "pending", "Taints and tolerations", "taints", [
  "One or more taints are applied to a node; this marks that the node should not accept any pods that do not tolerate the taints.",
  "Tolerations allow scheduling but don't guarantee scheduling: the scheduler also evaluates other parameters as part of its function."],
  ""),
 ("RB-12", "node-notready", "Node NotReady", "debug-cluster", [
  "As with Pods, you can use kubectl describe node and kubectl get node -o yaml to retrieve detailed information about nodes.",
  "Notice the events that show the node is NotReady, and also notice that the pods are no longer running (they are evicted after five minutes of NotReady status)."],
  ""),
 ("RB-13", "node-notready", "Node heartbeats", "nodes", [
  "Node heartbeats Heartbeats, sent by Kubernetes nodes, help your cluster determine the availability of each node, and to take action when failures are detected.",
  "When running in a cloud environment and whenever a node is unhealthy, the node controller asks the cloud provider if the VM for that node is still available."],
  ""),
 ("RB-14", "node-notready", "Node-pressure eviction", "pressure", [
  "During a node-pressure eviction, the kubelet sets the phase for the selected pods to Failed, and terminates the Pod.",
  "If the pods are managed by a workload management object (such as StatefulSet or Deployment) that replaces failed pods, the control plane (kube-controller-manager) creates new pods in place of the evicted pods.",
  "The kubelet uses eviction signals to make eviction decisions by comparing the signals to eviction thresholds, which are the minimum amount of the resource that should be available on the node."],
  ""),
 ("RB-15", "node-notready", "Safely draining a node", "drain", [
  "Use kubectl drain to remove a node from service You can use kubectl drain to safely evict all of your pods from a node before you perform maintenance on the node (e.g. kernel upgrade, hardware maintenance, etc.).",
  "Safe evictions allow the pod's containers to gracefully terminate and will respect the PodDisruptionBudgets you have specified.",
  "If availability is important for any applications that run or could run on the node(s) that you are draining, configure a PodDisruptionBudgets first and then continue following this guide."],
  "KubeSentinel blocks kubectl drain unless it is a --dry-run; a real drain needs a human change review."),
 ("RB-16", "dns", "Debugging DNS resolution", "dns", [
  "If you see that no CoreDNS Pod is running or that the Pod has failed/completed, the DNS add-on may not be deployed by default in your current environment and you will have to deploy it manually.",
  "You can verify if queries are being received by CoreDNS by adding the log plugin to the CoreDNS configuration (aka Corefile).",
  "If CoreDNS pods are receiving the queries, you should see them in the logs."],
  ""),
 ("RB-17", "dns", "CoreDNS configuration", "dns", [
  "The CoreDNS Corefile is held in a ConfigMap named coredns.",
  "Note: The Service for CoreDNS is named kube-dns, for backward compatibility with the original kube-dns."],
  "Editing the coredns ConfigMap is a WRITE action with cluster-wide impact and needs human approval."),
 ("RB-18", "hpa", "HorizontalPodAutoscaler metrics", "hpa", [
  "The horizontal pod autoscaling controller, running within the Kubernetes control plane, periodically adjusts the desired scale of its target (for example, a Deployment) to match observed metrics such as average CPU utilization, average memory utilization, or any other custom metric you specify.",
  "For per-pod resource metrics (like CPU), the controller fetches the metrics from the resource metrics API for each Pod targeted by the HorizontalPodAutoscaler.",
  "The metrics.k8s.io API is usually provided by an add-on named Metrics Server, which needs to be launched separately."],
  ""),
 ("RB-19", "hpa", "Manual scaling and manifests", "deployment", [
  "Should you manually scale a Deployment, example via kubectl scale deployment deployment --replicas=X, and then you update that Deployment based on a manifest (for example: by running kubectl apply -f deployment.yaml), then applying that manifest overwrites the manual scaling that you previously did."],
  "kubectl scale is a WRITE action and needs human approval; scaling to zero is blocked."),
 ("RB-20", "pvc", "PersistentVolumeClaim binding", "pv", [
  "Dynamic When none of the static PVs the administrator created match a user's PersistentVolumeClaim, the cluster may try to dynamically provision a volume specially for the PVC.",
  "This provisioning is based on StorageClasses: the PVC must request a storage class and the administrator must have created and configured that class for dynamic provisioning to occur.",
  "Claims will remain unbound indefinitely if a matching volume does not exist."],
  "Deleting PVCs or PVs is blocked by KubeSentinel."),
 ("RB-21", "pvc", "Default StorageClass", "storage-classes", [
  "As an administrator, you can specify a default StorageClass that applies to any PVCs that don't request a specific class.",
  "When a PVC does not specify a storageClassName, the default StorageClass is used.",
  "Note: You should try to only have one StorageClass in your cluster that is marked as the default."],
  ""),
 ("RB-22", "probes", "Liveness probes", "probes", [
  "Many applications running for long periods of time eventually transition to broken states, and cannot recover except by being restarted.",
  "Kubernetes provides liveness probes to detect and remedy such situations.",
  "The solution is to set up a startup probe with the same command, HTTP or TCP check, with a failureThreshold * periodSeconds long enough to cover the worst case startup time."],
  "Changing probe settings is a WRITE action and needs human approval."),
 ("RB-23", "probes", "Readiness probes", "probes", [
  "If the readiness probe fails, the pod will be marked unready and will not receive traffic from any services.",
  "Readiness and liveness probes can be used in parallel for the same container.",
  "Once the startup probe has succeeded once, the liveness probe takes over to provide a fast response to container deadlocks."],
  ""),
 ("RB-24", "certificates", "TLS on Ingress", "ingress", [
  "The TLS secret must contain keys named tls.crt and tls.key that contain the certificate and private key to use for TLS.",
  "The Ingress resource only supports a single TLS port, 443, and assumes TLS termination at the ingress point (traffic to the Service and its Pods is in plaintext)."],
  "Rotating a TLS Secret is a WRITE action and needs human approval."),
 ("RB-25", "certificates", "kubeadm certificate renewal", "kubeadm-certs", [
  "Manual certificate renewal You can renew your certificates manually at any time with the kubeadm certs renew command, with the appropriate command line options."],
  "kubeadm certs renew is a WRITE action and needs human approval."),
 ("RB-26", "secrets", "Handling Secrets", "secret", [
  "Secrets are similar to ConfigMaps but are specifically intended to hold confidential data.",
  "Caution: Kubernetes Secrets are, by default, stored unencrypted in the API server's underlying data store (etcd).",
  "Enable or configure RBAC rules with least-privilege access to Secrets."],
  "KubeSentinel redacts secret-like values and IP addresses before any text reaches the LLM."),
 ("RB-27", "service", "Service with no endpoints", "debug-service", [
  "If the ENDPOINTS column is <none>, you should check that the spec.selector field of your Service actually selects for metadata.labels values on your Pods."],
  ""),
 ("RB-28", "safety", "Voluntary disruptions", "disruptions", [
  "Typical application owner actions include: deleting the deployment or other controller that manages the pod updating a deployment's pod template causing a restart directly deleting a pod (e.g. by accident) Cluster administrator actions include: Draining a node for repair or upgrade.",
  "Caution: Not all voluntary disruptions are constrained by Pod Disruption Budgets."],
  "KubeSentinel never proposes namespace deletion, bulk deletes, PV/PVC deletion or forced deletion; they are blocked."),
 ("RB-29", "general", "General pod debugging", "debug-pods", [
  "Check the current state of the Pod and recent events with the following command: kubectl describe pods ${POD_NAME} Look at the state of the containers in the pod.",
  "Continue debugging depending on the state of the pods."],
  "Read-only investigation needs no approval."),
]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def main():
    pages = {}
    for p in DOCS.glob("*.txt"):
        url, _, text = p.read_text(encoding="utf-8").partition("\n")
        pages[p.stem] = (url.strip(), norm(text))
    rows = []
    for rid, topic, title, key, sentences, policy in RUNBOOKS:
        url, text = pages[key]
        for s in sentences:
            if norm(s) not in text:
                raise ValueError(f"{rid}: sentence not found verbatim on {url}: {s[:80]}")
        rows.append({"id": rid, "topic": topic, "title": title, "content": " ".join(norm(s) for s in sentences),
                     "source": url, "license": "CC BY 4.0, The Kubernetes Authors (verbatim excerpt)",
                     "kubesentinel_policy": policy})
    with open(ROOT / "data" / "runbooks.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} runbooks, all {sum(len(r[4]) for r in RUNBOOKS)} sentences verified verbatim")


if __name__ == "__main__":
    main()
