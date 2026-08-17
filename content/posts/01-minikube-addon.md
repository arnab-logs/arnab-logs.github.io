---
title: "Adding a Minikube Addon from Scratch"
date: 2026-05-06T14:54:17+05:30
draft: false
tags: ["Opensource-learnings","Minikube","Kubernetes"]
description: "I walk through how I opened a PR for adding a minikube addon"
---

## Introduction: Why I'm Writing This

Hi! This is where I write about the lessons that I learn from open source contributions! This is not a polished "here's how to contribute to open source" tutorial written by someone who has done it a hundred times.

The project is **Minikube,** the tool that lets you run a Kubernetes cluster on your local machine for development and testing. The contribution I worked on was adding **Node Readiness Controller (NRC)** as a Minikube addon, so that anyone in the world can type `minikube start --addons=nrc` and have it just work.

If you are new to open source, new to Kubernetes, or new to Go, I'll try to explain every concept as I go. Nothing will be assumed. And I'll be completely honest about where I got stuck because I think that's the most useful thing I can share.

## What Is Minikube? And What Is an Addon?

To be honest, I had previously worked with minikube and had basic knowledge about what it was. I’ll take a moment and introduce it, in case you are new to this.

**Minikube** is a tool that runs a full Kubernetes cluster on your laptop, inside a Docker container or a virtual machine. Real Kubernetes clusters run on multiple physical servers in data centers. Minikube simulates all of that on a single machine so developers can test their applications locally without needing cloud infrastructure.

**Addons** are optional features you can switch on or off inside your Minikube cluster. Examples include a web dashboard for your cluster, an ingress controller for routing traffic or a metrics server for monitoring. You enable them with a single command like `minikube addons enable dashboard`.

When you enable an addon, Minikube reads a set of Kubernetes YAML files it has stored internally, applies them to the cluster, and the feature starts running. The list of known addons, and the YAML instructions for each one all live inside the Minikube source code itself.

My job was to add [Node Readiness Controller](github.com/kubernetes-sigs/node-readiness-controller) to that list.

## What Is the Node Readiness Controller (NRC)?

NRC is a Kubernetes controller built by the Kubernetes SIGs (Special Interest Groups) community. Its job is to make sure that nodes i.e. the machines in your cluster, are truly ready before any workloads land on them.

Here's the problem it solves: when a node joins a Kubernetes cluster, Kubernetes marks it as "Ready" fairly quickly. But "Ready" from Kubernetes perspective just means the node's basic processes are running. It doesn't mean the GPU driver is loaded, or the network agent has finished initializing, or whatever custom infrastructure dependency your workload needs.

NRC fills that gap. It lets you define custom readiness rules i.e. "this node is only ready when condition X is true" and it automatically applies taints (essentially a "DO NOT SCHEDULE HERE" sticky note) to nodes that don't yet meet those conditions. When the conditions are met, it removes the taint, and workloads can flow in.

For the Minikube addon specifically, the goal was to run NRC in a **control-plane co-located** model. This means NRC runs on the same node as Kubernetes own system components, and starts up *before* any user workloads. This makes it useful for testing device-driver readiness scenarios, GPU/TPU simulation, and other infrastructure-level readiness checks i.e. all things that Minikube is increasingly being used for.

## The First Confusion: Which Repository Does This Go Into?

This was genuinely the first thing I got confused about and I think it trips up a lot of beginners.

NRC has its own GitHub repository at `github.com/kubernetes-sigs/node-readiness-controller`. It has its own source code, its own container image published to `registry.k8s.io`, and its own documentation. So my initial instinct was: "I should open a PR in the NRC repo."

It did not take much time to figure out that it was a wrong idea.

The PR goes into **Minikube's repository** (`github.com/kubernetes/minikube`). Here’s how I looked at it:

NRC's team has already done their work. They built the controller, compiled it into a container image, and published it to a public registry. That image is sitting on the internet right now, ready to be pulled.

What doesn't exist yet is Minikube knowing about NRC. Minikube has never heard of NRC. If you typed `minikube start --addons=nrc` today, it would fail immediately saying the addon doesn't exist.

My [PR](https://github.com/kubernetes/minikube/pull/22924) is teaching Minikube about NRC. I'm not changing NRC at all. I'm adding Minikube's instructions for *how to deploy* NRC when someone asks for it. Those instructions live in the Minikube repo.

Once this PR merges (🤞), whenever someone enables the NRC addon, Minikube reads the instructions I added, creates some Kubernetes objects in the cluster, and pulls NRC's container image from `registry.k8s.io`. NRC's own codebase is never touched.

## Understanding Minikube's Addon Architecture

Before writing a single line, I spent time reading how existing addons were structured. I figured this was a non-negotiable as you cannot write an addon without understanding the pattern.

Here's what I found. The Minikube codebase has a very specific two-layer system:

**Layer 1: The YAML files:** Inside `deploy/addons/`, there is one folder per addon. Each folder contains Kubernetes manifest files i.e. YAML files describing what to create in the cluster. But these aren't plain YAML. They use Go template syntax, with placeholders like `{{.Images.SomeName}}` that get filled in at runtime.

**Layer 2: The Go registration:** In `pkg/minikube/assets/addons.go`, there is a large Go map where every addon is registered. Each entry points to the YAML files and provides metadata like the addon name, the container image to use, the registry it comes from, and documentation links.

There's also a third piece: `deploy/addons/assets.go` which uses Go's `embed` package to bake all the YAML files directly into the compiled Minikube binary. This is why you can install Minikube as a single binary and it works everywhere without needing external files, all the addon YAML is inside the binary itself.

Every addon is the product of all three pieces working together. If any one of them is wrong or inconsistent, the addon fails.

## Writing the Actual Files

### Step 1: Reading NRC's Real Manifests First

The most important thing I did before writing anything was go read NRC's own source repository. Specifically, I looked at how NRC deploys itself, what Kubernetes objects it needs, what permissions it requires, what container image it uses, and what configuration flags it accepts.

This is not optional. You cannot write correct addon files for a project you haven't read. Everything you write in Minikube is derived from what the project itself specifies. You're not inventing how NRC works, you're translating its existing deployment into Minikube's format.

NRC deploys with two sets of files:

- A **CRD (Custom Resource Definition)**: this teaches Kubernetes about a new type of object called `NodeReadinessRule`
- A **deployment manifest:** this runs the actual NRC controller, along with its RBAC (permissions) setup

I used these as my source of truth for the Minikube addon files.

### Step 2: Creating the Addon Directory

```bash
mkdir deploy/addons/nrc
```

One command. But knowing *why* this directory exists, what goes in it, and how it connects to the rest of the system

### Step 3: Writing the YAML Template Files

I created two files:

- `deploy/addons/nrc/crds.yaml` the CRD definition, copied from NRC's release. No template syntax needed here because it has no container image reference.
- `deploy/addons/nrc/nrc.yaml.tmpl` the deployment, RBAC, and service account. This one uses template syntax for the image reference.

The `.tmpl` extension on the second file is what tells Minikube's build system "this file needs Go template rendering before it's applied to the cluster."

The critical line inside `nrc.yaml.tmpl` is the image reference:

```yaml
image: {{.CustomRegistries.NrcController | default .Registries.NrcController}}{{.Images.NrcController}}
```

This looks intimidating but it's actually straightforward once you decode it: (Note: this is the reason why CI checks failed for me when I pushed my PR initially)

- Try `.CustomRegistries.NrcController` first: if the user has specified a custom registry (useful for air-gapped environments or private registries), use that
- If not, fall back to `.Registries.NrcController` the default registry I registered in the Go code
- Append `.Images.NrcController` the full image path with tag and sha256 digest

The key name `NrcController` is just a string I chose, it must be identical in the template and in the Go registration maps.

### Step 4: The Go Registration

In `pkg/minikube/assets/addons.go`, I added:

```go
"nrc": NewAddon([]*BinAsset{
    MustBinAsset(addons.NrcAssets, "nrc/crds.yaml", vmpath.GuestAddonsDir, "crds.yaml", "0640"),
    MustBinAsset(addons.NrcAssets, "nrc/nrc.yaml.tmpl", vmpath.GuestAddonsDir, "nrc.yaml", "0640"),
}, false, "nrc", "node-readiness-controller (SIGs)", "", "https://node-readiness-controller.sigs.k8s.io/",
    map[string]string{
        "NrcController": "node-readiness-controller/node-readiness-controller:v0.3.0@sha256:5b3e69...",
    },
    map[string]string{
        "NrcController": "registry.k8s.io",
    }, nil),
```

And in `deploy/addons/assets.go`, I added the embed directive:

```go
// NrcAssets assets for nrc addon
//go:embed nrc/*
var NrcAssets embed.FS
```

And in `pkg/addons/config.go`, I added the config entry so the addon appears in `minikube addons list`:

```go
{
    name:      "nrc",
    set:       SetBool,
    callbacks: []setFn{EnableOrDisableAddon},
},
```

## The Pain Points

None of the above went smoothly the first time. Let’s walk through some of the failures.

### Failure 1:

The very first time I tried to run `./out/minikube addons list`, the binary failed immediately:

```
panic: Failed to define asset nrc/nrc.yaml.tmpl: open nrc/nrc.yaml.tmpl: file does not exist
```

I had renamed the file in my Go code to use the `.tmpl` extension, but the actual file on disk was still called `nrc.yaml`. The Go embed system was looking for `nrc.yaml.tmpl` inside the embedded filesystem and couldn't find it.

The fix was simply renaming the file on disk:

```bash
mv deploy/addons/nrc/nrc.yaml deploy/addons/nrc/nrc.yaml.tmpl
```

Simple fix, but it taught me that the filename in `MustBinAsset(...)`, the filename on disk, and the embed directive in `assets.go` are all a three-way contract. All three must say the exact same thing. If any one of them diverges, you get a panic.

### Failure 2: ImagePullBackOff

After getting past the panic, I enabled the addon and watched the pod go into `ImagePullBackOff`. I ran `kubectl describe pod` and saw this:

```
Pulling image "node-readiness-controller/node-readiness-controller:v0.3.0@sha256:..."
Failed to pull image "node-readiness-controller/...": pull access denied, repository does not exist
```

The image it was trying to pull had no registry prefix. Instead of `registry.k8s.io/node-readiness-controller/...`, it was just `node-readiness-controller/...`. Docker interpreted that as a Docker Hub image, which doesn't exist.

The root cause was in my template line. I had originally written:

```yaml
image: {{.CustomRegistries.NrcController | default .ImageRepository}}{{.Images.NrcController}}
```

The problem is `.ImageRepository` that's Minikube's *global* image repository override, not the default registry for this specific addon. In a normal `minikube start` without any flags, `.ImageRepository` is empty. So the registry prefix was resolving to an empty string, and the image path was being used alone.

The fix was to use `.Registries.NrcController` as the fallback instead, which is populated from the registries map I registered in Go:

```yaml
image: {{.CustomRegistries.NrcController | default .Registries.NrcController}}{{.Images.NrcController}}
```

### Failure 3: Missing the Version Tag in the Image String

This one was subtle. I had registered the image in `addons.go` as:

```go
"NrcController": "node-readiness-controller/node-readiness-controller@sha256:5b3e69...",
```

Notice there's no `:v0.3.0` tag, just the digest. This is technically a valid image reference format (digest-only), but containerd and CRI-O, the two runtimes the CI tests use, can be stricter about this than Docker is. Some configurations reject digest-only references.

Every other image in Minikube's `addons.go` follows the format `image-path:tag@sha256:digest`. The format exists for a reason that the tag makes the reference human-readable and widely compatible, while the digest ensures it's immutable and pinned.

The fix:

```go
"NrcController": "node-readiness-controller/node-readiness-controller:v0.3.0@sha256:5b3e69...",
```

## CI Failures: What They Were and What They Meant

Once I pushed my PR, three CI tests failed: (Note: In most Kubernetes repositories, CI isn’t triggered automatically for new contributors, you typically need a maintainer to comment `/ok-to-test`. However, as an org member, CI ran immediately on PR creation, which definitely speeds things up.)

```
pull-minikube-docker-containerd-linux-x86   Required: true
pull-minikube-kvm-docker-linux-x86          Required: true
pull-minikube-docker-crio-linux-x86         Required: false
```

These are end-to-end integration tests that actually start a real Minikube cluster in CI and run the addon through its full lifecycle. They run across different combinations of container runtimes (containerd, Docker, CRI-O) and drivers (Docker, KVM).

The two marked `Required: true` are merge blockers and the PR cannot be merged while they're red.

All three were failing because of the image reference issues described above (missing registry prefix, missing version tag). Once I fixed those locally, verified with `kubectl describe pod` that the pod was reaching `Running` state, and pushed the fixes, it retriggered the CI 

Minikube's CI system (Prow) picks it up and retriggers only the required failing tests.

## The Control-Plane Co-location Model

One part of the PR that I want to explain clearly because it's conceptually important: the way NRC is deployed on the control-plane node specifically.

In a Kubernetes cluster, there are two kinds of nodes. The **control-plane node** runs Kubernetes' own system components i.e. the API server, the scheduler, the controller manager. The **worker nodes** run user workloads. By default, Kubernetes prevents user workloads from landing on the control-plane node by applying a "taint" essentially a label that says "nothing should be scheduled here unless it explicitly tolerates this taint."

For NRC to run before any user workloads, it needs to be on the control-plane node. To achieve this, the deployment YAML needs two specific fields:

```yaml
tolerations:
  - key: node-role.kubernetes.io/control-plane
    operator: Exists
    effect: NoSchedule

nodeSelector:
  node-role.kubernetes.io/control-plane: ""
```

The `toleration` says "I accept the control-plane taint, so I'm allowed to run there." The `nodeSelector` says "I specifically require running on a control-plane node." Together they ensure NRC lands on the control-plane node and nowhere else.

Additionally, the `priorityClassName: system-cluster-critical` field gives NRC the same scheduling priority as core system components like CoreDNS. This ensures that even under resource pressure, NRC stays running and isn't evicted.

## The Minikube Addon Official Guide: And What It Doesn't Tell You

Minikube has an official guide for adding addons at `minikube.sigs.k8s.io/docs/contrib/addons/`. I read it carefully and it's genuinely useful, it tells you which files to touch and which commands to run.

But it assumes a lot of background knowledge. It says "add your manifest YAMLs" without explaining what format they need to be in, or what labels are required, or why. It mentions the `embed` directive without explaining what embedding even means. It says "run `make && make test`" without explaining what the output means or what to do if it fails.

The guide is correct. It's just dense. Everything it says is true and important. But for someone new to Go, new to Kubernetes, and new to open source codebases of this scale, the gap between reading the guide and knowing what to actually do is significant.

What helped me most was reading **real, working addons** in the codebase. I opened `deploy/addons/metrics-server/` and stared at it until I understood every line. I found the `metrics-server` entry in `addons.go` and decoded every argument to `NewAddon(...)`.

## Raising the PR

After all the local testing passed the pod was `Running`, the addon appeared in `minikube addons list`, the disable/enable cycle worked cleanly, I pushed the branch and opened the PR.

The PR description matters. Reviewers are busy people. A good description tells them what the PR does, why it exists, how you tested it, and what they should pay attention to. I included:

- What the addon does
- Why it belongs in Minikube
- The control-plane co-location detail and why it matters
- My testing steps and their results
- Links to the NRC project

## Closing Thoughts

I want to be honest about something: this contribution is not technically complex. It's a handful of YAML files, a few lines of Go to register them, and an embed directive. Experienced contributors could probably do this in a couple of hours.

For me it took much longer because I was learning while doing. I am not proficient in Go (Golang). I didn't know how Minikube's template rendering worked.

Every one of those things is now something I know. 

Open source projects like Kubernetes and Minikube can feel impossibly large and intimidating from the outside. The codebase is enormous. The concepts are deep. The community is full of people who have been doing this for years.

But every one of those people also had a first PR. Every one of them also got confused about something that now seems obvious to them. The project exists because people decided to start somewhere and figure it out as they went.

I am very much still figuring things out. But I have a PR open against a real project that real people use. And that is a start.

*If you are thinking about making your first open source contribution and you're not sure where to begin, find a project you use, find an issue labeled `good first issue`, read the existing code more than you read the documentation, and be patient with yourself when things break. They will break. That's where the learning is.*

*Thank you for reading.*