# Optional processing-engine packs

The application is MIT. Engines, libraries, OCR data and models retain their original licenses. Component installation requires the native application's explicit approval dialog. This builder never publishes releases, edits the registry, downloads models or installs processing engines globally on end-user machines.

**Candidate recipes, not release approval.** Rebuild every processing pack after these security updates; artifacts from the old pins are not approved for publication. No processing-engine registry entries or release URLs are created here. Native CI and application-level checks remain required.

**Office is explicitly a pre-release candidate, not a stable/production approval.** The official **26.2.7.1** Windows/Linux distributions replace 26.2.6.2 and contain **libpng 1.6.59**. The [exact source tag's `download.lst`](https://raw.githubusercontent.com/LibreOffice/core/libreoffice-26.2.7.1/download.lst) selects that version and includes [upstream's dependency upgrade](https://github.com/LibreOffice/core/commit/fd76bd2515f0d4e69ed227834ee355bf6a6d7f88). The [libpng maintainer's advisory](https://www.openwall.com/lists/oss-security/2026/09/29/4) identifies 1.6.59 as fixing CVE-2026-46675 (the triggering sequence is `png_read_info` then `png_read_end` without starting row reading). Static inspection of the actual `mergedlo.dll` / `libmergedlo.so` also finds 1.6.59. This resolves that dependency baseline, not all security questions. [The Document Foundation discourages production use of pre-releases](https://www.libreoffice.org/download/pre-releases/); plans, pack display names, provenance and source offers retain the pre-release candidate qualification. Native CI and application acceptance remain pending. No stable, CVE-free or release-ready claim is made. libpng is statically linked into the Office runtime: do not overlay a DLL or mix libraries from another release.

## Build matrix

| Engine | Linux x86_64 recipe | Windows x86_64 recipe |
|---|---|---|
| FFmpeg | Source build: **7.1.5**, libvpx 1.15.2, Opus 1.5.2 | Same sources, MinGW64/MSYS2 |
| Tesseract | Signed Ubuntu Jammy snapshot; English + OSD; app-local dependencies and exact distro sources | Native MSVC/CMake: **Tesseract 5.5.3, Leptonica 1.87.0, libpng 1.6.59, zlib 1.3.2**; pinned English + OSD |
| LibreOffice | Official **26.2.7.1 pre-release candidate** x64 DEB distribution; Jammy snapshot only for app-local system libraries/fonts, never its old Office engine | Official **26.2.7.1 pre-release candidate** x64 MSI; SHA-256 + expected-publisher Authenticode; CI-only administrative extraction and exact AMD64 CRT member selection |
| whisper.cpp / llama.cpp | Separate AI/model pipeline, not this builder | Separate AI/model pipeline, not this builder |

Linux targets Ubuntu 22.04 / glibc 2.35 or later, not every distribution. Host glibc and its loader remain the baseline; no bundled glibc/host-loader mixture is allowed. No distro package maintainer scripts are executed. Existing PATH engines remain alternatives, not evidence that a pack works.

## Security review and provenance

- [LibreOffice security advisories](https://www.libreoffice.org/about-us/security/advisories/): CVE-2026-63266/63267/63268/63269/63270/63277 and CFF issues CVE-2026-63275/63276 require the fixed 26.2.5/26.8.0 lines or later. The old Windows 25.2.7.2 pin is removed.
- [Ubuntu's actual CVE tracker](https://git.launchpad.net/ubuntu-cve-tracker/plain/active/CVE-2026-63266) marks Jammy's October issues `needs-triage`, not released. The CFF issues 63275/63276 are separately marked fixed in `1:7.3.7-0ubuntu0.22.04.13`. This does **not** establish the entire old engine is fixed. Consequently Linux Office now uses the current official distribution and explicitly rejects a distro-Office fallback.
- [FFmpeg releases](https://ffmpeg.org/releases/) list 7.1.5 as the latest 7.1 maintenance release checked. Its actual downloaded `Changelog` includes heap/use-after-free/out-of-bounds fixes absent from 7.1.3, including Dirac edge buffers, RASC decode, subtitle headers, and demuxer bounds checks. [The security page](https://ffmpeg.org/security.html) is not an exhaustive 7.1.5 CVE accounting; this upgrade is not a claim that all known multimedia CVEs are fixed.
- [Tesseract 5.5.3 release notes](https://github.com/tesseract-ocr/tesseract/releases/tag/5.5.3) include trained-data deserialization memory-safety/integer-overflow fixes. Leptonica is updated to its checked current release, 1.87.0.
- [libpng changes](https://github.com/pnggroup/libpng/blob/libpng16/CHANGES) identify multiple high-severity fixes after the old OCR pin 1.6.50, through the compressed-metadata fix in 1.6.59. The Windows OCR recipe uses 1.6.59. [zlib 1.3.2](https://zlib.net/) incorporates its security-audit fixes; the recipe handles its changed CMake options and `zs.lib` static output. Tesseract removed SW integration in 5.5.3; Leptonica's remaining SW integration is explicitly disabled.

Pins are immutable audit inputs, not a guarantee of security or legal compliance. Repeat upstream/dependency review before each release. A native smoke only establishes the exercised conversion/OCR/media behavior.

## Run

The manually triggered `.github/workflows/components.yml` has read-only repository permissions and uploads Actions artifacts only. Its native jobs are independent and non-fail-fast. The coordinator owns all GitHub/release writes.

```sh
gh workflow run components.yml --repo ClawPick2026/leafsmith --ref main -f component=all
# component can also be ffmpeg, tesseract or libreoffice

python scripts/build_component.py --component ffmpeg --platform linux-x86_64 --plan
python scripts/build_component.py --component ffmpeg --platform linux-x86_64
python scripts/build_component.py --component tesseract --platform linux-x86_64
python scripts/build_component.py --component libreoffice --platform linux-x86_64
# Native Windows MinGW64 MSYS2 shell:
python scripts/build_component.py --component ffmpeg --platform windows-x86_64
# Native Windows PowerShell with Visual Studio 2022 C++ tools:
python scripts/build_component.py --component tesseract --platform windows-x86_64
# Office extraction is restricted to the disposable Actions runner:
python scripts/build_component.py --component libreoffice --platform windows-x86_64 --plan
```

An empty work directory is required. `--work` defaults to `build/components`, `--output` to `dist/components`. Linux FFmpeg needs GCC/make/nasm/pkg-config; Windows needs the workflow's MinGW64 packages and their runtime license texts. Linux package builders use `sudo apt-get` **only on disposable CI**, with isolated signed sources/status/cache, to download/extract dependencies and corresponding sources; do not run them on end-user machines. Windows OCR/Office use the existing `windows-2022` lane, Python 3.12, CMake 3.31.6 and Pillow 11.3.0. End users need no compiler, Python, VC installer or administrator privileges.

## Outputs and acceptance gates

Each successful job supplies:

- `<id>-<version>-<platform>.zip`: deterministic regular-file payload with notices and provenance.
- Matching `.manifest.json`: actual SHA-256 and byte count, but deliberately no unpublished `url`.
- Matching `-sources.zip`: exact upstream archives/distro sources, patches, builder, checksums and build plan. FFmpeg includes configuration/toolchain records; Windows OCR includes CMake commands/caches and runtime terms.
- Matching `.build.json`: actual binary/source filenames, checksums, sizes and relocated smoke result.

All smokes re-extract the actual ZIP into a path containing spaces, with only the registry entry point initially executable, matching the Rust installer. Wrappers restore required executable permissions and set app-local library/data/font paths. Subprocess environments discard runner library/data/tool overrides.

- **FFmpeg:** inspect actual `-buildconf`, reject GPL/nonfree configuration, require disabled autodetection, generate VP9+Opus WebM and decode it. No x264/x265 encoding is provided.
- **OCR:** render a real image with a native font and recognize `LEAFSMITH TEST` with the pack's own trained data. Windows supports PNG/PNM/BMP; JPEG/TIFF/WebP codecs are deliberately not built. The application rasterizes PDF inputs to PNG.
- **Office:** create actual minimal OOXML DOCX, convert headlessly, and require a nonempty PDF with its PDF signature. Native/application-level layout/filter testing remains required; this is not a general-purpose Office installation.

Windows audits normal/delay imports, requires AMD64 PE32+ conversion binaries and app-local or identified Windows OS dependencies. Linux Office parses ELF64 dynamic metadata without executing `ldd`, rejects missing app-local dependencies and unsafe search paths, permits only explicit baseline glibc/loader SONAMEs, and writes `ELF-DEPENDENCIES.json` beside the source/binary provenance. These checks supplement, not replace, native execution and dynamic-feature testing.

Limits remain **20,000 ZIP file entries, 2 GiB expanded, 750 MiB downloaded**. Directories do not count as archived files. Unsafe paths, unsupported/escaping links and special files are rejected; internal file links are materialized. Distro directory links are copied app-locally; dangling alternative/manpage links are omitted rather than borrowed from the runner.

## Office runtime/source handling

All four **26.2.7.1 candidate** source archives and **all 152** external source/data/font downloads resolved from the checksum-pinned core's `download.lst` were actually downloaded or exact-hash-verified from cache, with zero failures. The core's 33,308-byte `download.lst` is byte-identical to the exact upstream tag and has SHA-256 `a419394891bf347ed5f84e8aeadc372601557313ea9f58673c839670834d62c9`. Of the externals, 139 identical prior archives were reused only after matching the new manifest hashes. Verified externals total 869,050,803 bytes; four candidate sources total 648,556,764 bytes. The Office external is `libpng-1.6.59.tar.xz`, SHA-256 `d80dd2a38a37f803cb9b6ac7b14bd6e74ddc3b654780a8380bdf93523fdb4389` (distinct from the OCR source archive). The core preserves upstream patches/build configurations. The builder repeats source verification and fails on missing bytes. The matching source ZIP must be published beside any approved binary; expiring Actions storage is not a permanent source offer.

### Windows

The actual official MSI was downloaded and matched its published hash. Native Windows additionally must verify valid Authenticode from The Document Foundation before `msiexec /a /qn`. The signature subprocess removes PowerShell 7's inherited `PSModulePath`, explicitly loads Windows PowerShell's own security module, and treats cmdlet/module failures as fatal; it never bypasses signature validation. Never use `/i` or globally register Office. The complete application runtime, `LICENSE.html`, `license.txt`, `NOTICE`, extension/dictionary notices and MSI `Fonts` are retained.

This MSI contains both **ARM64 and AMD64 CRT cabinet members with colliding `System64` target filenames**. Copying the flattened directory can silently choose the wrong architecture. The builder instead reads the embedded CAB through Windows' read-only MSI API, uses Windows `expand.exe` to select eight exact SHA-256-pinned AMD64 CRT members, verifies their actual PE architecture/imports, and relocates them beside `soffice.com`. All eight candidate members were re-extracted and hashed from the real candidate MSI: the `#libreoffice1.cab` stream and exact `_amd64.DFEFC2FE_EEE6_424C_841B_D4E66F0C84A3` member identities are unchanged, but all eight hashes changed (MSI File table reports CRT 14.44.35211.0). Their Microsoft redistribution terms remain in upstream `LICENSE.html`. It does not borrow a runner's redistributables. Unselected CRT members are not silently added; a new dependency fails closed.

The existing fourteen exact Java/.NET/scanner module paths remain unsupported and identified in `PE-DEPENDENCIES.json`. The same ten **exact** x86/ARM64 pip/setuptools packaging-launcher paths are rebased to the candidate's actual `python-core-3.12.15` directory, preserved but explicitly excluded from the headless-conversion audit; no arbitrary directory wildcard or conversion module is excluded. All ten exact paths exist in the inspected candidate. Native conversion still must pass.

**Static preparation only:** the corrected real candidate MSI payload has 19,475 files, 1,574,073,344 expanded bytes and a measured 509,280,481-byte ZIP. Its PE audit records 233 entries including the same 24 explicitly unsupported integrations/packaging launchers. Metadata adds a few files; existing limits need no change. This scratch inspection ZIP is not a release pack. The native MSI API/`expand.exe` path, Authenticode and actual Windows conversion remain CI obligations.

### Linux

The official x64 DEB archive was actually downloaded and matched its published SHA-256. The builder extracts its current Office modules under app-local `root/opt/libreoffice26.2`, never executing maintainer scripts. Six exact optional desktop-integration/Python/LibreLogo packages are omitted; fonts, import filters, dictionaries, core/module data and original runtime notices are preserved. The complete release's matching sources are retained even for omitted modules.

The retained core's five exact optional GUI/multimedia/Java integration libraries are identified rather than represented as verified functionality. `SAL_USE_VCLPLUGIN=svp` selects headless conversion. The explicitly selected library/font package closure comes from [the signed immutable Jammy snapshot](https://snapshot.ubuntu.com/ubuntu/20261001T000000Z/). Every included dependency `.deb` records exact binary/source versions and SHA-256; exact `apt-get source name=version` downloads include distro patches and `.dsc` checksums. Missing corresponding source is fatal. Dependency copyright and common-license texts are retained. Ghostscript/MuPDF packages and any old distro Office engine are rejected.

The selected candidate distribution was statically inspected on ARM64: 36 retained DEBs, 12,527 files / 661,746,823 bytes before adding distro dependencies and metadata. Each retained DEB's actual control record identifies `amd64` and version `26.2.7.1-1` (the previous candidate recipe used revision `-2`); the version gate remains exact. Loader-authoritative metadata from all 188 ELF files was parsed, not executed. **The complete signed APT closure, corresponding dependency sources, full ELF closure audit and relocated conversion have not yet been executed on a native x86_64 runner for this candidate recipe.** Do not turn the direct-library list or synthetic tests into a claim of verified Linux portability/provenance.

## Exact principal pins

These bytes were actually downloaded and hashed. The printed builder plans include all source-bundle/data/runtime pins.

| Source | SHA-256 |
|---|---|
| [FFmpeg 7.1.5](https://ffmpeg.org/releases/ffmpeg-7.1.5.tar.xz) | `de668509caf9e35e3cd162473441fdb29538c6d96ed080292b3cf9e6fc5d558f` |
| [libvpx 1.15.2](https://github.com/webmproject/libvpx/archive/refs/tags/v1.15.2.tar.gz) | `26fcd3db88045dee380e581862a6ef106f49b74b6396ee95c2993a260b4636aa` |
| [Opus 1.5.2](https://downloads.xiph.org/releases/opus/opus-1.5.2.tar.gz) | `65c1d2f78b9f2fb20082c38cbe47c951ad5839345876e46941612ee87f9a7ce1` |
| [Tesseract 5.5.3](https://codeload.github.com/tesseract-ocr/tesseract/tar.gz/refs/tags/5.5.3) | `9218e62793116d42a9f6d14cd9348518b27f382096eea3d0f2d1a24616bb5884` |
| [Leptonica 1.87.0](https://codeload.github.com/DanBloomberg/leptonica/tar.gz/refs/tags/1.87.0) | `fa2b40c5caea96d1bb93a97486262aed8731b69ce25a84a6bf5d25323e33f631` |
| [libpng 1.6.59](https://codeload.github.com/pnggroup/libpng/tar.gz/refs/tags/v1.6.59) | `2540302a1844ad2b2b501977abecfa850f265f97b78f065a712ab4074a89f5b5` |
| [zlib 1.3.2](https://zlib.net/zlib-1.3.2.tar.xz) | `d7a0654783a4da529d1bb793b7ad9c3318020af77667bcae35f95d0e42a792f3` |
| [LibreOffice 26.2.7.1 pre-release Windows MSI](https://downloadarchive.documentfoundation.org/libreoffice/old/26.2.7.1/win/x86_64/LibreOffice_26.2.7.1_Win_x86-64.msi) | `82edb4c85605bf38420f461596c5e4eb625afbe6557bd6c7bfa2c470b430a8c7` |
| [LibreOffice 26.2.7.1 pre-release Linux DEB distribution](https://downloadarchive.documentfoundation.org/libreoffice/old/26.2.7.1/deb/x86_64/LibreOffice_26.2.7.1_Linux_x86-64_deb.tar.gz) | `7cc840bd089f4779636cb2340f33786e71ce66669fdfbe36fe5c7322edc186ee` |
| [LibreOffice 26.2.7.1 core source](https://downloadarchive.documentfoundation.org/libreoffice/old/26.2.7.1/src/libreoffice-26.2.7.1.tar.xz) | `3ce4475c3e8c27450d667d83bf2dd9e99a8070d190363286022cf392d4eaec17` |
| [LibreOffice 26.2.7.1 dictionaries source](https://downloadarchive.documentfoundation.org/libreoffice/old/26.2.7.1/src/libreoffice-dictionaries-26.2.7.1.tar.xz) | `b8c73d520b1b6f65e1eed838d903334dbc68aa57c729049af74cac47db14cafd` |
| [LibreOffice 26.2.7.1 help source](https://downloadarchive.documentfoundation.org/libreoffice/old/26.2.7.1/src/libreoffice-help-26.2.7.1.tar.xz) | `cbe017cfb3ebd15bcffec2d3b646b0414a4b62c2a8eedb9c0d2dc7568dfc6843` |
| [LibreOffice 26.2.7.1 translations source](https://downloadarchive.documentfoundation.org/libreoffice/old/26.2.7.1/src/libreoffice-translations-26.2.7.1.tar.xz) | `781fc87e10424b510ee095480f152c4ed044e6b9a98e2a07020584bfe7691ac8` |

OCR data still uses the immutable tessdata_fast commit `65727574dfcd264acbb0c3e07860e4e9e9b22185`: English `7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2`, OSD `9cf5d576fcc47564f11265841e5ca839001e7e6f38ff7f7aacf46d15a96b00ff`. Its Apache-2.0 notice is independently pinned and preserved.

FFmpeg uses LGPL-2.1-or-later configuration with no GPL/nonfree/autodetected libraries; libvpx includes BSD/patent terms and Opus its original BSD/patent terms. Windows compiler runtimes retain GCC/MinGW exception/notices. OCR retains Apache-2.0, BSD-2-Clause, libpng and zlib notices plus MSVC terms. Office retains upstream MPL-2.0/LGPL-3.0-or-later and all third-party notices. These labels are not a redistribution audit or relicensing. Deterministic ZIP layout also does not make hosted compiler output bit-for-bit reproducible: preserve toolchain/runner provenance.

## Promote only after security, native and publication verification

1. Retain Office's explicit pre-release candidate status; review all current upstream/dependency advisories and upstream production guidance. The libpng 1.6.59 baseline alone is not stable-release approval. Do not publish old-pin artifacts.
2. Review actual native build/smoke, notices/source artifacts and application-level/platform checks.
3. Publish **both** approved engine ZIP and matching sources ZIP to an immutable versioned release.
4. Independently download the published engine and verify its SHA-256/byte count against its manifest.
5. Add the real URL and manifest fields to `registry.json`, using only `https://github.com/ClawPick2026/leafsmith/releases/download/`. Do not add build metadata: Rust rejects unknown entry fields.
6. Rebuild the app and test consent/install/run. Never add pending URLs, made-up hashes, mutable `latest`, a source archive instead of an executable, or failed-smoke packs.

## Contract verification

```sh
python -W error::ResourceWarning -m unittest discover -s scripts/tests -p test_components.py -v
```

The updated stdlib suite has security-minimum/pin regression tests, actual ZIP/hash/path/size tests, OOXML structure, CLI/native-host refusal, isolated smoke environments, exact source staging, signature gates, PE/ELF dependency checks, current OCR CMake flags and AMD64 CRT member verification. New behavior was exercised RED then GREEN. Clearly labelled synthetic orchestration/ELF/PE fixtures are not native execution. The preparation host is ARM64 without C/C++/APT tools; new native compilation, MSI APIs, OCR and Office conversion still require actual CI results. No assertion here approves the new packs for release.
