# Releasing a new version

Everything here is done from the project folder. Nothing is automatic until you
push a tag — pushing a branch only builds, it never releases.

## Where the version lives

One line, in `soundxr_bridge/__init__.py`:

```python
__version__ = "1.0.0"
```

`pyproject.toml` reads it through setuptools' dynamic version and
`packaging/soundxr_bridge.spec` imports it, so the app header, the Python
package and the macOS bundle version all follow automatically. **Do not type a
version number anywhere else.** If you find one, it is a bug.

Use the script rather than editing by hand — it validates the number and is the
same one CI runs:

```bash
python tools/set_version.py            # what is it now?
python tools/set_version.py 1.1.0      # set it (a leading "v" is stripped)
python tools/set_version.py --check 1.1.0
```

## Picking the number

`MAJOR.MINOR.PATCH`, and for this app that means:

| Part | Bump it when |
|---|---|
| PATCH `1.0.→1` | a fix, nothing new to learn: a wrong address in the catalogue, a crash |
| MINOR `1.→1.0` | something new that does not break existing shows: a curve, a target, a button |
| MAJOR `→2.0.0` | old presets stop loading, or the interface is rearranged enough to retrain on |

Never reuse a number that has been published, and never go backwards — the
Releases page sorts by what you tell it.

## The release itself

```bash
python tools/set_version.py 1.1.0
python -m pytest tests -q                    # must be green before you tag
git add -A
git commit -m "Release 1.1.0"
git push origin develop                      # run 1: builds, no release
#   wait for the run to go green in the Actions tab
git tag 1.1.0
git push origin 1.1.0                        # run 2: builds again, then releases
```

Then look at the repository's **Releases** page: `1.1.0` with four files
attached — Windows `.zip`, macOS arm64, macOS Intel, Linux `.zip`.

In SourceTree, tags are **not** pushed with the branch: tick *Push tags* in the
push dialog, or the second run never starts.

## What CI does

`.github/workflows/build.yml`, four jobs (Windows, macOS arm64, macOS Intel,
Linux). Each one installs the dependencies, runs the test suite, builds with
PyInstaller and runs `packaging/smoke_test.py` — which starts the packaged
binary and pushes a real OSC message through it.

- **push to `master`, `main` or `develop`** → builds, uploads artifacts to the
  run page (they expire after 90 days). No release.
- **push of a tag** like `1.1.0` or `v1.1.0` → the same builds, then the
  `release` job attaches them to a permanent Releases entry.

On a tag push CI also runs `tools/set_version.py <tag>` before building, so the
binaries always report the tag they came from. That stamps the build only, not
the repository — which is why step one above is still setting the version by
hand.

## When it goes wrong

| Symptom | Cause and fix |
|---|---|
| Tag pushed, no run started at all | The tag name does not match the `tags:` filter at the top of `build.yml`. It accepts `v1.1.0` and `1.1.0`, nothing else. |
| Run went green, but no release appeared | The `release` job needs **all four** builds to succeed — one failed or cancelled job (a stalled macOS Intel runner, say) skips it. Re-run the failed job from the Actions page. |
| Release used the wrong workflow | GitHub runs `build.yml` **as it exists at the tagged commit**, not the newest one on the branch. Tag a commit that already contains your workflow changes. |
| Re-pushing the tag does nothing | A tag that already exists on GitHub cannot re-fire. Delete it locally and remotely (`git tag -d 1.1.0 && git push origin :refs/tags/1.1.0`) and push it again, or — cleaner — move to the next number. |
| Pushing `build.yml` is rejected | Editing a workflow file needs a token with the `workflow` scope. Either use the classic PAT set up in SourceTree, or edit the file directly on github.com, which needs no token, then pull. |
| macOS release is a `.zip`, not a `.dmg` | The signing secrets are not set, so the job shipped an unsigned app — it still runs, via right-click → Open. See [SIGNING.md](SIGNING.md). |

## Undoing a release

Delete the release from the Releases page **and** delete its tag (deleting only
the tag leaves the release behind as a draft). Then fix, and go out under the
next number rather than reusing the old one — anyone who already downloaded the
first one will never know it changed.
