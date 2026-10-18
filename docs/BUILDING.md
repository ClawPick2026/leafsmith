# Build and smoke-test desktop packages

The `Desktop packages` workflow builds **Windows x86_64 NSIS** on
`windows-latest` and **Linux x86_64 AppImage** on `ubuntu-22.04`. Pushes to
`main` and manual dispatches upload Actions artifacts only. Pushing a `v*` tag
runs the same build and then publishes a GitHub release; see
[Publish a release](#publish-a-release).

## Start CI after the coordinator has committed/pushed these files

A workflow cannot execute uncommitted local source. Once `build.yml` is present
on GitHub's default branch, either its `push` run starts automatically or run:

```sh
gh workflow run build.yml --repo ClawPick2026/leafsmith --ref main
gh run list --repo ClawPick2026/leafsmith --workflow build.yml --limit 5
# Use the actual run ID returned above; wait and preserve its exit status.
gh run watch RUN_ID --repo ClawPick2026/leafsmith --exit-status
gh run view RUN_ID --repo ClawPick2026/leafsmith --log-failed
gh run download RUN_ID --repo ClawPick2026/leafsmith --dir artifacts/ci-RUN_ID
```

For a non-main ref, dispatch it explicitly after the workflow has first reached
the default branch. Check the run's commit SHA against the intended source.
Never infer installer success from the separate native-security workflow.

## What CI exercises

1. Python 3.12 x64, Node 24, stable Rust, and explicit native x86_64 Rust targets.
2. Linux GTK 3 / WebKitGTK **4.1** headers, AppIndicator, XDo, OpenSSL, SVG,
   binutils, patchelf, and Xvfb dependencies installed on the hosted runner.
3. `npm ci`, frontend tests/build, and native-security crate tests.
4. Binary-wheel-only core Python dependencies from
   `worker/runtime-requirements.txt`; pinned PyInstaller and pytest build tools.
   No optional engine binaries, AI model downloads, or cloud jobs are included.
5. Worker and packaging tests. Two test fixtures launch POSIX shebang scripts
   (`test_office_engine_receives_locked_down_job_profile` and
   `test_subprocess_timeout_sanitized`); Linux runs both, Windows explicitly
   deselects them and records that scope. Real optional engine tests can skip
   when their configured engine is absent; the JUnit/test logs retain skips.
6. PyInstaller **onedir** output, then native Tauri crate tests with resources
   available and frozen-worker smoke. Linux also builds the release executable
   **before** collecting its native dependency closure, notices and exact sources.
7. Tauri `--bundles nsis` / `--bundles appimage`, followed by smoke from the
   resulting package, not a development-source worker. Linux then separately
   extracts the actual AppImage, audits every shared library, and creates and
   reads back a corresponding-source ZIP before allowing artifact upload.

All piped test/build steps use Bash `pipefail`; a successful `tee` cannot hide a
failed process. Evidence artifacts upload even if a preceding step fails.
Standalone package artifacts upload only after build and smoke succeed.

## Runtime layout and no-Python requirement

`python scripts/freeze-worker.py` creates:

```text
build/worker/leafsmith-worker/
  leafsmith-worker[.exe]
  _internal/                    # Python runtime, extension modules, PDFium/data
  third-party-licenses/         # added by license-report.py before Tauri bundling
```

The Tauri resource mapping is exactly
`../build/worker/leafsmith-worker/` -> `worker/`. Keep the **whole directory**,
including `_internal`, not just the worker executable. A regression test checks
that the freezer destination and Tauri mapping agree. Optional components are
installed separately with consent and do not become implicit core requirements.

The freezer invokes the generated binary with Python environment variables
removed and PATH empty on Linux / restricted to System32 on Windows. The actual
worker `health` request imports the PDF engine, creates a fillable PDF using the
real `form_template` operation, and independently reads pages and fields back
with pypdf. Packaging requires `ok: true`, `status: ok`, at least one page, and
at least one field; import-only success and exit-code-only success are rejected.
The embedded interpreter is used; end users need not install Python.

## Package smoke boundaries

```sh
# Run after freezing and collecting notices; use .exe on Windows.
python scripts/smoke-package.py --kind worker \
  --path build/worker/leafsmith-worker/leafsmith-worker --logs build/logs/frozen-smoke

# Substitute the actual package path or a glob matching exactly one file.
python scripts/smoke-package.py --kind nsis \
  --path 'src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/*.exe' \
  --logs build/logs/nsis-smoke
python scripts/smoke-package.py --kind appimage \
  --path 'src-tauri/target/x86_64-unknown-linux-gnu/release/bundle/appimage/*.AppImage' \
  --logs build/logs/appimage-smoke
```

* Windows: silent `/S` installation into a fresh temporary `/D=` directory, then
  execute its `leafsmith.exe --worker-self-test` with captured process
  pipes and checked status. No existing installation or uninstaller is used.
* Linux: `--appimage-extract` (no FUSE requirement), set `APPDIR`, then execute
  `AppRun --worker-self-test`, under Xvfb if available without a display.
* Both: require native JSON to report the actual PDF form roundtrip, then run
  the **packaged resource worker** again without an external Python on PATH and
  verify SHA-256 hashes of all bundled notice resources.

Native self-test resource lookup expects Windows `worker/leafsmith-worker.exe`
next to the app, or Linux `usr/lib/Leafsmith/worker/leafsmith-worker` in
the AppImage. An unexpected layout fails explicitly; it is not papered over by
running a worker from the source checkout.

These checks are **noninteractive packaging smoke**, not proof of interactive
Windows/Linux desktop operation, a full interactive OS install, WebView setup
on a clean Windows machine, SmartScreen/signing behavior, or optional engine / AI
model quality. Test those separately on the target operating systems before
making release claims. Packages are unsigned unless signing is separately set up.

## Dependency notices

Run `python scripts/license-report.py --require-rust` after freezing and Cargo
dependency resolution, **before** Tauri bundling. It copies actual Python, npm,
and Rust notice/license files, including nested PDFium build notices, npm font
licenses, and vendored Rust-library terms. It includes Python's runtime license,
Pillow, cryptography, ReportLab/Bitstream Vera and PyInstaller's actual
`COPYING.txt` with the bootloader exception. Unused ReportLab DarkGarden and
hb-test font payloads are removed from the runtime, with source-distribution
notices retained for audit. Missing required Python notice distributions stop
the build. Rust crates without separate notice files retain their README terms
where available and declared license metadata; inventories are not legal advice
or a substitute for reviewing upstream obligations.

`application-MIT.txt` applies to Leafsmith code **only**. Third-party components
keep their own terms. Inventories deliberately include build/test tools from the
packaging environment; they do not assert that every installed tool ships in
the runtime. A notice manifest records the exact resource-file SHA-256 values.
Optional engines/models have separate licenses and are not in core installers.

## Linux shared-library gate and corresponding sources

A Python/npm/Rust notice list alone does **not** cover a Linux binary payload.
The Linux CI path additionally runs:

```sh
# After npm build, worker freeze and native tests; requires native Linux toolchain.
# Build the exact release binary once; it is inventoried, then bundled as-is.
npm run tauri -- build --target x86_64-unknown-linux-gnu --no-bundle
python scripts/license-report.py --require-rust \
  --linux-native src-tauri/target/x86_64-unknown-linux-gnu/release/leafsmith \
  --linux-extra-library '/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/*/loaders/*.so' \
  --linux-extra-library '/usr/lib/x86_64-linux-gnu/gtk-3.0/*/immodules/*.so' \
  --linux-extra-library '/usr/lib/x86_64-linux-gnu/gio/modules/*.so' \
  --linux-extra-library '/usr/lib/x86_64-linux-gnu/gtk-3.0/*/printbackends/*.so' \
  --linux-extra-library '/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1/injected-bundle/*.so' \
  --linux-extra-library '/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1/WebKit*Process'
npm run tauri -- bundle --target x86_64-unknown-linux-gnu --bundles appimage
python scripts/audit_linux_libraries.py \
  --appimage 'src-tauri/target/x86_64-unknown-linux-gnu/release/bundle/appimage/*.AppImage' \
  --inventory build/worker/leafsmith-worker/third-party-licenses/linux-libraries.json \
  --sources build/linux-corresponding-sources \
  --source-archive artifacts/Leafsmith-linux-corresponding-sources.zip \
  --logs build/logs/linux-library-audit
```

* **Prebundle inventory:** enumerate actual `*.so` / `*.so.*` files in the frozen
  worker, including extensions and vendored wheel `.libs`. Match against installed
  `importlib.metadata` RECORD filenames and copied distribution notices; ambiguous
  basenames fail. CPython `libpython` and `lib-dynload` originals use the included
  Python runtime license. The worker executable separately requires PyInstaller's
  actual bootloader exception notice.
* Run `ldd` on the release executable, worker, extensions and explicit GTK/GIO
  loader roots. These are trusted build outputs, never user-supplied documents.
  Record the transitive dependency **superset** so notices and sources can be in
  place before bundling. Resolve copied system-library basenames through
  `ldconfig`, PyInstaller's real `COLLECT-00.toc` origin paths, merged-`/usr`
  aliases, and exact `dpkg-query -S` ownership. A known non-Debian origin (for
  example, a custom Python `libcrypto` with a host-matching SONAME) cannot be
  silently reassigned to the host Debian package. Missing collection provenance
  fails. Record binary package/version, source package/version, original path,
  original hash and actual staged hash. Unresolved dependencies and unmapped or
  ambiguous libraries stop the build.
* Copy actual `/usr/share/doc/<package>/copyright` text and common license texts,
  not symlinks or invented summaries. A conservative license tripwire rejects
  AGPL and GPL-only libraries, permits LGPL with preserved notices and exact
  sources, and narrowly permits `libgcc_s`/`libstdc++` from `gcc-N` with the GCC
  Runtime Library Exception present. Debian copyright often covers GPL build
  tools alongside LGPL/permissive libraries; DEP5's default `Files: *` license is
  used where available rather than treating a GPL `config.guess` stanza as runtime
  terms. A GPL-only `Files:` override is accepted only when its grant offers a
  non-GPL alternative (`BSD-3-clause or GPL-2`) or a standard exception (Bison,
  Autoconf, libtool distribution, Linux-syscall-note), or when every listed file is
  packaging, documentation, tests, examples, programs, scripts, a Linux UAPI
  header copy, a named non-source build-system file (not a `build-aux/*`
  wildcard), or a reviewed path in `REVIEWED_NONRUNTIME_OVERRIDES` (each with
  its reason). Prose such as "GPL-2 or later" is not an alternative license.
  Krb5, keyutils, libidn2, libzstd and colord are classified from their exact reviewed
  notices (`REVIEWED_LIBRARY_NOTICES` pins the notice SHA-256, library names and
  upstream version; Ubuntu security revisions may change). A changed notice or
  new upstream version fails until it is reviewed again.
  The error lists every unexcused file. This tripwire is **not** a determination
  of file-specific licensing. Review source-file exceptions and mixed/dual-license
  notices before release.
* CI deletes gdk-pixbuf's TIFF loader on the disposable runner before inventory
  and bundling: it links libtiff to JBIG-KIT (`libjbig`, GPL-2+), and the app
  never decodes TIFF through GTK (the worker uses Pillow's bundled libtiff).
  Copyleft wheel declarations require an explicit exact-source collector rather
  than silently borrowing unrelated Debian sources. Other wheel terms and nested
  vendored-library notices still require review.
* Download **each exact recorded Debian source package version**, even for
  permissively licensed libraries in the dependency superset:
  `apt-get source --download-only --only-source PACKAGE=SOURCE_VERSION`.
  Authenticate through apt's configured signed repository indexes. Require a
  matching `.dsc` Source/Version and SHA-256/size-verified upstream tarballs and
  Debian patch/archive files. Retain the actual `.dsc`, every file it lists,
  download logs, and a source/hash inventory in `build/linux-corresponding-sources`.
  A URL list is not a source artifact; the code makes no three-year source offer.
* **Postbundle:** independently extract the built AppImage without FUSE, require
  the expected worker layout and the exact packaged prebundle inventory, verify
  all packaged notice hashes, and enumerate every actual shared library across
  the entire AppDir. Every entry must map to that prebundle inventory (by file
  name, or by ELF SONAME for versioned copies and dev links) and its
  copied notices; Debian entries also require their verified corresponding source.
  Unknown Tauri-added libraries fail: add reviewed prebundle roots and rebuild,
  rather than patching notices into an already-produced package. Tauri may omit
  WebKitGTK from its default AppImage; the audit does not assume it ships.
  RPATH/stripping changes are permitted: retain actual postbundle hashes alongside
  prebundle hashes rather than demanding byte identity with system originals.
* Produce `Leafsmith-linux-corresponding-sources.zip`, then read it back and
  verify every archived file's hash. It contains the exact source files, source
  inventory, prebundle library inventory and postbundle audit bound to the
  AppImage's SHA-256. The external report records the source ZIP's SHA-256.
  A failed audit, missing exact source version, checksum failure or ZIP failure
  prevents the standalone package artifact upload.

Only the **disposable GitHub-hosted Ubuntu 22.04 job** configures `deb-src` for
Jammy, updates and security. It checks `GITHUB_ACTIONS`, `RUNNER_ENVIRONMENT`, OS
and codename first. The scripts themselves never edit apt configuration, install
packages, or invoke sudo. For local use, arrange authenticated matching source
indexes yourself; do not copy the CI apt-reconfiguration step onto a user's host.

Hosted runners can contain a binary version that current mirrors no longer have
as source. This is an intentional release blocker: use the matching authenticated
Ubuntu snapshot/Launchpad archive or rebuild against an available exact version.
Do **not** substitute current upstream sources, a newer Debian version, a mutable
link, or a claimed source offer. CI must actually download and check the files.
The ARM64 development host lacks dpkg/apt: synthetic ownership/source contracts
can run there, but real Ubuntu x86_64 mapping, downloads and AppImage verification
remain mandatory CI integration checks. Neither passing contracts nor these gates
are legal advice or a substitute for reviewing redistribution obligations.

Artifacts:

* `Leafsmith-windows-x86_64` / `Leafsmith-linux-x86_64`: verified package,
  `Leafsmith-<target>-third-party-notices.zip` (the notices also shipped inside
  the package) and platform `SHA256SUMS` file. The Linux artifact **also
  contains** `Leafsmith-linux-corresponding-sources.zip`; its checksum is in the
  same sums file. A release must carry this exact ZIP beside the matching
  AppImage and retain source availability with the binary (including mirrors).
  Expiring, access-controlled Actions artifacts alone are not public source
  delivery.
* `Leafsmith-evidence-<target>`: toolchains, frontend/Rust/Python logs and JUnit,
  freeze logs, smoke `report.json`, raw stdout/stderr and exact process exit
  codes, actual notices/inventories, PyInstaller warnings, generated Cargo locks,
  source download logs and Linux postbundle library/hash/source audit report.

## Publish a release

`npm run release -- rc` (or `final`, `patch`, `minor`, `major`, `minor --rc`,
`--version X.Y.Z`) automates the steps below: it bumps the four manifests, writes
release notes when `docs/releases/<tag>.md` is missing, commits and pushes main,
waits for that commit's build, pushes the tag, waits for the release, verifies
the assets against the GitHub digests and `SHA256SUMS`, then updates the README
and website download links and publishes the website. Add `--dry-run` to see the
plan and generated notes without changing anything. It refuses uncommitted
changes. If it stops after the tag, finish with
`npm run release -- --links-only <tag>`. Tests:
`python3 -m unittest discover -s scripts/tests -p test_release.py`.

Manual steps:

1. Commit release notes to `docs/releases/<tag>.md`. The first line is the
   release title (`# ...`); the rest is the body. State what CI actually
   exercised and what remains untested; the workflow appends the commit and run.
2. Push a tag matching the app version in `src-tauri/tauri.conf.json`: `v0.1.0`
   or a pre-release such as `v0.1.0-rc.2`. A tag with a `-` suffix is published
   as a pre-release.

```sh
git tag -a v0.1.0-rc.2 -m "Leafsmith 0.1.0 RC2" && git push origin v0.1.0-rc.2
gh run watch RUN_ID --repo ClawPick2026/leafsmith --exit-status
```

The tag run first checks the tag and release notes, so a mistake fails in
seconds. It then looks for an earlier successful `Desktop packages` run for the
same commit, such as the run started by merging to `main`, whose package
artifacts have not expired (14 days). If one exists, the tag run publishes those
already-verified packages in about a minute instead of rebuilding them. Push the
tag after that run has passed to get this fast path; otherwise the tag run
builds and checks both packages itself.

The `publish` job uses only packages whose builds passed every check, including
the Linux postbundle license/source audit. It verifies every downloaded asset
against both `SHA256SUMS` files, uploads the AppImage, NSIS installer, notices
ZIPs, Linux corresponding-source ZIP and checksum lists to a draft release, then
publishes it. It is the only job with `contents: write`, and the release notes
name the run that built the packages. A failed build publishes nothing. To retry
after fixing a failure, delete the tag (and any leftover draft release) and push
the tag again on the fixed commit.

## Local development

Use a dedicated virtual environment; never install build dependencies globally:

```sh
python3.12 -m venv .venv-package
# POSIX; on Windows use .venv-package/Scripts/python.exe instead.
.venv-package/bin/python -m pip install --only-binary=:all: \
  -r worker/runtime-requirements.txt pyinstaller==6.22.3 pytest==9.1.1
.venv-package/bin/python -m pytest worker/tests scripts/tests/test_freeze.py scripts/tests/test_linux_licenses.py -v
.venv-package/bin/python scripts/freeze-worker.py
# Windows: ordinary --require-rust notice collection. Linux release: use the
# --linux-native collection + exact-source + postbundle commands above.
.venv-package/bin/python scripts/license-report.py --require-rust
```

A native Rust/C toolchain and the target OS dependencies remain build-time
requirements. PyInstaller is not a cross-compiler. An ARM64 development freeze
proves only that ARM64 worker; use the hosted x86_64 matrix for deliverables.
On this development host, a local ARM64 worker freeze was exercised with Python
3.14 and user-local extracted binutils (no global installation). That is not a
Windows/Linux x86_64 Tauri build result. The first target CI run remains required.
