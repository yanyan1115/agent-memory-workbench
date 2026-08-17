# Two-Host NFSv4 Over SSH

This advanced topology gives multiple agent hosts one writable authority without
exposing NFS publicly.

Use role names:

- **storage-host** owns the physical backing directory.
- **client-host** runs another agent and keeps a local read-only fallback.

## Topology

```text
storage-host physical backing: /srv/agent-memory-backing
storage-host canonical mount:  /srv/agent-memory

storage-host 127.0.0.1:2049
    -> reverse SSH tunnel
client-host 127.0.0.1:<tunnel-port>
    -> NFSv4 staging mount
client-host canonical mount:   /srv/agent-memory
```

The storage host also uses its canonical NFS mount. Never let applications edit
the backing directory directly; direct filesystem locks and NFS locks may not
share one lock domain.

## 1. Storage Host

Export only an NFSv4 pseudo-root and restrict the listener to loopback using the
distribution's NFS configuration. A conceptual export is:

```exports
/srv/agent-memory-backing 127.0.0.1(rw,fsid=0,sync,subtree_check,root_squash)
```

Requirements:

- NFSv4 only; disable NFSv3 and unnecessary rpcbind exposure.
- Verify the NFS socket listens only on `127.0.0.1` and/or `::1`.
- Keep consistent numeric UID/GID ownership across hosts.
- Mount `127.0.0.1:/` at `/srv/agent-memory` with a hard NFSv4 mount.
- Make services require the mount so they cannot fall through to a local directory.

Exact NFS daemon configuration differs across Debian, Ubuntu, Fedora, and other
systems. Verify with socket and mount inspection rather than trusting a sample
filename.

## 2. SSH Tunnel

Create a dedicated unprivileged tunnel account on the client host. Provision and
pin host keys through a trusted channel. Restrict the key to the required remote
forward where the SSH implementation supports it.

From the storage host, the tunnel shape is:

```bash
ssh -NT \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -R 127.0.0.1:<tunnel-port>:127.0.0.1:2049 \
  tunnel-user@client-host
```

Do not use a privileged remote account as the public default. Do not disable
host-key checking.

A parameterized systemd example is in
[`examples/systemd/memory-nfs-tunnel.service.example`](../../examples/systemd/memory-nfs-tunnel.service.example).

## 3. Client Mount

Mount the forwarded loopback endpoint as NFSv4. The exact options depend on the
client implementation; a representative shape is:

```fstab
127.0.0.1:/ /mnt/agent-memory-nfs nfs4 noauto,hard,_netdev,nofail,vers=4.2,proto=tcp,port=<tunnel-port>,local_lock=none 0 0
```

Bind the verified NFS staging mount to the same canonical application path used
on the storage host. Ensure the canonical path is a real mountpoint before
starting writers.

`local_lock=none` is not proof of correct cross-host locking. Run the acceptance
test below on the actual server and clients.

## 4. Elect One Semantic Index Writer

Set an explicit host role in root-owned configuration. Only the storage/index
host runs:

```bash
memsearch index --root /srv/agent-memory --provider <provider>
```

Other hosts may run `memsearch search` against the completed state. If state is
not on the shared filesystem, publish the completed cache generation separately
and atomically; never let two hosts update the same semantic cache.

## 5. Read-Only Fallback

While shared mode is healthy, publish a local immutable mirror on the client:

```bash
memory-mirror \
  --root /srv/agent-memory \
  --destination /var/cache/agent-memory-ro \
  --keep 3
```

`memory-mirror` takes a shared memory lock, rejects symlinks, validates the
copied library, removes write bits, creates a versioned release, and atomically
switches `current`.

During an outage:

1. Stop all writers on the client.
2. Unmount the failed NFS/bind mount cleanly.
3. Bind-mount `/var/cache/agent-memory-ro/current` at a fallback staging path.
4. Remount the bind read-only.
5. Bind that read-only mount to the canonical application path.
6. Verify a write fails with `EROFS` before starting read-only agents.

Never synchronize fallback changes back to the authority. There should be no
fallback changes: the kernel read-only mount is the enforcement boundary.

On recovery, stop readers, remove fallback binds, validate the tunnel and NFS
sentinel, restore the shared mount, and only then restart writers.

## 6. Acceptance Tests

Do not declare deployment complete until all pass:

1. NFS and forwarded ports listen only on loopback.
2. Both canonical paths are mountpoints, not symlinks or ordinary directories.
3. An exclusive `fcntl.flock` on one host blocks acquisition on the other.
4. An atomic replacement on one host is immediately visible on the other.
5. Candidate promotion and deterministic index generation work through the mount.
6. Only the elected host can publish semantic state.
7. Forced tunnel loss selects a read-only mirror and writes fail with `EROFS`.
8. Recovery returns to the single shared authority without copying fallback data back.

Repeat the lock and outage tests after NFS, kernel, SSH, or mount-option changes.
