# Privacy And Security

## Safe Defaults

- Public `active/` and `archive/` memories are searchable by default.
- `private/` requires `--include-private` for every index and search operation.
- Inbox candidates are never indexed or searched.
- Semantic state is outside the memory root by default.
- Semantic cache records contain no plaintext memory body.
- Automatic recall is disabled unless a gateway explicitly invokes it.
- Recall failure produces no injected block and does not block the user message.

## Remote Embedding Boundary

Semantic indexing sends chunk text to the configured provider. A local cache
does not make that transmission local. Before using `--include-private`, obtain
the required consent and review the provider's retention and data-use terms.

Use separate provider credentials and state directories when privacy domains
must not mix. Never put API keys in repository files, command examples with
literal values, logs, issues, or support bundles.

## Cache And Mirror Sensitivity

Vectors can leak information even without plaintext. Protect semantic state as
sensitive derived data. A fallback mirror contains complete Markdown and needs
the same access controls as the authority.

## Multi-Host Threats

- Never expose NFS directly to the public network.
- Use NFSv4 and loopback listeners behind authenticated SSH forwarding.
- Use a dedicated unprivileged tunnel account and pinned host keys.
- Keep numeric UID/GID ownership consistent.
- Prefer `root_squash` unless a documented review justifies otherwise.
- Use hard mounts for writable authority; avoid `soft` mounts.
- Verify actual cross-host lock behavior after server/client upgrades.
- Fail read-only instead of creating a second writable authority.

## Current Facts Override Memory

Memory cannot grant permission. Current user instructions, approval policy,
workspace, network state, model, and system rules must be rebuilt from current
facts. A historical note saying an operation was once approved does not approve
it now.

## Before Publishing A Fork

Search the complete Git tree, not only current files, for:

- tokens, credentials, private keys, cookies, and OAuth data;
- IP addresses, hostnames, usernames, and home paths;
- chat, user, session, device, or account identifiers;
- private memory bodies and personal profile data;
- live backup paths and internal service names.
