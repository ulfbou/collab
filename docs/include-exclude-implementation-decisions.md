# Include/exclude implementation decisions

- Selection remains behind the existing DX v2 entry encoding boundary.
- Git ignore decisions use one batched `git check-ignore -z --stdin --verbose --non-matching` query per pack operation.
- `--only` is an isolated source mode and retains output, `.git`, containment, object, and content protections.
- `--path` defines candidate scope without overriding Git-ignore, DX ignore-file, or default soft exclusions; positive filters and `--only` provide explicit-selection strength.
- User excludes and exclude extensions are hard exclusions. Includes and include extensions form one positive-filter union.
- Candidate identities are selection-root-relative POSIX paths and candidate access always uses the selection root.
