---
title: "Makefiles Finally Made Sense to Me"
date: 2026-08-26
description: "Let’s understand what happens inside a Makefile when we work with a real Kubernetes project."
tags: ["Kubernetes", "NodeReadinessController", "Opensource-learnings", "makefile"]
draft: false
source: notion
---

I've been studying the Node Readiness Controller codebase lately.

It's a Kubernetes project and like most Kubernetes projects, it has a Makefile. Makefiles are usually large files spanning over 300+ lines, so my immediate reaction to it was to close it and come back to it later.

This weekend, I did some research on what Makefiles are and why are they needed. Now, I do have a good idea on what they are, so I decided to document my understanding in case I need to come back to it later.

To actually run a project, build it, test it, we have to go through the Makefile. 

### What a Makefile Actually Is

In simple words, a Makefile is a file full of shortcuts and it does solve a big problem.

When we work on a project, we end up running the same long commands over and over. Let’s use an example to make things clear: Instead of typing `go run ./cmd/main.go` every single time or trying to remember which flags to pass to some tool which is new to us, we write those commands into a Makefile once. After that, `make run` is all we need.

### A Target in a Makefile

Every entry in a Makefile follows the same pattern:

```makefile
name: dependency1 dependency2
    command to run
```

Three things to note here:

1. A **name is** what we type after `make` Eg: `make run`

1. **Dependencies **are other tasks that must finish before this one starts

1. **Commands** are what actually runs

The dependencies run left to right, completely, before any command fires. Here's `make run` from the actual NRC Makefile:

```makefile
run: manifests generate fmt vet
    go run ./cmd/main.go
```

When we type `make run`, we are triggering a whole chain of commands. 

`manifests` runs, 

then `generate`, 

then `fmt`, 

then `vet`, 

and only then does `go run ./cmd/main.go` actually start the controller.

### Variables

The top of most Makefiles is almost entirely variables:

```makefile
CONTROLLER_GEN_VER := v0.19.0
CONTROLLER_GEN_BIN := controller-gen
TOOLS_BIN_DIR      := hack/tools/bin
```

We use them with `$(NAME)` and Make substitutes the actual value inline:

```makefile
CONTROLLER_GEN := $(TOOLS_BIN_DIR)/$(CONTROLLER_GEN_BIN)-$(CONTROLLER_GEN_VER)
# becomes: hack/tools/bin/controller-gen-v0.19.0
```

There are two kinds of assignment worth knowing:

- `:=` means "set the value now, always use this value"

- `?=` means "set this value only if nobody else set it first"

The `?=` ones are useful because we can override them from the command line, using:

```bash
make run IMG_TAG=v1.2.3
```

### .PHONY: Why we need it?

Make was originally designed to build files. If we tell it `make program`, it checks whether a file called `program` already exists. If it does, Make does nothing and it thinks the target is already built.

This becomes a problem for targets like `run` or `install`. If a file called `run` happened to sit in our project folder, `make run` would do absolutely nothing and would skip everything.

`.PHONY` is the fix for that:

```makefile
.PHONY: run
run: manifests generate fmt vet
    go run ./cmd/main.go
```

This tells Make that “run” is a task name and not the name of a “file”.

In the NRC Makefile, almost every named target is declared `.PHONY`. The only ones that aren't are the tool file paths like `$(CONTROLLER_GEN)` as those actually produce real files on disk, so the file-existence check is intentional here.

### controller-gen: a tool that writes YAML

The first time I saw `$(CONTROLLER_GEN)` used as a dependency, I had no idea what it was but I was curious to understand what role it played.

controller-gen is a code generation tool from the Kubernetes project which reads our Go struct definitions and the special comment markers sitting above them:

```go
// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
type NodeReadinessRule struct { ... }
```

From those, it generates two things:

1. **CRD YAML files** i.e. the schema Kubernetes needs to understand our custom resource

1. **DeepCopy Go code** i.e. the `zz_generated.deepcopy.go` file we are not supposed to edit manually

Without controller-gen, we would have to write hundreds of lines of YAML by hand and keep them perfectly in sync with our Go code every time anything changed. 

The NRC Makefile calls it twice, for different purposes:

```makefile
# make manifests: generates YAML files
controller-gen rbac:roleName=manager-role crd webhook paths="./..."

# make generate: generates Go code
controller-gen object:headerFile="..." paths="./..."
```

### How Tools Install Themselves

This was the part that surprised me most.

The NRC Makefile doesn't assume we have `kustomize` or `controller-gen` installed globally on our machine. It installs its own pinned versions into `hack/tools/bin/` inside the repo. The first time we run `make run` or `make install`, it downloads whatever it needs automatically.

The trick behind this is very simple. In Make, a dependency can be a file path. Make checks whether that file exists. If it doesn't, it runs the recipe that creates it. If it does, it skips it.

```makefile
$(KUSTOMIZE):
    CGO_ENABLED=0 GOBIN=$(TOOLS_BIN_DIR) $(GO_INSTALL) $(KUSTOMIZE_PKG) ...
```

`$(KUSTOMIZE)` expands to `hack/tools/bin/kustomize-v5.7.0`. If there is no file there, Make runs the install script. If file already there, it is skipped.

The first run is slow because everything downloads and every run after that is fast. We never touch your global tooling and the project stays fully self-contained.

### The Three Commands That Builds NRC locally

After all of that, here's what running NRC locally actually comes down to:

```bash
# 1. Create a kind cluster (once)
kind create cluster --name nrc-dev

# 2. Install the CRD into the cluster (once, or after changing the API types)
make install

# 3. Run the controller
make run
```

`make install` registers the `NodeReadinessRule` custom resource with Kubernetes. Without it the cluster simply doesn't know that resource type exists.

`make run` compiles and starts the controller. It connects to our kind cluster automatically because kind updates our `~/.kube/config` when we create it.

We can see logs appear in our terminal and the controller is running, watching for events.

### Conclusion

In simple sense, the Makefile is a recipe file, where someone writes down the commands so future contributors, including us, don't have to figure them out from scratch.

Once we understand the structure we can easily picture what runs before what. We know what a variable resolves to, including when a tool is being installed versus called.

That is a good feeling to have before we go any deeper into a codebase.
