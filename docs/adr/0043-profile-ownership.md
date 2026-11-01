# ADR-0043: Profiles an app's team can write merge after the platform's

**Status:** Accepted

## Decision

The loader tells apart who can write a profile, and uses that to order layers and to find profiles:

- **A profile is app-owned** when the app's team can write it: it is in `.harness/profiles` next to the app spec, or it is a file named by the app spec or by another app-owned profile. Everything else belongs to the platform: a directory given by `--profile-dir`, `profile_dirs=` or `HARNESSWEAVER_PROFILE_PATH`, a plugin's profile, and a file a platform profile names.
- **App-owned profiles merge after the platform's**, whatever order `extends` lists them in. The order is built-in profiles, platform profiles, app-owned profiles, the app spec, the overlay.
- **The first directory that holds any file for a name owns that name.** `org://acme-baseline@^1` picks the highest matching version in that directory, and versions are never compared across directories. If none matches, the reference fails to resolve; it does not fall through to a later directory.
- **Profiles are the same profile when they are the same file.** Duplicates and cycles are found by resolved file, not by the text of the reference. A file that both the app and the platform name counts as the platform's.

App-owned profiles keep the `org` layer kind, so they may still declare locks and bounds, and the `baseline` band.

The same review of the baseline's guarantees made these load errors:

- A lock with a wildcard is enforced: `guardrails.input[*]` covers every item of that list and `tasks.*.budget` every task's budget. They also stop later layers adding items or tasks there. Exact ids remain the way to lock only the baseline's own items.
- `null` at a path a bound gives a maximum removes the limit, so it is a `BoundViolation`. A null the framework defaults left in place removes nothing and is allowed. A null on a task budget leaves the per-run limit in force, and is allowed too.
- An enabled guard declared `where: sidecar` that a lock covers needs a lock covering `sidecar.url`.
- A baseline-band guard that fails open is refused on its own, whether or not it is in a parallel group.
- A layer can't use the merger's temporary `~auto` ids, or a key named `__proto__`.

## Why

A layer's locks bind only the layers after it (ADR-0018), and a keyed-list item merges into whatever is already there. So a file listed before the baseline could put `enabled: false` into a guard the baseline then locked, because the baseline's item didn't state `enabled`. The load succeeded and the lock was still listed. Likewise, one version number decided between directories, so a copy of the baseline in the app's own `.harness/profiles` with a higher version replaced the platform's and removed all of its locks. Neither needed anything but files in the app's repository, which is exactly the principal R1 constrains.

Ordering by owner fixes the first without changing what a lock means. Making locks retroactive would not work: a platform child profile may rightly lock a value its parent set. Tying a name to its first directory fixes the second, and gives up only one layout: a platform splitting versions of one name across path directories must keep them together.

The kind stays `org` because ownership only decides order. A new kind would have changed the wire-visible layer kinds and every band table for no gain, and the tutorial's single-team layout, a baseline in `.harness/profiles`, keeps working as it did.

## Consequences

- This protects a baseline an app reaches through the platform's channels. A baseline in the app's own repository, or one the app names by file path, has no boundary to protect: its team can edit it. Distribute baselines on the profile path or in a plugin, and reference them as `org://` or `profile://`.
- It doesn't make a baseline mandatory. An app can still drop its `extends` entry, which `require_level` can't catch, since that comes from the same profile. Reviewing that line, with `spec diff`, stays necessary.
- App-owned profiles keep the `baseline` band, so a `fail_mode: open` middleware there still fails loading. They run inside the platform's baseline middleware, since they merge later.
- Baselines that lock a `where: sidecar` guard without locking `sidecar.url` now fail loading. TypeScript's `options.sidecar` takes the place of `sidecar.url`, and isn't covered: it is app code, which already runs with the app's authority.
