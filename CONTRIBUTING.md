# Contributing

Contributions are welcome. Keep the project file-first, auditable, and safe by
default.

Before opening a pull request:

```bash
python3 -m pip install -e .
python3 -m unittest discover -s tests -v
memoryctl doctor --root examples/basic-memory-root
```

Never commit real memory bodies, credentials, host addresses, account or chat
identifiers, private deployment paths, embedding caches, or support logs. Use
neutral fictional fixtures and explicit placeholders.

Behavior that changes privacy defaults, locking, atomicity, cache semantics, or
recall injection requires regression tests and documentation.
