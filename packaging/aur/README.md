# AUR package: leafsmith-bin

The AUR package installs the contents of the published Linux AppImage under
`/opt/leafsmith`, with a `/usr/bin/leafsmith` launcher, desktop entry, icon
and license files. It runs the extracted `AppRun`, so FUSE is not needed. The
`-bin` suffix marks a package of release binaries.

**Waiting for the rename.** The app is being renamed from Paperwork to
Leafsmith, and only releases built under the new name are packaged. Until the
first one exists, runs on `main` end with a notice and publish nothing. That
release must have this layout, matching `_appname`, `_product` and `_worker` in
`PKGBUILD.in` and the constants at the top of `scripts/aur_package.py`:

- asset `Leafsmith_<version>_amd64.AppImage` (Tauri `productName` `Leafsmith`);
- `usr/bin/leafsmith`, with `StartupWMClass` `leafsmith`, and the icon
  `usr/share/icons/hicolor/512x512/apps/leafsmith.png`;
- the frozen worker `usr/lib/Leafsmith/worker/leafsmith-worker`, with
  `third-party-licenses/application-MIT.txt` beside it.

If the GitHub repository is renamed, update `REPOSITORY` in the script and
`url` in the template.

AUR receives only the recipe: `PKGBUILD`, `.SRCINFO`, `leafsmith.sh` and
`leafsmith.desktop`. `makepkg` downloads the AppImage from the GitHub release
and checks its SHA-256. The recipe is generated from `PKGBUILD.in` by
`scripts/aur_package.py`. Change the template here: edits made only on AUR are
replaced by the next publish.

## When it publishes

The `AUR package` workflow runs:

- after a successful `Desktop packages` tag run, for that tag. That workflow
  publishes releases with `GITHUB_TOKEN`, which emits no `release` event;
- when `main` receives changes to these packaging files, for the newest
  release with a Leafsmith AppImage;
- from the Actions tab (**Run workflow** on `main`), for a chosen tag or the
  newest release, for example after publishing a release by hand. Clear
  **Push to AUR** to validate only. Runs from other branches validate only;
- on pull requests that change these files: validation only, nothing is pushed.

Pre-releases are included: `v0.1.0-rc.2` becomes `pkgver=0.1.0rc2`, which
pacman orders before `0.1.0`. A new release resets `pkgrel` to 1. A recipe
change for the same release publishes the next `pkgrel`. A release older than
the one on AUR is still built and checked but not pushed, and nothing is pushed
when AUR already matches.

## What a run checks

1. **Pin** (`fetch-release`): exactly one `.AppImage` asset whose version
   matches the tag, listed in `SHA256SUMS-linux-x86_64.txt`, and agreeing with
   GitHub's recorded asset digest.
2. **Plan**, in a disposable `archlinux:base-devel` container with no
   credentials: the unit tests, including pacman's real `vercmp` and
   `makepkg --printsrcinfo`, then rendering and comparing with AUR's current
   `master`. The runner copies the plan out of the container's mount before
   the build starts, and only that copy can be published.
3. **Build and check**, in a second container, also without credentials:
   - `bash -n`, `shellcheck`, `desktop-file-validate`, and `.SRCINFO` regenerated
     and compared;
   - `makepkg --verifysource`, then a build as an unprivileged user;
   - `pacman -U` with repository dependencies, then `pacman -Qkk`;
   - `namcap` on the PKGBUILD and package;
   - the release workflow's headless checks on the installed launcher under
     Xvfb: `--worker-self-test` and the packaged-operation checks.

   namcap errors fail the run unless `namcap_errors` in
   `scripts/aur_package.py` accepts them:
   - the reviewed patterns in `REVIEWED_NAMCAP_ERRORS`, each with its reason;
   - dependency reports where every needing file is inside the bundle and every
     library is one the package ships. These include the frozen worker's
     Python sources, which run on the worker's own interpreter.

   A library the bundle does not ship must be in `depends`.
4. **Push** (`publish` job, `aur` environment, `main` only): only this job
   receives the SSH key. It checks the files against the validated plan's
   SHA-256 list, then commits and pushes, never with force. If AUR changed
   after validation, it does nothing when AUR already holds the same files and
   fails otherwise. A re-run then plans against the new state.

Not tested: interactive desktop use on Arch, and other AUR helpers' build
environments.

## One-time setup

AUR accepts pushes only over SSH. The key must be registered to the AUR
account that will own the package. It is used only by GitHub Actions; the
development machine needs no SSH configuration. Do this before merging the
workflow to `main`: that push runs it and publishes the newest release.

1. Create a dedicated key without a passphrase in a private temporary
   directory:

   ```sh
   dir=$(mktemp -d) && ssh-keygen -t ed25519 -N '' -C 'leafsmith-bin AUR CI' -f "$dir/aur"
   cat "$dir/aur.pub"
   ```

2. On <https://aur.archlinux.org>, open **My Account**. Add the `aur.pub` line
   to **SSH Public Key** on a new line, keeping any existing keys. Enter your
   password and choose **Update**.
3. Create the `aur` environment and limit it to `main`. This step is
   required: otherwise a workflow edited on any branch could use the key.
   Then store the private key as its secret and delete the local copy:

   ```sh
   repo=repos/ClawPick2026/paperwork-desktop
   printf '%s' '{"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}' |
     gh api -X PUT "$repo/environments/aur" --input -
   gh api -X POST "$repo/environments/aur/deployment-branch-policies" -f name=main -f type=branch
   gh secret set AUR_SSH_PRIVATE_KEY --env aur --repo ClawPick2026/paperwork-desktop < "$dir/aur"
   rm -r "$dir"
   ```

4. Set the PKGBUILD maintainer line and AUR commit author. This text is
   public on AUR; an obfuscated address such as `name at example dot org` is
   fine:

   ```sh
   gh variable set AUR_MAINTAINER --repo ClawPick2026/paperwork-desktop --body 'Your Name <you at example dot org>'
   ```

5. Optional: under **Settings → Environments → aur**, require a reviewer
   before each push.

The AUR host keys are pinned in `known_hosts`. Their fingerprints were checked
against the ones published on the AUR home page.

To replace the key, register the new public key on AUR first, then rerun step 3.

Current key, created on 2026-10-19 and registered on AUR (steps 1 to 4 are done;
`AUR_MAINTAINER` is `Firstpick <firstpick1992@proton.me>`):
`ED25519 SHA256:XPgMB6a9YYGtdIaYlxzMS17hJnfJ6c5S6urwnV8eI+4`, comment
`ClawPick2026/paperwork-desktop GitHub Actions AUR publishing`.

## Local checks

`python -m pytest scripts/tests/test_aur_package.py` runs anywhere with git and
bash. The `vercmp` and `makepkg` tests are skipped outside Arch. Full package
builds run in CI only (`packaging/aur/ci-validate.sh` refuses to run outside
the CI container).
