---
title: "Understanding HEARTBEAT_PERIOD: Why a Reporter Sometimes Chooses Not to Write"
date: 2026-08-19
description: "
Why re-writing an unchanged Node status still costs etcd a full write and how a heartbeat timer fixes it.
"
tags: ["Kubernetes", "NodeReadinessController", "OpenSource", "etcd"]
draft: true
source: notion
---

A maintainer asked me to look at a merged PR in `node-readiness-controller` and figure out how to get it into NRC documentation. That was the whole assignment as it was given to me. 

I opened the PR [#263](https://github.com/kubernetes-sigs/node-readiness-controller/pull/263) and the first thing I saw was a variable called `HEARTBEAT_PERIOD`. I had no idea what it did neither did I knew what a "heartbeat" meant in this context. 

I want to write down what it actually took to go from that to actually document it and ultimately get it merged as part of the NRC documentation.

### Figuring things out

What helped more than the code was reading the PR discussion top to bottom in order.

The author's first instinct was that this fixes **API server flooding**. What it means in simple terms is that it fixed the problem of too many requests hitting the API server as the cluster scales (the project targets ~5,000 nodes). 

A reviewer tested that locally and found the request rate itself wasn't really a bottleneck as for a component that exists to periodically report node health, that's exactly/near to the number of requests what you would expect. 

The author pushed back with a bigger number i.e. in case the project targets a scale of 5,000 nodes, it would mean 500 requests a second and surely that's too much. 

The reviewer reframed the actual problem during review and this is the part that took me some time to understand i.e. **the actual cost isn't the number of requests, it's that Kubernetes stores the entire Node object in etcd, and every write, even a no-op write forces etcd to persist the whole thing again. **Reads were not the problem but writes were.

I didn't get this on the first pass. I got it on maybe the fourth after tracing through who said what to whom and in what order in the PR discussions. 

Let’s understand it from the scratch.

### What the reporter does

There is a small program in this project called the readiness-condition-reporter. It runs on a node, and its whole job is to check whether something on that node is healthy. It could be a CNI plugin, a security agent or whatever it is configured to watch and write that result onto the Node object as a condition. A condition is just a small structured entry: a type, a status of `True`/`False`/`Unknown`, a reason, a message, and a couple of timestamps.

When I read the above explanation (during the review process for this blog) it sounded a bit vague, so I will try to dissect it a bit more.

Let’s first see what a node actually looks like. In simple words, if we run something like `kubectl get node my-node -o yaml` we would see something like this:

```yaml
status:
  conditions:
    - type: Ready
      status: "True"
      reason: KubeletReady
      message: "kubelet is posting ready status"
      lastHeartbeatTime: "2026-08-20T10:15:00Z"
      lastTransitionTime: "2026-08-19T08:00:00Z"
    - type: MemoryPressure
      status: "False"
      reason: KubeletHasSufficientMemory
      message: "kubelet has sufficient memory available"
      lastHeartbeatTime: "2026-08-20T10:15:00Z"
      lastTransitionTime: "2026-08-19T08:00:00Z"
```

Here, we can see the `conditions:` entry sitting inside the node’s YAML. Kubernetes already ships a few of these conditions like `Ready`, `MemoryPressure`, `DiskPressure` by default and the `kubelet` (i.e. the agent running on every node) is the one that keeps them updated.

The readiness-condition-reporter is a separate small program that adds its *own* entry to the same YAML list, for something Kubernetes does not check natively, eg: "is the CNI plugin actually working on this node." Here’s what it might look like:

```yaml
    - type: projectcalico.org/CalicoReady
      status: "True"
      reason: EndpointOK
      message: "Calico health endpoint responded 200"
      lastHeartbeatTime: "2026-08-20T10:15:30Z"
      lastTransitionTime: "2026-08-19T09:02:00Z"
```

It is the same shape as the built-in ones. It just has a different `type` name and this reporter (readiness-condition-reporter) is the one deciding what goes in it, instead of the `kubelet`.

Before this PR, the reporter used to watch and write that result onto the Node object as a condition every `CHECK_INTERVAL`(i.e. 30 seconds by default), whether or not the result had changed.

After this PR, it still checks health every `CHECK_INTERVAL`. But it only writes if the result actually changed, or if `HEARTBEAT_PERIOD`says it's been too long since the last write, regardless.

### Fundamentals first

Two things are worth being clear on before any of this makes sense.

First, **a Node condition**. Every Node object in Kubernetes carries a list of conditions each with a type, a status of `True`/`False`/`Unknown`, a short reason code, a human-readable message, and two timestamps: when the condition last transitioned to a new status and when it was last confirmed at all.

Second, **etcd**. This is the key-value store Kubernetes uses to persist everything i.e. every Node, every Pod, every object. The important detail is that etcd doesn't do partial updates. When you write a Node object (Note: a node object is the Node’s full YAML that we see when we run `kubectl get node my-node -o yaml`), you are not patching one field somewhere. The entire Node including its labels, its taints, every condition it carries, all of it gets serialized and written as one value under one key. Every write is a full rewrite of the whole object.

Put those two together and the shape of the problem becomes obvious: a condition update is small and conceptually cheap but the actual write it triggers is not small at all. It's the same cost as rewriting the entire node.

### Why writing every time is a problem

This is the part I did not understand at first, and it's the part that actually matters here.

My first assumption was that writing more often means more requests hitting the API server, and that's a scaling problem on its own. That's not quite right, and the PR discussion walks through why. 

In simple words, the actual cost is in etcd, which is the database Kubernetes. When the reporter writes a Node's status, etcd doesn't update just the one field that changed. It has to persist the entire Node object again i.e. every label, every taint, every other condition, all of it. 

We can think of it like, a key-value store like etcd does not understand "fields" inside that value at all. It just sees one blob of bytes under one key. So when the reporter wants to update for example, *just* the `CalicoReady` condition i.e. one status field, one reason, one timestamp, there's no way to tell etcd "just change this one line" as etcd has no concept of "one line" inside the value. The only operation it has is: take the *whole* blob, and replace it with a *new whole* blob.

This is because that is how etcd stores things. So a write that changes nothing meaningful, still costs the same as a write that changes something real. Multiply that by thousands of nodes checking in every thirty seconds and you are asking etcd to constantly re-save data that hasn't actually changed.

That distinction is something that I picked up by reading the discussion in order, watching the author's first explanation get corrected then watching the corrected version get refined again. 

### The fix

Before writing, the reporter now checks whether the condition it's about to write is actually different from the condition already stored i.e. same `Status`, same `Reason`, same `Message`. If nothing is different, it skips the write entirely.

That's the whole idea. Everything else in the PR exists to make that one decision.

### Why you can't just stop writing

Skipping the write has a side effect. Node conditions carry a field called `LastHeartbeatTime` (see [here](/3bf69b308045805cb345e9e3df710f16#3c169b308045803bafa3d5bd66be9b1c)) i.e. the last time the condition was confirmed, whether or not anything changed. If the reporter simply stops writing whenever the state is unchanged, that timestamp goes stale. And a stale `LastHeartbeatTime` looks exactly like a dead reporter even if the reporter is running perfectly fine and just has nothing new to say.

This is where `HEARTBEAT_PERIOD` comes in. In simple terms, it is a ceiling on how long the reporter is allowed to stay silent. Even if nothing has changed, once this much time has passed since the last write, the reporter writes anyway, purely to refresh `LastHeartbeatTime`. 

If the health status actually changes, it writes immediately regardless of the timer. The default is five minutes, which matches the default used by Node Problem Detector, an existing & more established tool that does the same kind of periodic heartbeat instead of writing on every check. 

The kubelet does something close to the same thing for the node it runs on: it doesn't hammer the API server on every internal health tick, but it guarantees a status write within a bounded window, so a healthy but quiet node never looks indistinguishable from a dead one. 

Also, lease renewal in leader election works the same way i.e. a leader doesn't need to prove it's alive constantly, just often enough that nobody reasonably concludes it's gone. 

This PR in its entirety tries to solve one important issue i.e. how do you tell the difference between "nothing to report" and "not reporting"?

So there end up being two clocks doing different jobs, and I mixed them up more than once: `CHECK_INTERVAL` controls how often the reporter *looks*, and `HEARTBEAT_PERIOD` controls how long it's allowed to stay quiet once it has nothing new to report.

### Final thought process

I don't think I understood any of this from the diff alone. The code is small enough that you can read it in a minute and still not know why it exists. What helped me make sense of it was reading the discussion in the order it happened, letting the wrong explanation come first and watching it get corrected instead of jumping straight to the final version. The first framing of a problem in a PR is rarely the most accurate one but the discussion underneath it usually is.

Also, I don't think I learned anything here that is written down cleanly in a Kubernetes tutorial. Instead, I learned that a PR discussion can be overwhelming at times (read always) but it does force you to think things through, and try to understand the reasoning behind a reviewer’s comments.

None of this was hard, exactly. It was slow and it took time. Considering we have the privilege of time, I think slow is just what understanding a new codebase and a new review culture actually looks like and nobody really tells you that going in.

*Here is my merged *[*PR*](https://github.com/kubernetes-sigs/node-readiness-controller/pull/314)* and the discussions that followed, in case you decide to have a look.*
