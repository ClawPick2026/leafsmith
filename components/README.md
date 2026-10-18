# Optional processing-engine packs

The application is MIT. Downloaded engines, libraries, OCR data and models retain their own licenses. Engine downloads require the native application's approval dialog; this pipeline never installs software on end-user machines, publishes a release, changes the registry, or downloads model weights.

**These processing-engine recipes have not passed native CI or been published by this change.** No processing-engine registry entries or download URLs are created here. Existing PATH tools remain usable. A workflow recipe or static MSI inspection is not a verified downloadable engine. Native CI build and smoke results must be reviewed before offering a pack. The separate AI/model pipeline and its release status are independent.

## Build matrix

| Engine | Linux x86_64 recipe | Windows x86_64 recipe |
|---|---|---|
| FFmpeg | Source build, 7.1.3 + libvpx 1.15.2 + Opus 1.5.2 | Same source build with MinGW64/MSYS2 |
| Tesseract | Signed Ubuntu Jammy snapshot, English + OSD data, app-local dependency closure | Native MSVC/CMake source build: Tesseract 5.5.1, Leptonica 1.85.0, libpng 1.6.50, zlib 1.3.1; pinned English + OSD data |
| LibreOffice | Signed Ubuntu Jammy snapshot, core + Writer/Calc/Impress + fonts, app-local dependency closure | Official 25.2.7.2 x64 MSI, exact SHA-256 + Authenticode gate, CI-only administrative extraction; app-local runtime/fonts |
| whisper.cpp | Separate AI pipeline; not handled by this builder | Separate AI pipeline; not handled by this builder |
| llama.cpp | Separate AI pipeline; not handled by this builder | Separate AI pipeline; not handled by this builder |

No placeholder entries are provided for unsupported engines. Transcription/local AI also need an independently selected, licensed model and explicit model-download consent; engine binaries alone do not supply those features. Existing installations and configured local providers remain alternatives.

Linux packages target Ubuntu 22.04 / glibc 2.35 or later; they are not universal across all Linux distributions. A successful headless runner smoke is not native interactive desktop testing. APT package maintainer scripts are deliberately not executed, which may expose additional LibreOffice relocation requirements: the build must fail rather than declare those packs ready.

## Run

The manually triggered workflow is `.github/workflows/components.yml`. It has read-only repository permission and uploads Actions artifacts only. A maintainer can invoke it after the workflow exists on GitHub:

```sh
gh workflow run components.yml --repo ClawPick2026/paperwork-desktop --ref main -f component=all
# component can also be ffmpeg, tesseract or libreoffice
```

Each successful native job runs the builder and smoke before upload. Jobs run independently, so failure of an Office recipe does not conceal a successful FFmpeg job. Use the Actions UI or `gh run view` to inspect each result; do not assume every matrix entry succeeded.

Local native equivalents (empty work directory required):

```sh
python scripts/build_component.py --component ffmpeg --platform linux-x86_64 --plan
python scripts/build_component.py --component ffmpeg --platform linux-x86_64
python scripts/build_component.py --component tesseract --platform linux-x86_64
python scripts/build_component.py --component libreoffice --platform linux-x86_64
# In a native Windows MinGW64 MSYS2 shell:
python scripts/build_component.py --component ffmpeg --platform windows-x86_64
# Native Windows PowerShell with Visual Studio 2022 C++ tools and CMake:
python scripts/build_component.py --component tesseract --platform windows-x86_64 --plan
python scripts/build_component.py --component tesseract --platform windows-x86_64
# LibreOffice extraction is deliberately restricted to the disposable Actions runner.
python scripts/build_component.py --component libreoffice --platform windows-x86_64 --plan
```

`--work` defaults to `build/components`; `--output` defaults to `dist/components`. Linux FFmpeg needs GCC/make/nasm/pkg-config. Windows FFmpeg needs the workflow's MinGW64 packages; it refuses to build without runtime license texts. Linux package builders use `sudo apt-get` **only on the disposable CI runner**, with an isolated source list, empty dependency status and isolated cache. They download/extract packages; they do not globally install those engines. Do not run those package-builder commands on an end-user machine. The OCR smoke uses Pillow 11.3.0 and DejaVu fonts installed only on CI.

Windows OCR/Office jobs are an independent, non-fail-fast matrix on `windows-2022`; they do not depend on, cancel or replace the existing FFmpeg/Linux jobs. Runner-only prerequisites are Python 3.12, CMake 3.31.6 and Pillow 11.3.0; the hosted runner supplies Visual Studio 2022. Windows OCR renders its smoke fixture with the runner's Arial font, not a nonexistent Linux font path. End users need none of these build dependencies or administrator privileges.

## Actual build outputs and smoke gates

A successful job supplies:

- `<id>-<version>-<platform>.zip`: regular-file payload, sorted fixed-date ZIP, notices and `PROVENANCE.json`.
- Matching `.manifest.json`: native registry fields except `url`, including the **actual** archive SHA-256 and byte count. It is deliberately not yet an installable registry entry.
- Matching `-sources.zip`: exact upstream archives/distro sources and patches, builder, source checksums and build plan. FFmpeg also records configuration and toolchain versions.
- Matching `.build.json`: binary and source filenames/checksums/sizes and the successful smoke result.

Smokes operate on a newly extracted ZIP in a path containing spaces, with only the registry entry point initially executable, matching the current Rust installer. Linux wrappers restore the required app-local executable permissions, export relative library/data paths, and invoke engines without an end-user Python dependency.

Smoke subprocess environments discard runner `TESSDATA_PREFIX`, library overrides and tool directories. Windows OCR/Office also undergo AMD64 normal/delay-import auditing before packing; non-system dependencies must be present in the payload, not merely installed on the runner. `PE-DEPENDENCIES.json` records the result. This static import check complements native conversion; it does not prove all dynamically loaded features work.

- **FFmpeg:** inspect the actual `-buildconf`; reject GPL/nonfree flags; generate VP9+Opus WebM from synthetic video/audio; decode the result. The bundled libraries are explicitly selected and autodetection is disabled. No x264/x265 encoding is supplied.
- **Tesseract:** render an actual English image and require recognition of `PAPERWORK TEST` using the pack's English trained data.
- **LibreOffice:** generate a real minimal OOXML `.docx`, convert it headlessly, and require a nonempty PDF with the PDF signature. More layout/filter/platform fixtures remain a release-testing obligation.

Payload limits match the native installer: at most 20,000 ZIP file entries, 2 GiB extracted, 750 MiB downloaded. Empty staging directories are not archived or counted as ZIP entries. Backslashes, absolute/drive/traversal paths and escaping/special links are rejected. Internal regular-file links are materialized. Distro directory links are copied as regular trees before packing; dangling alternative/manpage links are omitted, never followed into the runner's filesystem.

## Windows redistribution provenance and limitations

- **OCR:** no assumed official Windows executable and no unofficial binary distribution. All four source archives and the exact English/OSD data were downloaded and hashed during preparation. Sources, original license texts, upstream PDF font/configs, CMake command lines/caches and pinned Microsoft Visual Studio runtime terms accompany the pack. The build uses static libraries and `/MT`, disables SW downloads, curl, libarchive, OpenMP, native-CPU tuning and unpinned image codecs. PNG/PNM/BMP are supported; JPEG/TIFF/WebP decoding is not advertised by this Windows recipe. Application PDF rasterization supplies PNG to OCR.
- **Office:** the official MSI was actually downloaded; its SHA-256 matches the official archive's published value. Windows must additionally report a valid signature from The Document Foundation before `msiexec /a /qn` runs. This is administrative extraction only, never `/i` or global Office registration. The runtime's full `LICENSE.html`, `license.txt`, `NOTICE`, dictionary/extension notices and bundled fonts are retained. Its own `System64` VC runtime DLLs are relocated beside `soffice.com`; the runner's installed redistributables are not copied. The Microsoft redistribution terms are included in upstream `LICENSE.html`.
- **Corresponding Office sources:** all four exact 25.2.7.2 source bundles plus all 143 external source/data/font downloads resolved from the checksum-pinned core's `download.lst` were actually downloaded and SHA-256 verified (zero failures). The core archive retains upstream patches and build configurations. The recipe repeats this verification and refuses missing sources; its matching sources ZIP must be released beside the binary. `SOURCE-OFFER.txt` names the exact matching versioned source artifact; it is not permission to omit that artifact or rely on expiring Actions storage.
- **Scope:** this is headless document conversion, not a supported general-purpose LibreOffice installation. Java/OfficeBean, .NET automation and scanner integrations are unsupported. Fourteen exact upstream optional module paths are retained but explicitly excluded from the headless-conversion import audit and identified in its JSON; they must not be presented as verified functionality. All remaining inspected conversion/runtime PE files must be x86_64 and have an app-local/system dependency closure.
- **Preparation evidence, not native verification:** static inspection of the real MSI confirmed its runtime, fonts, notices and separate x64 CRT layout. The relocated static payload fit the packer: 18,954 files, 1,519,961,719 expanded bytes, 492,762,852 ZIP bytes. Its PE audit inspected 212 modules, explicitly identifying the 14 unsupported integrations. This scratch-only inspection archive is not a release pack and has never been run on Windows.
- These are immutable audited provenance pins, not claims that a version is newest, currently supported or CVE-free. Recheck upstream security advisories and support status before release, especially this archived Office version. A native build/smoke failure remains a blocker; do not weaken the audit to borrow host DLLs or publish a recipe as a working engine.

Deterministic ZIP construction does not imply bit-for-bit reproducible compiler output: source versions/checksums and APT snapshot are pinned, but hosted runner/toolchain updates can change binaries. Recorded toolchain/build provenance is for auditing those differences. Reproducing exact historical bytes requires retaining the runner/toolchain image too.

## Upstream pins and licenses

These source archives were actually downloaded and SHA-256 checked when preparing the recipe:

| Source | SHA-256 |
|---|---|
| [FFmpeg 7.1.3](https://ffmpeg.org/releases/ffmpeg-7.1.3.tar.xz) | `f0bf043299db9e3caacb435a712fc541fbb07df613c4b893e8b77e67baf3adbe` |
| [libvpx 1.15.2](https://github.com/webmproject/libvpx/archive/refs/tags/v1.15.2.tar.gz) | `26fcd3db88045dee380e581862a6ef106f49b74b6396ee95c2993a260b4636aa` |
| [Opus 1.5.2](https://downloads.xiph.org/releases/opus/opus-1.5.2.tar.gz) | `65c1d2f78b9f2fb20082c38cbe47c951ad5839345876e46941612ee87f9a7ce1` |
| [Tesseract 5.5.1](https://codeload.github.com/tesseract-ocr/tesseract/tar.gz/refs/tags/5.5.1) | `a7a3f2a7420cb6a6a94d80c24163e183cf1d2f1bed2df3bbc397c81808a57237` |
| [Leptonica 1.85.0](https://codeload.github.com/DanBloomberg/leptonica/tar.gz/refs/tags/1.85.0) | `c01376bce0379d4ea4bc2ec5d5cbddaa49e2f06f88242619ab8c059e21adf233` |
| [libpng 1.6.50](https://codeload.github.com/pnggroup/libpng/tar.gz/refs/tags/v1.6.50) | `71158e53cfdf2877bc99bcab33641d78df3f48e6e0daad030afe9cb8c031aa46` |
| [zlib 1.3.1](https://zlib.net/fossils/zlib-1.3.1.tar.gz) | `9a93b2b7dfdac77ceba5a558a580e74667dd6fede4585b91eefb60f03b72df23` |
| [Official LibreOffice x64 MSI 25.2.7.2](https://downloadarchive.documentfoundation.org/libreoffice/old/25.2.7.2/win/x86_64/LibreOffice_25.2.7.2_Win_x86-64.msi) | `9fdd22f8ea7a92a67de5beaa08588ef6da58c1930ac86fd57c46b0c6d7ca9d34` |

Windows OCR data uses the upstream `tessdata_fast` 4.1.0 tag's immutable commit `65727574dfcd264acbb0c3e07860e4e9e9b22185`: English SHA-256 `7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2`, OSD SHA-256 `9cf5d576fcc47564f11265841e5ca839001e7e6f38ff7f7aacf46d15a96b00ff`. The original Apache-2.0 license is separately pinned and preserved. Exact Office source-bundle and Microsoft notice pins are in the builder's printed plan.

- [FFmpeg licensing](https://ffmpeg.org/legal.html): LGPL-2.1-or-later with this configuration; no `--enable-gpl`, `--enable-nonfree`, system FFmpeg copy or unknown prebuilt build. Original LGPL texts are copied. libvpx is BSD-3-Clause plus its patent grant; Opus includes BSD and patent terms. Windows static compiler runtimes retain GCC runtime exceptions/MinGW notices.
- [Tesseract](https://github.com/tesseract-ocr/tesseract/blob/main/LICENSE): Apache-2.0, with separately licensed Leptonica/runtime dependencies and trained data. The recipe includes English/OSD only, not all languages.
- [LibreOffice licensing](https://www.libreoffice.org/about-us/licenses/): MPL-2.0/LGPL-3.0-or-later and third-party components. The recipe preserves each package's `usr/share/doc/*/copyright`, common license texts and exact corresponding distro source packages.
- Linux package selection uses [Ubuntu's immutable snapshot service](https://snapshot.ubuntu.com/ubuntu/20261001T000000Z/), Jammy/main/universe/updates/security, authenticated by Ubuntu's archive signing key. Each included `.deb` has its exact version and SHA-256 recorded. Missing corresponding source is a fatal error. Ghostscript/MuPDF dependency packages are rejected; neither is deliberately installed or bundled.

A license label is not a redistribution audit. Inspect every dependency's notices, source availability and platform runtime licenses before release. Publish the matching source artifact beside every binary and retain it as long as necessary; do not replace it with a mutable upstream URL or treat Actions' expiring artifact storage as a permanent source offer.

## Promote only after publishing and verification

The coordinator owns all GitHub/release writes. This workflow has no publishing token or release action.

1. Review each native build/smoke, notices and source artifact; perform application-level and native platform checks.
2. Publish **both** the exact engine ZIP and matching sources ZIP to an immutable versioned release.
3. Download the published engine URL independently and verify its SHA-256 and byte count against the artifact manifest.
4. Copy the manifest fields into `registry.json` and add the real `url`. The only allowed prefix is `https://github.com/ClawPick2026/paperwork-desktop/releases/download/`. Do not add build metadata/provenance fields: Rust's entry schema rejects unknown fields.
5. Rebuild the app containing that verified registry and test the consent/install/run flow.

Never add pending URLs, made-up hashes, a mutable `latest` asset, a source archive in place of an executable, or entries for packs whose native smoke failed.

## Contract tests and current verification limit

```sh
python -W error::ResourceWarning -m unittest discover -s scripts/tests -p test_components.py -v
```

The stdlib suite currently passes 21 tests: deterministic real ZIPs/checksums, manifest shape, executable modes, safety/size/file-count boundaries, pin verification, traversal rejection, real OOXML fixture structure, CLI plans, nonnative refusal, Windows source/data/notice staging, signature rejection, CI-only MSI extraction, native font selection, isolated smoke environments and PE dependency gates. New behaviors were exercised RED then GREEN; orchestration tests use clearly labelled synthetic fixtures, not a substitute for native compilation. Actionlint 1.7.12 validates the complete workflow. The preparation host is ARM64 with no C/C++/APT tooling: native compilation, Windows Authenticode verification, OCR and Office conversion have **not** been executed there. Actual Actions results must establish that the recipes produce usable x86_64 packs; this README does not claim they already did.
