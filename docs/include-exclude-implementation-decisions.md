# Include/exclude implementation decisions

- Selection remains behind the existing DX v2 entry encoding boundary.
- Git ignore decisions use one batched `git check-ignore -z --stdin --verbose --non-matching` query per pack operation.
- `--only` is an isolated source mode and retains output, `.git`, containment, object, and content protections.
- `--path` defines candidate scope without overriding Git-ignore, DX ignore-file, or default soft exclusions; positive filters and `--only` provide explicit-selection strength.
- User excludes and exclude extensions are hard exclusions. Includes and include extensions form one positive-filter union.
- Candidate identities are selection-root-relative POSIX paths and candidate access always uses the selection root.

## DX v2.0.0 completion status

Issue #92 completes the unreleased DX v2.0.0 selection increment without
changing the carrier version or serialization boundary.

The implemented user-visible selection behavior is:

- a directory supplied with `--path` contributes the complete candidate scope
  but does not bypass Git-ignore, DX ignore files, or default soft exclusions;
- a directly supplied file remains an explicit selection;
- `--only` is an isolated explicit source mode and still preserves protected
  path, containment, object, output, and content-policy checks;
- `--include` and `--include-extension` act as positive filters and may restore
  only their own matching candidates from soft exclusions;
- hard exclusions continue to win over positive filters and explicit source
  strength;
- directory intent belongs in source providers such as positional `SOURCE`,
  `--path`, or `--only`, not in file-filter operands;
- device-mode default output remains a numbered `.dx.txt` carrier; and
- compatibility adapters remain available while callers migrate to the
  provider-and-scope model.

Examples:

```bash
# Restrict candidate discovery to docs while preserving ignore processing.
python dx.py pack . --path docs/

# Explicitly select docs as an isolated source.
python dx.py pack . --only docs/

# Restore only the matching ignored file from the candidate scope.
python dx.py pack . --path config/ --include 'config/local.env'
```

`dx.py` remains the authoritative implementation for packing, inspection,
verification, unpacking, and application. New and modified carriers remain
DX v2.0.0 files delivered with the `.dx.txt` filename extension.
