# Supply chain

What this project depends on, and which of those dependencies carry risk worth naming.

Scope note: nothing here ships. Every dependency below exists only to build and test the
firmware, and everything except the ARM toolchain runs solely inside the CI job — which
holds a read-only token and no secrets. A compromise of any of them gets an attacker code
execution in a throwaway runner, not access to anything. That bounds the severity of
everything on this page and is stated up front rather than left to be inferred.

Figures gathered 2026-08-12 from the GitHub API.

## High-risk dependencies

| Dependency | Risk factors | Notes | Alternative |
|---|---|---|---|
| **Renode** (`renode/renode`) | high-risk features, no security contact | ~2.7k stars, Antmicro-backed, actively developed. It emulates guest binaries and executes IronPython from platform descriptions — third-party code execution is what it is *for*. No `SECURITY.md`. | None. It is the project's reason for existing, and the archive is pinned by SHA-256 (see below). |
| **telnetlib3** (`jquast/telnetlib3`) | single maintainer, low popularity, no security contact | ~173 stars, 14 contributors, personal account. Pulled in by Renode's test requirements; this project never imports it. | Not ours to swap — it arrives through Renode. Version is now pinned exactly. |
| **robotframework-retryfailed** (`MarketSquare/…`) | low popularity, stale | ~19 stars, last push 2025-12-02. Community org rather than a single person, which softens it. | Not ours to swap; arrives through Renode's requirements. |
| **PyYAML** (`yaml/pyyaml`) | high-risk features, past CVEs | ~2.9k stars, organisation-owned. Deserialisation is its whole job and it has a history of unsafe-load CVEs. Nothing here calls it directly. | None warranted; the safe API is what its consumers use. |
| **psutil** (`giampaolo/psutil`) | single maintainer | ~11.3k stars, 100+ contributors, `SECURITY.md` present, actively maintained by a long-standing, publicly identifiable maintainer. Listed for completeness rather than concern. | None. |

The four GitHub Actions (`checkout`, `setup-python`, `cache`, `upload-artifact`) are
GitHub-owned, actively maintained, and pinned to commit SHAs rather than tags. `gcc-arm-none-eabi`
comes from the Ubuntu archive and is distribution-signed. None met a risk criterion.

## Counts by risk factor

| Risk factor | Count |
|---|---|
| Single maintainer | 2 |
| Unmaintained or stale | 1 |
| Low popularity | 2 |
| High-risk features | 2 |
| Past CVEs | 1 |
| No security contact | 3 |

## Controls already in place

- **The Renode archive is verified before it is unpacked**, against the SHA-256 digest the
  GitHub release publishes. The check is unconditional: CI caches the archive rather than
  the unpacked tree, precisely so that a cache hit cannot skip verification. It used to, and
  was skipped on five consecutive runs.
- **Actions are pinned to commit SHAs**, so a moved tag cannot change what runs.
- **The workflow declares `permissions: contents: read`** rather than relying on a repository
  setting someone can change from a web page.
- **A CI step fails the build if anything modifies tracked files after checkout**, which is
  what would catch a dependency writing into the working tree.

## Recommendations

1. **Done:** close the two version ranges in Renode's requirements (`pyyaml==6.0.*`,
   `telnetlib3==2.0.*`) with [`ci/constraints.txt`](../ci/constraints.txt). A range installs
   whatever patch release exists on the day CI runs, including one published after a
   maintainer account is compromised.
2. **Not done — worth doing if this ever guards anything valuable:** install with
   `--require-hashes` against a generated lock file. That closes the remaining gap, which is
   that a pinned *version* can still be re-published or served differently. It costs a
   regeneration step whenever Renode's requirements change, which is why it is recorded here
   rather than adopted now.
3. **Not done:** ask Antmicro to publish a `SECURITY.md`. Nothing this project can fix
   unilaterally, but it is the reason a vulnerability reporter has nowhere obvious to go.

## Method

Produced with the `supply-chain-risk-auditor` skill, with one deviation: the skill writes its
report into a hidden `.supply-chain-risk-auditor/` workspace directory, and this lives in
`docs/` instead. A dependency audit is something a reader of this repository should be able
to find, not tool exhaust.
