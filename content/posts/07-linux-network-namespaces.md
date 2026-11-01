---
title: "Linux Network Namespaces"
date: 2026-11-01
description: "Let’s learn about linux network namespaces and build a whole network in one laptop"
tags: ["linux", "networking"]
draft: false
source: notion
---

I've started diving into the world of Linux networking lately, and in the initial part I thought we needed several machines or at least several virtual machines to practice anything about routers and networks. So when I found out that one Linux machine can pretend to be many machines, I was surprised and I wanted to write it down in the sense that it can help anyone else who is just starting and to make sure I really understood it myself.

I'm still learning so if I get something slightly wrong in the process, please be kind and let me know :P

### The problem

Real networking problems almost always involve more than one machine. There's a client, there's a server, and often a router sitting in the middle. If I want to test a route or understand why a packet isn't arriving, I need at least two or three "machines" talking to each other. Setting up three virtual machines every time I want to try a small experiment felt like way too much work.

Linux has a neat answer to this, and it's called a **network namespace**.

### A "network stack"

Before the main idea, there's one term I had to learn. A **network stack** is everything the kernel uses to handle networking: the network interfaces (like `eth0`), the IP addresses on them, the route table (the list that says where each packet should go) and the firewall rules.

Normally our computer has exactly one of these and every program shares it. That's why when we add a route, it shows up in the one `ip route show` that everyone sees.

### A network namespace

A **network namespace** is a complete, separate copy of the network stack. It has its own interfaces, its own addresses, its own route table and its own firewall rules. A program running inside a namespace can only see that namespace's network, and nothing else.

So for networking purposes, each namespace behaves like its own separate machine, even though it's all one computer underneath. One small thing worth knowing is that it only separates the network. Files, users and processes are still shared with the host, which is why it's so much lighter than a virtual machine.

![Image](/images/posts/07-linux-network-namespaces/img1.png)

### Making my first one

Here's the first thing I tried (you'll need root, so use `sudo` if you're not root):

```bash
ip netns add ns1
ip netns exec ns1 ip addr
```

The first command creates a namespace called `ns1`. The second one uses `exec`, which means "run this command inside that namespace." Here the command is `ip addr`, which lists interfaces.

What I saw was only this:

```plain text
1: lo: <LOOPBACK> mtu 65536 ...
```

Just one interface, `lo`, which is the loopback interface and it was even switched off. It exists but it can't talk to anything yet.

### The cable: a veth pair

So how do we plug in a cable? In Linux, the virtual cable is called a **veth pair**. "veth" stands for virtual Ethernet. It's two virtual interfaces created together and they act like the two ends of one cable: whatever goes into one end comes out of the other.

```bash
ip link add veth1 type veth peer name veth1p
```

This creates both ends at once, named `veth1` and `veth1p`. Right after creating them, both ends are sitting on the host. To connect two namespaces, we push one end into each:

```bash
ip link set veth1  netns ns1
ip link set veth1p netns ns2
```

An interface can only live in one namespace at a time, so after this, `veth1` belongs to `ns1` and `veth1p` belongs to `ns2`. Two separate machines, one cable between them.

![Image](/images/posts/07-linux-network-namespaces/img2.png)

### Let's make two machines talk

Here are the steps in order. 

1. Create two machines/namespaces:

1. Create the cable and plug in each end:

1. Give each end an IP address:

1. Turn both ends on (a cable that's switched off carries nothing):

1. Test it:

We can see that the reply came back i.e. Two machines were talking and we haven’t touched a single real cable.

We might wonder why we didn't have to add a route. When we give an interface an address like `10.0.0.1/24`, Linux automatically adds a route for that whole `10.0.0.0/24` network through that interface.

### A router in the middle

Two machines on one cable is nice but real networks have separate **subnets** (smaller networks) joined by a **router**. So I built this:

![Image](/images/posts/07-linux-network-namespaces/img3.png)

- `ns1` lives on the subnet `10.0.1.0/24`

- `ns2` lives on a different subnet, `10.0.2.0/24`

- `nsrouter` has two interfaces, one in each subnet, and passes packets between them, just like a small office router

For this to work, three things need to be true:

**1. Addresses on every interface.** 

`ns1` gets `10.0.1.1`, the router gets `10.0.1.254` on the ns1 side and `10.0.2.254` on the ns2 side, and `ns2` gets `10.0.2.1`.

**2. Routes that use ****`via`****.** 

`ns1` only knows about its own subnet. To reach `10.0.2.0/24`, it has to be told to send that traffic to the router:

```bash
ip netns exec ns1 ip route add 10.0.2.0/24 via 10.0.1.254
```

The word `via` means "the next hop is this address," which is the router's address on the same subnet. And `ns2` needs the matching route back:

```bash
ip netns exec ns2 ip route add 10.0.1.0/24 via 10.0.2.254
```

Without the return route, the ping reaches ns2 but the reply has no way home. This was the one that confused me the most at first.

**3. Forwarding turned on in the router.** 

By default, Linux throws away packets that arrive for someone else, which is a sensible safety default for a normal computer. A router has to pass them along, so we switch that on:

```bash
ip netns exec nsrouter sysctl -w net.ipv4.ip_forward=1
```

`sysctl -w` sets a kernel setting, and it's per namespace so it has to run inside `nsrouter`.

### What happens to one packet

When `ns1` pings `10.0.2.1`, this is the journey:

1. `ns1` checks its routes and sees "for `10.0.2.0/24`, go via `10.0.1.254`," so it sends the packet to the router.

1. The packet crosses cable A and arrives at `nsrouter`.

1. The router sees the packet isn't meant for itself. Forwarding is on, so it looks at its own routes and finds `10.0.2.0/24` is directly attached on its other interface.

1. The packet crosses cable B and reaches `ns2`.

1. `ns2` replies, and the packet makes the same trip backwards using its return route.

### Breaking it on purpose

The part that taught me the most was breaking things. Try these:

1. With the lab working, turn forwarding off: `ip netns exec nsrouter sysctl -w net.ipv4.ip_forward=0`. The ping now hangs, because packets reach the router and stop there.

1. Turn it back on, then remove the return route: `ip netns exec ns2 ip route del 10.0.1.0/24`. The ping hangs again, because the reply can't find its way home.

Once you've seen each failure with your own eyes, you won't forget what each piece does.

### Conclusion

The biggest reason why namespaces matter is that we can practice real networking problems on one machine, with no extra hardware and without risking our own network. If something goes wrong, we just delete the namespace.

Also, this is exactly how containers get their networking. Every Docker or Kubernetes container lives in its own network namespace, connected to the host by a veth pair. So even if we never planned to build a lab, we’ve probably been using this idea every day without noticing.
