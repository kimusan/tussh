# TuSSH Connection Profiles

This document describes the built‑in connection profiles available when adding a new host in TuSSH. Profiles pre‑fill common SSH options to match typical scenarios. You can still edit any fields before saving.

General notes
- Non‑destructive: Profiles only pre‑populate fields; you can tweak or remove values freely.
- Structured vs extras: Options with dedicated inputs (e.g., `ServerAliveInterval`) populate those inputs. Everything else is added to the “Additional options” area.
- Comments: Some advanced options are inserted as commented lines so you can opt in by uncommenting.
- ControlMaster path: Profiles that use multiplexing ensure `~/.ssh/cm` exists.
- Security: Profiles aim for safe defaults, but you should always validate against your environment and policies.


## Fast connect
Optimizes for quick starts and snappy reconnects.

When to use
- Frequent short SSH sessions to the same hosts.

Sets
- ServerAliveInterval=20, ServerAliveCountMax=2
- Compression=yes
- Extras: ControlMaster auto, ControlPersist 60, ControlPath ~/.ssh/cm/%r@%h:%p

Pros
- Faster subsequent connections via multiplexing
- Reasonable keepalives to detect drops

Cons/Notes
- Requires filesystem for ControlPath; TuSSH ensures `~/.ssh/cm` exists


## Hardened
Prefers stricter, key‑only authentication with conservative defaults.

When to use
- Security‑sensitive environments; production bastions

Sets
- StrictHostKeyChecking=yes
- PreferredAuthentications=publickey
- Compression=no
- ServerAliveInterval=30, ServerAliveCountMax=3
- Extras: PasswordAuthentication no, KbdInteractiveAuthentication no, IdentitiesOnly yes

Pros
- Disables password and keyboard‑interactive auth
- Enforces key checking

Cons/Notes
- Requires keys correctly provisioned


## Low bandwidth
Aims to save bytes while staying resilient.

When to use
- Slow or metered links

Sets
- Compression=yes
- ServerAliveInterval=30, ServerAliveCountMax=3
- PreferredAuthentications=publickey
- Extras (commented): Ciphers chacha20‑poly1305@openssh.com; MACs hmac‑sha2‑256,hmac‑sha2‑512

Pros
- Compression helps reduce traffic

Cons/Notes
- Advanced ciphers/MACs are commented; enable only if supported fleet‑wide


## Stable NAT / Idle (Keepalive‑heavy)
Keeps connections alive across flaky NAT/VPNs.

When to use
- Intermittent networks that drop idle flows

Sets
- ServerAliveInterval=15, ServerAliveCountMax=6
- Compression=no
- Extras: TCPKeepAlive yes

Pros
- More frequent application‑level keepalives

Cons/Notes
- Slightly higher overhead due to keepalive traffic


## Multiplexed persistent
Persistent master connections for many child sessions.

When to use
- Heavy multi‑session workflows (e.g., multiple terminals/editors)

Sets
- ConnectTimeout=5
- Extras: ControlMaster auto, ControlPersist 300, ControlPath ~/.ssh/cm/%r@%h:%p
- Extras (commented): ServerAliveInterval 20; ServerAliveCountMax 3

Pros
- Very fast additional sessions to the same host

Cons/Notes
- Ensure `~/.ssh/cm` exists (TuSSH creates it)


## Bastion (ProxyJump)
Simple jump host path via `ProxyJump`.

When to use
- Environments requiring a bastion to reach private hosts

Sets
- ProxyJump=bastion (edit this to your bastion alias)
- StrictHostKeyChecking=yes

Pros
- One line to route through bastion

Cons/Notes
- You may prefer the built‑in ProxyJump builder for complex chains


## Dev tunnels (LocalForward)
Common local forward pattern (edit values as needed).

When to use
- Local development requiring DB/app access through SSH

Sets
- LocalForward=127.0.0.1:5432 127.0.0.1:5432 (example)
- ServerAliveInterval=20, ServerAliveCountMax=3
- Extras (commented): ExitOnForwardFailure yes

Pros
- Quick starting point for common forwards

Cons/Notes
- Replace ports/hosts to match your setup


## Reverse tunnels (RemoteForward)
Expose a local service to the remote via reverse forwarding.

When to use
- Remote access to a local service (e.g., support session)

Sets
- RemoteForward=0.0.0.0:8080 127.0.0.1:8080 (example)
- ServerAliveInterval=20, ServerAliveCountMax=3
- Extras: GatewayPorts yes

Pros
- Easiest path to expose a local port remotely

Cons/Notes
- Opens a listening port on the remote; ensure firewall/policy allows it


## Kerberos / GSSAPI
Enterprise environments using Kerberos/AD.

When to use
- Domain‑joined environments with GSSAPI auth

Sets
- PreferredAuthentications=gssapi-with-mic,publickey
- StrictHostKeyChecking=yes
- Extras: GSSAPIAuthentication yes; GSSAPIDelegateCredentials no

Pros
- Integrates with enterprise auth flows

Cons/Notes
- Requires correct client and server configuration for GSSAPI


## IPv4 only
Disable IPv6 for problematic networks.

When to use
- Sites where IPv6 is broken or misconfigured

Sets
- ConnectTimeout=5
- Extras: AddressFamily inet

Pros
- Avoids slow IPv6 fallbacks

Cons/Notes
- IPv6-only hosts won’t be reachable


## X11 forwarding
Enable X11 forwarding for GUI apps over SSH.

When to use
- Running remote GUI apps locally

Sets
- ForwardX11=yes
- Compression=yes
- Extras: ForwardX11Trusted yes

Pros
- One-click setup for X11 forwarding

Cons/Notes
- Ensure X server is available locally; consider security implications


## Mosh client
Switch connection client to Mosh for better roaming/latency handling.

When to use
- High‑latency or lossy links; frequent roaming between networks

Sets
- Per‑host override: client=mosh

Pros
- Better experience on poor or roaming networks

Cons/Notes
- Requires Mosh installed and UDP connectivity

