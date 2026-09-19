# DX Include and Exclude Filtering Specification

Status: Proposed, implementation-ready
Target: dx.py v2.1
Scope: Candidate discovery, path-rule evaluation, content policy, diagnostics, Git integration, safety, compatibility, and verification for `dx.py pack`

## 1. Purpose

This specification defines the complete selection system used by `dx.py pack`. It replaces ad hoc path collection and filtering with a deterministic pipeline in which:

1. source providers discover candidate files;
2. every candidate has one canonical path relative to one selection root;
3. rule providers produce ordered matches;
4. precedence produces one path-selection verdict;
5. filesystem and content policies validate selected paths and bytes;
6. diagnostics retain the complete decision trace; and
7. output ordering and counts are reproducible.

The specification is normative unless a section is explicitly marked informative.

## 2. Goals

The implementation MUST provide:

- one selection root and one candidate identity model;
- composable file and directory operands;
- Git-wildmatch-compatible user patterns;
- effective Git-ignore behavior for Git-origin rules;
- hard exclusions that no include can override;
- explicit selections that override only soft exclusions;
- precise extension filters;
- safe handling of `.git`, output files, symlinks, and root boundaries;
- deterministic results independent of traversal order;
- complete human-readable and machine-readable explanations;
- exact, non-overlapping terminal counts;
- compatibility diagnostics for changed behavior; and
- unit, integration, golden, property, and differential tests.

## 3. Non-goals

Version 2.1 does not:

- represent deletions in a DX carrier;
- represent symbolic links as symbolic links;
- follow directory symlinks;
- use operating-system glob expansion as its pattern language;
- allow includes to override protected or hard-exclude rules;
- infer an ignore language from arbitrary files;
- silently broaden selection when Git-ignore evaluation fails; or
- preserve filesystem iteration order in carrier output.

## 4. Normative language

The terms MUST, MUST NOT, REQUIRED, SHALL, SHALL NOT, SHOULD, SHOULD NOT, MAY, and OPTIONAL are normative requirements.

A usage error exits with code 2. An invalid carrier exits with code 3. An I/O or external-tool failure exits with code 4. A write conflict exits with code 5. A verification failure exits with code 6.

## 5. Conceptual model

### 5.1 Layers

The implementation MUST separate these layers:

1. CLI parsing and option validation.
2. Selection-context construction.
3. Source-provider discovery.
4. Candidate normalization and deduplication.
5. Rule-provider construction.
6. Path-rule evaluation.
7. Filesystem-object validation.
8. Content classification and policy.
9. Decision aggregation and diagnostics.
10. Stable output planning.
11. Carrier serialization.

A layer MAY consume immutable output from an earlier layer. It MUST NOT mutate the behavior of an earlier layer based on later results.

### 5.2 Pipeline

The normative pipeline is:

```text
CLI options
  -> selection context
  -> source providers
  -> raw discovered paths
  -> normalized candidates
  -> operational protections
  -> protected rules
  -> hard excludes
  -> positive filters
  -> explicit-selection determination
  -> soft-exclude verdict
  -> path-selected candidates
  -> filesystem validation
  -> byte loading and content classification
  -> content policy
  -> final decisions
  -> stable output order
  -> carrier
```

No later stage may resurrect a candidate terminally excluded by an earlier stage.

## 6. Terminology

### 6.1 Selection root

The single absolute directory against which all candidate identities and user patterns are interpreted.

### 6.2 Discovery scope

The file or directory from which a source provider discovers files. A discovery scope may be narrower than the selection root.

### 6.3 Candidate

A normalized, deduplicated potential carrier entry identified by a POSIX path relative to the selection root. Candidate creation does not imply inclusion.

### 6.4 Source provider

A component that contributes candidate paths. Source providers are positional `SOURCE`, default walk, `--path`, `--from-git`, and `--only`.

### 6.5 Rule provider

A component that produces path-rule matches. Providers include protected rules, output protection, user exclusions, extension exclusions, positive filters, Git ignore, explicit ignore files, and default excludes.

### 6.6 Protected rule

A non-overridable safety exclusion, such as a `.git` path component unless unsafe Git inclusion is explicitly enabled.

### 6.7 Hard exclude

A user-requested exclusion that no include or explicit selection may override.

### 6.8 Positive filter

A rule in the union of `--include` and `--include-extension`. If the union is non-empty, a candidate must match at least one member to remain eligible.

### 6.9 Explicit selection

A property of a candidate that overrides soft exclusions. A candidate is explicitly selected when it is the positional single-file source, matches a positive filter, or is contributed by `--only`. Contribution by `--path` defines candidate scope but does not itself create explicit-selection strength.

### 6.10 Soft exclude

An exclusion that applies only when the candidate is not explicitly selected. Git ignore and default excludes are soft excludes.

### 6.11 Terminal outcome

Exactly one final category assigned to every candidate: output-protected, protected, hard-excluded, positive-filter-missed, soft-excluded, invalid-object, unreadable, binary-skipped, or selected.

### 6.12 Decision trace

The normalized candidate, provenance, every relevant rule match, explicit-selection basis, decisive path verdict, filesystem result, content result, and terminal outcome.

## 7. CLI contract

### 7.1 Selection options

```text
SOURCE
--root DIR
--path PATH                 repeatable
--from-git
--only PATH                 repeatable
--include PATTERN           repeatable
--exclude PATTERN           repeatable
--include-extension EXT     repeatable
--exclude-extension EXT     repeatable
--ignore-file FILE          repeatable
--no-gitignore
--no-default-excludes
--no-ignore
--unsafe-include-git
--skip-binary
--binary
--readonly
```

### 7.2 Diagnostic options

```text
--dry-run
--json
--explain
--explain=json
--quiet
--verbose
```

### 7.3 Mutual exclusions and implications

The following are usage errors:

- `--path` with `--from-git`;
- `--only` with `--path` or `--from-git`;
- `--only` with any include, exclude, extension, ignore-file, or ignore-disable option;
- `--binary` with `--skip-binary`;
- `--quiet` with `--verbose`;
- `--unsafe-include-git` without `--force`;
- `--explain=json` with a non-JSON explanation mode;
- a second positional output when `--output` is also supplied.

`--no-ignore` is exactly equivalent to `--no-gitignore --no-default-excludes`.

`--explain=json` implies `--dry-run` and structured JSON output. For pack dry-run, `--json --explain` and `--explain=json` MUST produce the same decision-bearing schema.

### 7.4 `--only`

`--only` is repeatable. Its operands form the complete candidate scope. In this mode:

- Git-ignore, default-exclude, user-pattern, and extension providers are disabled;
- output protection, `.git` protection, root containment, symlink policy, regular-file validation, readability, binary policy, and read-only metadata remain active;
- `.git` remains excluded unless `--unsafe-include-git --force` is present; and
- all contributed candidates are explicitly selected.

`--only` is therefore an isolated source mode, not an alternate serializer and not a bypass around safety or content policy.

## 8. Selection context

The implementation MUST construct one immutable selection context before discovery. It contains at least:

```text
selection_root
source_path
source_kind
repository_root or null
output_path or stdout
source_mode
normalized option values
rule providers
content policy
```

### 8.1 Root derivation

The selection root is determined as follows:

1. If `--root` is supplied, its resolved directory is the selection root.
2. Otherwise, if `SOURCE` is an existing directory, its resolved path is the selection root.
3. Otherwise, if `SOURCE` is an existing regular file, its resolved parent is the selection root.
4. Otherwise, when `SOURCE` is omitted, the resolved current directory is both source and selection root.

`--root` MUST exist and be a directory.

### 8.2 Containment

When both `SOURCE` and `--root` exist, resolved `SOURCE` MUST equal the selection root or be contained by it. Every `--path` and `--only` operand MUST resolve within the selection root.

Lexical absolute paths are allowed only where the CLI explicitly permits them. Lexical traversal containing a `..` component MUST be rejected before filesystem resolution for operands documented as root-relative.

Containment MUST be checked after resolution as well as lexically. A symlink or mount arrangement MUST NOT permit a path outside the selection root to acquire an in-root candidate identity.

### 8.3 Candidate identity

For an absolute discovered file `F` and selection root `R`, candidate identity is exactly:

```text
F.relative_to(R).as_posix()
```

The discovery scope never changes candidate identity. For example, packing `project/src` with `--root project` produces `src/app.py`, not `app.py`.

Candidate paths MUST:

- be non-empty;
- use `/` separators;
- be relative;
- contain no empty, `.` or `..` component;
- contain no NUL, carriage return, line feed, or double quote;
- compare by their normalized string identity; and
- be sorted by Unicode code-point order for deterministic output.

Path case MUST NOT be folded for candidate identity, even on a case-insensitive filesystem. If two discovered filesystem objects normalize to the same candidate path, they collapse to one candidate and retain all source provenance.

## 9. Source providers

### 9.1 Default walk

With no `--path`, `--from-git`, or `--only`, a directory `SOURCE` is walked recursively.

The walk MUST:

- begin at `SOURCE`;
- create candidate identities relative to the selection root;
- not follow directory symlinks;
- not emit file symlinks;
- prune path components named `.git` unless unsafe Git inclusion is enabled;
- enumerate directory entries in sorted order or sort candidates after discovery;
- retain discovery failures as I/O errors rather than silently skipping them; and
- avoid reading file bytes during discovery.

Pruning `.git` is an optimization only. The protected evaluator MUST independently exclude `.git` candidates if a source provider supplies one.

### 9.2 Positional file source

An existing regular-file `SOURCE` contributes exactly one explicitly selected candidate. It behaves like `--path` for selection strength, but remains the positional source for root derivation and diagnostics.

A positional symlink is rejected by filesystem-object validation.

### 9.3 `--path`

Each `--path` operand is interpreted relative to the selection root unless the CLI explicitly accepts an absolute contained path. Operands are processed in CLI order for provenance, while final candidates are deduplicated and sorted.

A file operand contributes one candidate. A directory operand contributes every descendant regular non-symlink file. Multiple operands form a union. Contribution by `--path` defines candidate scope and does not itself make a candidate explicitly selected.

When `--path` is present, that union is the complete candidate set. `--path` does not add to a default walk. Git ignore, DX ignore files, and default excludes remain effective. Protected rules and hard excludes still apply. Positive filters, when present, further restrict the set and give matching candidates explicit-selection strength.

### 9.4 `--from-git`

`--from-git` obtains candidate records from:

```text
git status --porcelain=v1 -z --untracked-files=all
```

The command MUST execute at the repository root. Repository-relative paths MUST be converted to selection-root-relative identities. Records outside the selection root are ignored and counted as outside-scope records in verbose diagnostics.

Rules by status:

- modified, added, unmerged, type-changed, and untracked destination paths contribute candidates if they resolve to regular non-symlink files;
- rename and copy records contribute the destination path only and retain the source path as diagnostic metadata;
- any deletion record causes a usage error because the carrier format cannot represent deletion;
- a destination outside the selection root does not become a candidate;
- submodule entries are rejected unless they resolve to ordinary file content supported by DX; and
- malformed or undecodable records cause an I/O error.

Ignored untracked files are absent from this source provider. `--no-gitignore` has no effect on `--from-git`; an include cannot resurrect a path that is not a candidate. Users must use `--path` or `--only` to select an ignored untracked file.

Candidates from `--from-git` are not explicitly selected merely because Git reported them. User includes may explicitly select them; otherwise effective soft excludes apply only where applicable. Tracked candidates MUST NOT be rejected because they match an ignore pattern.

### 9.5 `--only`

Each operand expands using the same file and directory rules as `--path`. The union is the complete candidate set, and every candidate is explicitly selected. Section 7.4 controls which rule providers remain active.

## 10. Pattern model

### 10.1 User path patterns

`--include` and `--exclude` use a tested Git-wildmatch-compatible matcher. They do not invoke the shell and do not use Python `fnmatch` semantics unless that implementation has been extended and verified for full conformance.

Supported syntax includes:

- `*` for zero or more non-separator characters;
- `?` for one non-separator character;
- bracket expressions;
- `**` in Git-compatible positions for crossing directory boundaries;
- leading `/` to anchor at the selection root;
- trailing `/` to designate a directory subtree;
- patterns without `/` matching a name at any depth; and
- backslash escaping consistent with the selected Git-compatible grammar.

User include and exclude options MUST NOT support leading `!` negation. A leading `!` is a literal only when escaped according to the pattern grammar; otherwise it is a usage error with guidance to use multiple options or an ignore file.

### 10.2 Directory matching

A directory match is evaluated against each candidate path and its ancestor directory prefixes. It never inserts a directory object into the carrier.

Therefore:

```text
--path src/ --exclude src/cache/
```

selects eligible descendants of `src/` other than descendants of `src/cache/`.

The following selects nothing under `src/`:

```text
--exclude src/ --include src/keep.py
```

because a hard exclusion cannot be overridden.

### 10.3 Pattern normalization

Patterns MUST preserve semantic leading and trailing separators. Implementations MUST NOT blindly strip `/`, because anchoring and directory-only semantics depend on it.

A pattern is invalid if it contains NUL, carriage return, or line feed, or if its grammar is malformed. Empty user patterns are usage errors.

Patterns are matched against normalized candidate paths using POSIX separators. The matching engine MUST be deterministic and independent of host separator conventions.

### 10.4 Case behavior

User wildmatch patterns are case-sensitive. Candidate identity and path matching MUST not depend on host filesystem case folding.

Extension rules are the explicit exception and are case-insensitive.

## 11. Extension rules

Extension options are typed suffix rules, not rewritten wildmatch patterns.

Normalization:

1. trim surrounding CLI whitespace only if the argument parser has not preserved it intentionally;
2. reject an empty value;
3. reject `/`, `\\`, NUL, carriage return, and line feed;
4. prepend `.` when absent;
5. reject `.` alone; and
6. lowercase for comparison and deduplication.

A candidate matches extension `.tar.gz` when its basename, compared case-insensitively, ends with `.tar.gz`. Extension comparison does not inspect directory names.

`--exclude-extension` is a hard-exclude provider. `--include-extension` participates in the positive-filter union. Duplicate normalized extensions have no additional effect.

## 12. Rule providers and precedence

### 12.1 Normative precedence

For each candidate, evaluate in this order:

1. output-path protection;
2. protected rules;
3. all hard-exclude providers;
4. positive-filter eligibility;
5. explicit-selection basis;
6. effective soft-exclude verdict;
7. filesystem-object validation;
8. content policy.

The first terminal exclusion decides the terminal outcome. Later layers may still be omitted from evaluation, but diagnostics MUST make clear that they were not evaluated because an earlier terminal outcome was reached.

### 12.2 Output-path protection

When output is a filesystem path located under the selection root, its resolved path is always excluded. No user option may override this rule. Output to stdout has no output candidate.

This protection prevents inclusion of an existing carrier being replaced and prevents self-inclusion during writing.

### 12.3 Protected `.git`

Unless unsafe Git inclusion is enabled, any candidate having a path component exactly equal to `.git` is protected and excluded. This includes a `.git` directory and a `.git` regular file used by worktrees or submodules.

Unsafe Git inclusion requires both:

```text
--unsafe-include-git --force
```

No interactive prompt is used. This requirement is deterministic in terminals, scripts, and CI.

Unsafe Git inclusion disables only the `.git` protected rule. It does not disable output protection, hard excludes, root containment, symlink policy, or content policy.

### 12.4 Hard excludes

Hard-exclude providers are:

1. `--exclude`, in CLI order;
2. `--exclude-extension`, in CLI order.

All matching hard rules MUST be recorded for explanation. The first matching hard rule in provider and CLI order is decisive. A hard exclusion always wins over an include, `--path`, positional file source, `--only`, Git negation, or default override.

### 12.5 Positive filters

The positive-filter set is the union of:

1. `--include`, in CLI order;
2. `--include-extension`, in CLI order.

If the set is empty, every candidate passes this stage. If non-empty, a candidate must match at least one positive filter. Failure is terminal with outcome `positive_filter_missed`.

A matching positive filter explicitly selects the candidate and may override later soft exclusion. Positive filters do not create candidates.

### 12.6 Explicit-selection precedence

Explicit selection is true if any of these holds:

- the candidate is a positional single-file source;
- the candidate was contributed by `--only`; or
- the candidate matched an include or include-extension filter.

Contribution by `--path` does not itself create an explicit-selection basis.

The trace MUST record every basis. Explicit selection overrides only a final soft-exclude verdict.

### 12.7 Soft excludes

Soft-exclude providers are:

1. effective Git ignore;
2. DX `--ignore-file` providers in CLI order;
3. default excludes.

A candidate with a final soft-exclude verdict is excluded unless explicitly selected.

For candidate tracing, all provider decisions and matched patterns SHOULD be retained when obtainable without changing semantics. At minimum, the decisive soft provider and pattern MUST be retained.

## 13. Git integration

### 13.1 Repository detection

Repository detection MUST use Git plumbing such as:

```text
git rev-parse --is-inside-work-tree
git rev-parse --show-toplevel
```

The implementation MUST support `.git` as either a directory or a file. It MUST NOT infer repository membership solely from `.git/HEAD`.

If Git-ignore processing is enabled, repository metadata indicates a worktree, and Git cannot execute or cannot produce a reliable result, packing fails with exit code 4. The implementation MUST NOT silently disable Git ignore and broaden selection.

Outside a Git worktree, Git-ignore is inactive. A standalone `.gitignore` outside a worktree is not automatically activated.

### 13.2 Effective Git-ignore semantics

Effective Git-ignore evaluation MUST account for:

- `core.excludesFile`;
- repository `.git/info/exclude`;
- hierarchical `.gitignore` files from repository root through each candidate's containing directory;
- later matching patterns overriding earlier patterns at the same precedence level;
- deeper per-directory files taking precedence over shallower files;
- escaped `#` and `!`;
- comments and blank lines;
- trailing-space rules;
- directory patterns;
- negation; and
- Git path-relative interpretation.

Tracked files are not excluded merely because an ignore rule matches them.

The preferred decision mechanism is batched Git plumbing that accepts NUL-delimited paths and reports per-path ignore decisions. Calls MUST be batched, checked for failure, decoded strictly, and cached for the duration of one pack operation.

### 13.3 DX ignore files

Each `--ignore-file FILE` is a DX soft-rule provider using Git-ignore file syntax. Files are evaluated in CLI order after effective Git ignore and before defaults. Later DX ignore files override earlier DX ignore files. Within one file, later matching patterns override earlier patterns.

Paths referenced by an ignore file are interpreted relative to the selection root, not relative to the ignore file's containing directory. This deliberate DX rule MUST be documented in help and diagnostics.

Ignore files MUST be UTF-8 text. Invalid UTF-8, unreadable files, and malformed patterns fail with exit code 4 for I/O failures or 2 for invalid rule syntax. The ignore file itself may be a candidate unless another rule excludes it.

A negated pattern re-includes only within the ordered DX ignore-file provider. It does not override protected rules, hard excludes, positive-filter misses, or an exclusion from a later soft provider.

### 13.4 `--no-gitignore`

This option disables effective Git-ignore evaluation only. It does not disable DX ignore files, defaults, protected rules, or hard excludes.

When used with `--from-git`, it does not alter Git's candidate source and therefore cannot expose ignored untracked files.

## 14. Default excludes

Defaults are enabled unless `--no-default-excludes` or `--no-ignore` is supplied.

The v2.1 default pattern set is:

```text
.DS_Store
Thumbs.db
*~
*.swp
*.swo
.#*
#*#
```

These patterns match basenames at any depth and are soft excludes. Explicit selection overrides them.

The `.git` rule is protected and is not part of defaults. Disabling defaults MUST NOT disable `.git` protection.

The default set MUST be versioned in code and exposed in verbose diagnostics so behavior changes are reviewable.

## 15. Filesystem-object policy

### 15.1 Regular files

Only regular files may become carrier entries. Directories exist only for discovery and pattern ancestry.

### 15.2 Symlinks

Directory symlinks are never followed. File symlinks are never packed, regardless of whether the target lies inside the selection root. A candidate explicitly referring to a symlink receives terminal outcome `invalid_object` and causes an I/O error unless the source provider could safely omit it during ordinary recursive discovery.

For consistency:

- ordinary walks omit encountered symlinks and may report them under verbose diagnostics;
- direct `SOURCE`, `--path`, `--only`, and `--from-git` references to symlinks fail with exit code 4.

DX v2.1 has no implicit symlink-dereference mode.

### 15.3 Race resistance

The implementation MUST validate the object immediately before reading. It SHOULD use file-descriptor-based checks where available to reduce check-then-open races. If the object changes type, escapes the root, disappears, or becomes unreadable between discovery and read, packing fails rather than silently changing the selected set.

### 15.4 Permissions and errors

Unreadable selected files cause exit code 4. Pack MUST NOT silently omit them. Dry-run without content inspection MAY avoid reading bytes, but when binary classification or exact byte size is requested it MUST perform the same readability checks as a real pack.

## 16. Content policy

Content policy runs only after path selection and regular-file validation.

### 16.1 Classification

Classification MUST be deterministic. The existing DX classification contract is:

- UTF-8 without BOM, NUL, or carriage-return bytes is text;
- all other content is binary and requires lossless binary encoding.

A future classifier change requires a format or behavior review and updated golden tests.

### 16.2 Binary handling

By default binary files are included using the carrier's lossless binary representation. `--binary` explicitly selects that default behavior. `--skip-binary` assigns terminal outcome `binary_skipped` to path-selected binary candidates.

A file skipped as binary is not counted as a selected carrier entry.

### 16.3 Read-only metadata

`--readonly` does not filter files. It marks every final selected entry read-only in carrier metadata.

## 17. Decision data model

The implementation SHOULD use immutable typed records equivalent to:

```text
Candidate
  path: normalized relative POSIX path
  absolute_path: resolved path used for access
  provenance: ordered source records
  git_status: optional status metadata

RuleMatch
  provider: stable provider identifier
  provider_instance: optional index or file path
  rule_kind: protected, hard, positive, soft, operational
  pattern: optional normalized pattern
  action: include or exclude
  order: deterministic evaluation order
  source_location: optional line number

Decision
  candidate: Candidate
  matched_rules: ordered RuleMatch sequence
  positive_filter_present: boolean
  positive_filter_matched: boolean
  explicit_selection_bases: ordered sequence
  path_verdict: selected or excluded
  decisive_reason: stable reason code
  filesystem_kind: optional value
  content_kind: optional text or binary
  readonly: boolean
  terminal_outcome: stable outcome code
```

Decision reason codes are part of the JSON compatibility surface and MUST NOT be changed without a schema-version change.

## 18. Diagnostics

### 18.1 Human explanation

`--explain` writes one deterministic line per candidate to stderr. Lines are sorted by candidate path. Each line includes path, final action, decisive provider, and override information when applicable.

Example:

```text
src/app.py         include  default selection
src/secret.env     include  --include config/local.env overrides gitignore *.env
src/cache/foo.py   exclude  --exclude src/cache/
node_modules/x.js  exclude  gitignore node_modules/
.git/config        exclude  protected .git component
```

Human output is not a stable machine interface.

### 18.2 JSON explanation

Structured output MUST contain exactly one JSON document on stdout. Informational and warning text goes to stderr. In JSON mode, no non-JSON bytes may be written to stdout.

The top-level schema includes:

```json
{
  "schema_version": 2,
  "command": "pack",
  "dry_run": true,
  "selection_root": "/absolute/root",
  "source_mode": "walk",
  "candidate_count": 64,
  "filter_counts": {},
  "rule_match_counts": {},
  "decisions": []
}
```

Each decision includes at least:

```json
{
  "path": "src/secret.env",
  "included": true,
  "terminal_outcome": "selected",
  "explicit_selection_bases": ["include"],
  "decisive_reason": {
    "provider": "include",
    "pattern": "src/secret.env"
  },
  "matches": [
    {
      "provider": "gitignore",
      "pattern": "*.env",
      "action": "exclude",
      "source": ".gitignore",
      "line": 8
    },
    {
      "provider": "include",
      "pattern": "src/secret.env",
      "action": "include",
      "overrides": ["gitignore"]
    }
  ]
}
```

Absolute paths to private user configuration SHOULD be avoided in portable JSON output. Provider source paths SHOULD be selection-root-relative, repository-relative, or represented by stable symbolic names such as `core.excludesFile`.

### 18.3 Terminal counts

`filter_counts` are exact and non-overlapping. Every candidate contributes to exactly one key:

```json
{
  "output_excluded": 1,
  "protected": 1,
  "hard_excluded": 3,
  "positive_filter_missed": 4,
  "soft_excluded": 11,
  "invalid_object": 0,
  "unreadable": 0,
  "binary_skipped": 1,
  "selected": 43
}
```

The mandatory invariant is:

```text
candidate_count = sum(filter_counts.values())
```

Operational failure normally aborts packing. If a dry-run mode reports invalid or unreadable candidates rather than failing immediately, it MUST still exit nonzero and retain exact terminal counts.

### 18.4 Rule-match counts

`rule_match_counts` are overlapping observations and MUST be separate from terminal counts. Stable keys include:

```text
output
protected
exclude
exclude_extension
include
include_extension
gitignore
ignore_file
default
```

A candidate matching several providers increments each applicable rule-match count but only one terminal count.

### 18.5 Ordering

JSON decisions are sorted by candidate path. Rule matches are ordered by evaluation stage, provider order, CLI order, file order, and pattern line order. Arrays whose semantics are sets MUST still use a documented stable order.

## 19. Determinism and performance

### 19.1 Determinism

For an unchanged filesystem, repository state, environment configuration, CLI invocation, and tool version, selection and diagnostics MUST be byte-for-byte deterministic except for explicitly documented absolute path fields.

The selected set MUST be invariant to:

- filesystem enumeration order;
- hash-map iteration order;
- batching of Git-ignore queries; and
- duplicate source operands.

### 19.2 Performance

The implementation SHOULD:

- discover each directory once per source scope;
- normalize each candidate once;
- compile user patterns once;
- normalize extensions once;
- batch Git queries using NUL-delimited input;
- cache Git decisions per candidate for one pack;
- avoid loading bytes for path-excluded candidates;
- classify each path-selected file once; and
- serialize from already loaded immutable entry data.

Performance optimizations MUST NOT alter explanation completeness or precedence.

## 20. Error handling

### 20.1 Usage errors, exit 2

Examples include:

- incompatible options;
- invalid patterns or extensions;
- source outside root;
- unsafe lexical path operands;
- deletion encountered under `--from-git`;
- unsafe Git inclusion without `--force`; and
- unsupported rule negation on include or exclude options.

### 20.2 I/O errors, exit 4

Examples include:

- missing source or operand;
- unreadable selected file;
- unreadable ignore file;
- Git unavailable or failing when required;
- undecodable Git output;
- selected symlink or non-regular object;
- traversal failure; and
- object mutation detected before read.

### 20.3 Empty result

If filtering produces no final selected entries, pack fails with exit code 4 and a message distinguishing:

- no candidates discovered;
- all candidates excluded by path rules; and
- all path-selected candidates removed by content policy.

Dry-run JSON MUST still emit the complete decision document before returning the documented nonzero status, unless doing so would expose an invalid partial state.

## 21. Backward compatibility

### 21.1 Behavior changes

- `--path` no longer disables Git-ignore processing globally. It defines its own complete candidate union while Git-ignore, DX ignore files, and default soft exclusions remain effective. A positive-filter match or `--only` is required to override a soft exclusion.
- user patterns use Git-wildmatch-compatible semantics rather than ad hoc `fnmatch` prefix behavior;
- extension filters are typed suffix rules;
- default temporary-file exclusions are expanded;
- exact terminal counts replace approximate statistics;
- symlink behavior is explicit and consistent;
- positional output remains deprecated in favor of `--output`; and
- contradictory write options remain usage errors.

### 21.2 Warnings

Deprecation warnings go to stderr and MUST NOT corrupt JSON stdout. A warning MUST identify the deprecated form and its replacement. Behavior removals targeted for v3 MUST be documented with tests that assert warning text and output channel.

## 22. Implementation architecture

A recommended module structure is:

```text
pack_command
  -> PackOptions.validate
  -> SelectionContext.build
  -> CandidateDiscovery.discover
       -> WalkSource
       -> PathSource
       -> GitStatusSource
       -> OnlySource
  -> CandidateNormalizer.normalize_and_deduplicate
  -> RuleSet.build
       -> OutputProtection
       -> ProtectedRules
       -> UserHardRules
       -> PositiveRules
       -> GitIgnoreProvider
       -> DxIgnoreFileProvider
       -> DefaultRules
  -> SelectionEvaluator.evaluate_all
  -> FileLoader.load_selected
  -> ContentPolicy.evaluate
  -> SelectionReport.build
  -> CarrierWriter.write
```

The legacy `collect_paths` function MUST be removed or reduced to a compatibility-free adapter that delegates all behavior to the new pipeline. Pack command handling MUST NOT perform inline filtering.

Each provider MUST expose a stable identity and structured rule metadata. The evaluator, not individual providers, owns cross-provider precedence.

## 23. Testing strategy

### 23.1 Unit tests

Unit tests MUST cover:

- root derivation and containment;
- candidate identity with nested source and root;
- path normalization and duplicate collapse;
- every wildmatch construct;
- invalid pattern handling;
- directory ancestry matching;
- extension normalization and compound suffixes;
- protected and output rules;
- hard-exclude precedence;
- positive-filter union behavior;
- every explicit-selection basis;
- ordered soft-provider resolution;
- exact terminal counts;
- stable decision ordering;
- content classification; and
- JSON schema fields and reason codes.

### 23.2 Git integration tests

Temporary real repositories MUST cover:

- root and nested `.gitignore` files;
- deeper-file precedence;
- negation;
- ignored directories;
- tracked files matching ignore patterns;
- `.git/info/exclude`;
- an isolated `core.excludesFile` configuration;
- worktrees where `.git` is a file;
- submodule boundaries;
- repository root distinct from selection root;
- Git command failure;
- `--from-git` additions, modifications, type changes, renames, copies, deletions, and untracked files;
- ignored untracked files absent from `--from-git`; and
- NUL-safe paths supported by the platform and Git.

Tests MUST isolate global Git configuration and environment so results do not depend on the developer machine.

### 23.3 Golden tests

Golden fixtures MUST cover complete human and JSON output for:

1. default walk with Git ignore;
2. `--path` restricting candidate scope while preserving Git-ignore exclusion;
3. include overriding a soft Git exclusion;
4. hard exclude overriding include and path;
5. include and include-extension union;
6. compound extensions;
7. defaults and their disable flags;
8. protected `.git` behavior;
9. unsafe Git inclusion requiring force;
10. output self-exclusion;
11. source nested below root;
12. `--only` isolation;
13. symlink handling;
14. binary skipping;
15. empty result categories;
16. exact filter counts; and
17. deterministic ordering.

### 23.4 Property tests

Property tests MUST assert:

- adding a hard-exclude rule never increases selection;
- after a positive-filter set exists, adding another positive filter never decreases selection;
- adding the first positive filter can remove nonmatching candidates and can select matching candidates previously blocked only by soft rules;
- explicit selection never defeats protected or hard rules;
- disabling a soft provider never reduces selection;
- duplicate source operands do not duplicate entries;
- candidate iteration order does not affect decisions;
- every candidate has exactly one terminal outcome;
- terminal counts sum to candidate count;
- selected paths are unique and sorted; and
- evaluation is idempotent for the same immutable context and candidates.

### 23.5 Differential matcher tests

The user-pattern matcher MUST be tested against a pinned Git executable as an oracle over a broad generated corpus of paths and supported patterns. Any deliberate difference from Git semantics MUST be documented as a DX extension with explicit tests.

### 23.6 Security tests

Security-oriented tests MUST cover:

- lexical and resolved root escape;
- symlink escape and retargeting;
- output self-inclusion;
- `.git` files and directories at multiple depths;
- malformed NUL-delimited Git output;
- newline and quote characters in user operands;
- unreadable paths;
- race-like object replacement where testable;
- JSON stdout purity; and
- unsafe Git inclusion gating.

## 24. Acceptance criteria

The implementation is accepted only when:

1. filtering logic is absent from `pack_command` except orchestration;
2. every source and provider has focused tests;
3. the matcher passes its conformance suite;
4. Git integration tests use real isolated repositories;
5. terminal counts are exact and satisfy the sum invariant;
6. all decisions are deterministic under shuffled discovery order;
7. output protection and `.git` protection cannot be bypassed unintentionally;
8. no symlink is serialized;
9. dry-run and real pack use the same selection evaluator;
10. JSON output contains no non-JSON stdout text;
11. compatibility warnings are tested; and
12. all existing carrier parse, apply, inspect, and verification tests remain green.

## 25. Normative examples

### 25.1 Subtree minus cache

```bash
dx.py pack . --path src/ --exclude 'src/cache/'
```

Candidate set: descendants of `src/`.
Result: all eligible descendants except `src/cache/` descendants.

### 25.2 Include overrides Git ignore

```bash
dx.py pack . --include 'config/local.env'
```

Candidate set: default walk.
Positive filter: only `config/local.env` matches.
Explicit selection: the include match.
Result: the file is selected even if Git ignore or defaults soft-exclude it, unless protected or hard-excluded.

### 25.3 Hard exclude wins

```bash
dx.py pack . --exclude 'src/' --include 'src/keep.py'
```

Result: no `src/` descendant is selected.

### 25.4 Include union

```bash
dx.py pack . --include 'src/' --include-extension '.md'
```

Result: candidates matching either the `src/` pattern or the `.md` suffix pass the positive-filter stage.

### 25.5 Git changes

```bash
dx.py pack . --from-git --exclude-extension '.md'
```

Result: non-deleted Git status destination candidates are considered; Markdown suffix matches are hard-excluded.

### 25.6 Isolated selection

```bash
dx.py pack . --only docs/
```

Result: descendants of `docs/` are selected without Git, default, include, or exclude rules. Safety, symlink, output, and content policies remain active.

### 25.7 Unsafe Git inclusion

```bash
dx.py pack . --only .git/config --unsafe-include-git --force
```

Result: the `.git` protected rule is disabled for this invocation. All remaining containment, regular-file, output, and content policies still apply.

## 26. Final invariants

The completed implementation MUST preserve these invariants:

1. One absolute selection root defines every candidate identity.
2. Source providers create candidates; include patterns never create candidates.
3. Candidate identity is independent of discovery scope.
4. Output protection is non-overridable.
5. `.git` is protected unless both unsafe inclusion and force are explicit.
6. Hard excludes always win.
7. Positive filters restrict the candidate set when present.
8. Explicit selection overrides only soft exclusions.
9. Git ignore is effective, hierarchical, and fail-closed when required.
10. Directory operands expand to descendant files and never become carrier entries.
11. Symlinks are never serialized.
12. Extension rules are case-insensitive basename suffix rules.
13. Content policy is orthogonal to path selection.
14. Every candidate has one terminal outcome and a deterministic trace.
15. Terminal counts are exact, non-overlapping, and sum to candidate count.
16. Final selected paths are unique and sorted.
17. Dry-run and real pack share the exact same evaluator.
18. No optimization changes selection, precedence, or explanation.

## 27. Collab DX v2 repository baseline

This specification is an implementation specification for the Collab repository represented by the authoritative `collab.dx.txt` DX v2.0.0 carrier. It is not a greenfield CLI design. Every change MUST preserve Collab's existing DX v2 codec, command, compatibility, test, and workflow contracts except where this specification explicitly changes pack selection behavior.

### 27.1 Authoritative implementation surface

The filtering implementation is owned by `dx.py`. In the v2 baseline:

- `match_pattern` performs ad hoc path and ancestor matching using `fnmatch.fnmatchcase`;
- `normalize_extension`, `matches_compound_extension`, and `extension_selected` implement case-insensitive suffix selection;
- `git_changed_paths` supplies `--from-git` candidates;
- `git_repo_root`, `git_allowed_paths`, and `apply_gitignore_filter` implement current Git integration;
- `DEFAULT_EXCLUDES` contains `.git`, `.DS_Store`, and `Thumbs.db`;
- `collect_paths` combines discovery, protection, includes, excludes, Git ignore, defaults, extension filtering, and approximate statistics;
- `pack_command` calls `collect_paths`, maps names back to filesystem objects, loads bytes, applies binary policy, emits dry-run diagnostics, and writes DX v2 carriers; and
- `build_parser` defines the currently shipped pack options and aliases.

The implementation MUST replace this filtering internals without changing the DX v2 serialization contract unless a separate format change is accepted.

### 27.2 DX v2 codec boundary

Selection changes MUST remain behind the carrier-entry boundary. They MUST NOT alter:

- `VERSION = "v2.0.0"` or `DX_FORMAT = "v2.0"` solely to deliver filtering;
- `Entry` semantics;
- UTF-8 text versus base64 binary classification;
- `escaped="true"` handling for text payload directive lines;
- `trailing_newlines` preservation;
- `readonly="true"` carrier metadata;
- `%%DX`, `%%FILE`, `%%ENDBLOCK`, and `%%END` framing;
- duplicate carrier-path rejection;
- supported `v1.3.1` and `v2.0.0` parsing compatibility;
- atomic output writing;
- unpack, apply, inspect, compare, and verify behavior; or
- the existing exit-code taxonomy.

Filtering produces an ordered sequence of selected `(path, bytes, classification, readonly)` inputs. Existing DX v2 encoding remains the sole owner of carrier formatting.

### 27.3 Collab compatibility entry point

`collab-dx-pack.py` is a supported compatibility entry point. It imports `dx` and invokes `dx.main(["pack", *sys.argv[1:]])`. Therefore:

- every new pack option MUST work through both `dx.py pack` and `collab-dx-pack.py`;
- historical `--out` behavior accepted by the Collab wrapper MUST remain supported or receive an explicit, tested migration path;
- the wrapper MUST contain no independent filtering logic;
- error codes and stdout/stderr behavior MUST be equivalent between entry points after accounting for program-name text; and
- duplicate `pack` tolerance in `dx.main` MUST remain unaffected.

No filtering feature is complete until compatibility-entry-point tests pass.

### 27.4 Existing v2 behavioral constraints

The new pipeline MUST preserve these current Collab behaviors unless this specification explicitly supersedes them:

- `--path` and `--from-git` are mutually exclusive;
- Git deletions fail closed because DX carriers cannot represent deletion;
- rename and copy records contribute destination paths;
- output may be stdout;
- an output file under a symlinked parent directory is supported while replacing an output-file symlink is rejected;
- ordinary recursive walks do not follow directory symlinks;
- selected filesystem symlinks are not packed;
- binary content is included losslessly by default and may be skipped explicitly;
- output paths are written atomically;
- no selected entries is an error;
- JSON dry-run output is machine-readable stdout;
- normal diagnostics use stderr; and
- quiet and verbose remain mutually exclusive.

### 27.5 Existing test surfaces

Implementation work MUST update and preserve the relevant tests already carried by Collab:

- `tests/test_dx_cli_v2_acceptance.py` for pack CLI, dry-run, filtering counts, root mapping, Git behavior, binary handling, symlink safety, and exit codes;
- `tests/test_dx_cli_compatibility.py` for the historical wrapper, duplicate command tolerance, parse-error handling, and symlinked output parents;
- `tests/test_dx_codec.py` and `tests/collab-dx-codec-tests.sh` for carrier-format stability;
- `tests/collab-dx-content-policy-tests.sh` for BOM, LF, empty files, deletion rejection, path representability, and Git deletion behavior;
- `tests/collab-hardening-tests.sh` for spaces, newline preservation, binary handling, and security regressions;
- `tests/run-tests.sh` as the repository-level test entry point; and
- any repository verification scripts that invoke the compatibility packer.

New focused filtering tests MAY be added, but they do not replace these regression suites.

## 28. Collab v2 implementation plan

### 28.1 Refactoring boundary

The implementation MUST introduce the new pipeline inside `dx.py` or imported Collab modules while preserving the current public command handlers. The target dependency flow is:

```text
build_parser
  -> pack_command
       -> PackOptions validation
       -> SelectionContext
       -> CandidateDiscovery
       -> RuleSet
       -> SelectionEvaluator
       -> File loading and content policy
       -> existing encode_entry and write_atomic
```

`pack_command` remains the public handler but becomes orchestration only. `collect_paths` MUST be removed after all callers migrate. `match_pattern` MUST be replaced by the conformant matcher rather than retained as a second interpretation path.

### 28.2 Required typed objects

The v2 implementation MUST introduce explicit internal records for at least:

```text
SourceProvenance
Candidate
PatternRule
ExtensionRule
RuleMatch
PathDecision
ContentDecision
SelectionReport
```

These records MAY remain in `dx.py` for v2.1 if module extraction would create unnecessary repository churn. Regardless of location, they MUST be independently testable and MUST NOT depend on argparse namespaces.

### 28.3 Option normalization

Argparse output MUST be converted once into normalized immutable pack options. Normalization includes:

- resolved source, root, and output intent;
- normalized repeated path operands;
- compiled include and exclude patterns;
- normalized include and exclude extensions;
- derived `--no-ignore` flags;
- validated source mode;
- validated unsafe Git inclusion gate;
- diagnostic mode; and
- binary and readonly policy.

Downstream components MUST NOT read raw argparse fields or repeat option validation.

### 28.4 Candidate-to-file mapping

The current conditional join in `pack_command` MUST be eliminated. Every `Candidate` MUST carry or deterministically derive its absolute access path from the selection root. File loading MUST use that mapping for all source modes. This prevents `SOURCE`, `--root`, `--path`, and `--from-git` from interpreting the same relative name against different directories.

### 28.5 Git command abstraction

Git subprocess execution MUST use one checked abstraction that:

- records the invoked operation for diagnostics without leaking sensitive environment values;
- accepts an explicit working directory;
- supports binary NUL-delimited input and output;
- distinguishes Git-not-installed, not-a-repository, and command-failure outcomes;
- uses an isolated environment in tests;
- never decodes path records with replacement characters; and
- prevents individual providers from implementing inconsistent subprocess error handling.

### 28.6 Statistics migration

The current `stats` dictionary returned by `collect_paths` is replaced by `SelectionReport`. Existing human dry-run labels MAY remain during v2.1 compatibility, but their values MUST be derived from exact terminal outcomes. New JSON fields use the schema in section 18.

For one compatibility release, JSON MAY include legacy keys alongside schema-version-2 fields when all of the following hold:

- legacy keys retain their documented meanings;
- exact values replace approximations;
- the schema clearly distinguishes legacy summaries from terminal counts; and
- golden tests cover both representations.

Approximate counts and deliberately hard-coded zero counts are forbidden.

### 28.7 Help and command surface

`build_parser`, command-specific help, and `TOP_HELP` MUST be updated together. Every added option MUST specify:

- whether it is repeatable;
- whether its value is root-relative;
- its precedence class;
- incompatible options;
- whether it affects candidate discovery or only rules; and
- its behavior through `collab-dx-pack.py`.

Short options already used by Collab MUST NOT be reassigned.

## 29. Collab v2 migration matrix

The existing Collab behavior migrates as follows:

```text
Current: --path suppresses Git-ignore processing for the complete operation.
Target:  --path defines the complete candidate union without creating
         explicit-selection strength. Soft-rule providers remain effective
         unless a positive filter explicitly selects a candidate.

Current: fnmatch plus ancestor-prefix matching approximates pattern behavior.
Target:  one Git-wildmatch-compatible matcher with differential tests.

Current: .git, .DS_Store, and Thumbs.db are mixed into protected handling.
Target:  .git is protected; removable defaults are a separate soft provider.

Current: include patterns first restrict the set and are checked again to
         re-add Git-ignored candidates.
Target:  one positive-filter stage plus one explicit-selection property.

Current: extension filters run after Git and default filtering.
Target:  exclude extensions are hard rules; include extensions join the
         positive-filter union.

Current: Git ignore is skipped for explicit paths, Git sources, and file SOURCE.
Target:  Git evaluation follows source-specific normative rules and retains a
         trace; explicit selection controls only override behavior.

Current: filter counts overlap conceptually and default counts are approximate.
Target:  exact terminal counts plus separate overlapping rule-match counts.

Current: pack_command reconstructs the target path with source-mode conditions.
Target:  candidates own an unambiguous root-relative identity and access path.
```

## 30. Collab v2 test additions

Beyond the generic requirements in section 23, the Collab repository MUST add the following concrete tests.

### 30.1 CLI parity tests

For every new or changed filtering option, execute equivalent invocations through:

```text
python3 dx.py pack ...
python3 collab-dx-pack.py ...
```

Assert equivalent exit status, selected carrier entries, dry-run JSON, and error classification.

### 30.2 Codec non-regression tests

Create carriers from an identical selected entry set before and after pipeline refactoring and assert identical bytes when no intentional header or ordering change applies. At minimum cover:

- UTF-8 text;
- text containing a physical line beginning with `%%`;
- empty text;
- multiple trailing newlines;
- CRLF classified as binary;
- UTF-8 BOM classified as binary;
- arbitrary binary bytes;
- readonly metadata; and
- deterministic entry ordering.

### 30.3 Root and source regression tests

Add explicit cases for:

```text
pack nested/source --root root
pack file.txt --root root
pack root --path nested/source
pack root --path nested/source --include nested/source/a.py
pack root --from-git
```

Every carrier path MUST be relative to `root`, and every loaded object MUST resolve to the corresponding candidate.

### 30.4 Current-bug characterization tests

Before replacing the implementation, tests MUST characterize and then update these known baseline behaviors:

- Git ignore bypass caused by any non-empty `--path` list;
- include-directory and exclude-subdirectory composition;
- hard exclude versus include precedence;
- root-level extension matches;
- compound extension matches;
- nested `.gitignore` behavior;
- default count reporting; and
- output-file self-selection when output lies under the source tree.

Each changed expectation MUST cite the normative section that authorizes it.

### 30.5 Repository test command

The implementation gate MUST execute the repository's complete test entry point, not only new focused tests. Focused tests MAY run first for fast feedback. Final acceptance requires the complete Collab suite.

## 31. Collab v2 delivery requirements

The implementation delivery MUST include:

1. the specification file from this carrier;
2. production changes to `dx.py` and, only if required, reusable modules under `collab/`;
3. parser and help updates;
4. compatibility-wrapper validation without duplicated filtering logic;
5. focused unit, Git integration, property, differential, security, and golden tests;
6. updates to existing Collab v2 acceptance and compatibility tests;
7. exact dry-run and explanation fixtures;
8. repository-wide test evidence;
9. a compatibility note describing deliberate CLI behavior changes; and
10. no unrelated changes to audit artifacts or other repository workflows.

A correction carrier for this work MUST contain only new and changed files, use DX v1.3.1 framing with exact four-space text payload indentation, and be reparsed before delivery.
