# Optional local AI packs — build and release gates

**Status: ready-to-trigger recipe, not a verified release.** No engine binaries or
model ZIPs were compiled, published, committed or added to the registry by this
change. The preparation host is Linux ARM64 without a C/C++ compiler. Native
Windows/Linux x86_64 compilation, real model inference, ZIP sizes and ZIP hashes
must come from the workflow results. The existing general-engine builder is
independent; its README's previous AI “not implemented” rows do not describe this
new recipe.

## Independent downloads and consent

| Registry/worker ID | Pack entry point | License / purpose |
|---|---|---|
| `whisper` | `bin/whisper-cli` (`.exe` on Windows) | whisper.cpp MIT engine, bundled third-party notices |
| `whisper_model` | `models/ggml-tiny.en.bin` | OpenAI Whisper tiny **English-only**, MIT, converted by whisper.cpp upstream |
| `llama` | `bin/llama-cli` (`.exe` on Windows) | llama.cpp MIT engine, bundled third-party notices |
| `llama_model` | `models/qwen2.5-0.5b-instruct-q4_k_m.gguf` | Official Qwen2.5-0.5B-Instruct GGUF, Q4_K_M, Apache-2.0 |

Weights are separate ZIP assets, never hidden in engine ZIPs. Installing an engine
must not install its weights automatically. Native application consent must show
the **actual ZIP** size, version and licenses for each separate installation.
The worker receives independently installed absolute paths under the four IDs
above. No end-user Python installation, cloud account or API key is required.
Transcription also requires the independently installed FFmpeg component.

`--allow-model-downloads` and the workflow checkbox authorize **builder/CI-only**
weight downloads, not end-user installation or external document processing. No
models are downloaded by `--plan` or the unit suite. Native inference uses only
local model paths; CURL, server, RPC, GPU and system-GGML integration are disabled.
These packs do not supply a model-download client or start a service.

## Trigger, without publishing

`.github/workflows/ai-components.yml` is manual dispatch only, with repository
`contents: read`, no stored checkout credentials and Actions artifact uploads
only. The coordinator can trigger it once the workflow is present on GitHub:

```sh
gh workflow run ai-components.yml --repo ClawPick2026/paperwork-desktop --ref main \
  -f component=all -f allow_model_downloads=true
# component: all, whisper, llama
```

Each selected family runs independently on **ubuntu-22.04 x86_64** and
**windows-latest x86_64**. Failures do not cancel the other jobs. CMake 3.31.6,
Ninja 1.11.1.3 and `worker/media-requirements.txt` are runner-only build/smoke
dependencies. Windows enters the native MSVC x64 developer environment and uses
`/MT`; Linux links the engine/ggml statically but retains the system C/C++ runtime.
No AVX/AVX2/FMA/F16C/SSE4.2 CPU requirement is requested by the recipe.

FFmpeg is installed on the disposable runner only: Ubuntu's package or Windows
Chocolatey `ffmpeg` 7.1.1. That test dependency is **not** redistributed in these
packs and does not define the separate app's FFmpeg license/configuration. Hosted
images, MSVC/GCC and OS package mirrors can change; source pins are fixed, binary
bit-for-bit reproducibility and perpetual hosted-image availability are not
claimed. Dependency or source failures must fail the job, never create substitute
registry entries.

Native equivalents (empty work directory; never on an end-user machine):

```sh
python scripts/build_ai_components.py --component whisper --platform linux-x86_64 --plan
python scripts/build_ai_components.py --component whisper --platform linux-x86_64 --allow-model-downloads
python scripts/build_ai_components.py --component llama --platform linux-x86_64 --allow-model-downloads
# Native x64 VS developer shell, with CMake/Ninja on PATH:
python scripts/build_ai_components.py --component llama --platform windows-x86_64 --allow-model-downloads
```

Use `--ffmpeg /absolute/path/to/ffmpeg` if it is not discoverable on the build
runner. Defaults: work `build/ai-components`, successful output
`dist/ai-components`. Wrong-architecture or unconsented builds fail before writes
or network requests.

## Immutable pins and measured source bytes

Both actual engine source archives were downloaded, hashed, safely extracted and
inspected on the preparation host. Upstream tag references were resolved to the
following exact commits; CI fetches the commit archives, not mutable tag URLs.

| Source | Commit | Archive bytes | Actual archive SHA-256 |
|---|---|---:|---|
| [whisper.cpp v1.7.6](https://github.com/ggml-org/whisper.cpp/tree/a8d002cfd879315632a579e73f0148d06959de36) | `a8d002cfd879315632a579e73f0148d06959de36` | 7,309,272 | `7b17da903114ed45d82f48c030e3be6a5a8a279f884b2f733706dbb4e832fb6b` |
| [llama.cpp b6780](https://github.com/ggml-org/llama.cpp/tree/b22572e97dc51757d3ebe917a5a283385010ec68) | `b22572e97dc51757d3ebe917a5a283385010ec68` | 25,959,077 | `46387109730a3ea6c288afcc3af56dcbf3c00bbde1618eb1b3b038be1785ef16` |

The model pins below are **raw weight** byte counts and SHA-256s from the pinned
Hugging Face LFS metadata, not measured distribution ZIP properties. Full weight
downloads are deferred to explicitly consented CI; CI independently verifies every
byte against these pins before packaging and again after ZIP extraction.

| Weights | Immutable model revision | Raw bytes | Raw SHA-256 |
|---|---|---:|---|
| [Whisper tiny.en](https://huggingface.co/ggerganov/whisper.cpp/tree/5359861c739e955e79d9a303bcbc70fb988958b1) | `5359861c739e955e79d9a303bcbc70fb988958b1` | 77,704,715 | `921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f` |
| [Official Qwen GGUF Q4_K_M](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/tree/9217f5db79a29953eb74d5343926648285ec7e67) | `9217f5db79a29953eb74d5343926648285ec7e67` | 491,400,032 | `74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db` |

Both model cards and license texts were actually retrieved and hashed. Qwen's
pinned LICENSE is Apache-2.0, not an assumed license inherited from a different
Qwen size. OpenAI Whisper's MIT license is retained, together with whisper.cpp's
attribution for the conversion. The builder pins the notice/card sizes and hashes
and preserves all upstream LICENSE/COPYING/NOTICE files plus full vendored sources
carrying inline notices (including miniaudio/stb_vorbis and llama's vendor tree).
Windows also includes Microsoft's pinned STL Apache-2.0-with-LLVM-exception license
and third-party notices. The proprietary MSVC CRT is statically linked; it is not
relabelled MIT. Maintainers still need to review the selected hosted toolchain's
redistribution terms and ensure the notice snapshot covers the actual toolchain
before release; this recipe is not legal advice or a license audit.

## Real native smoke gates

The builder creates separate engine/model ZIPs in private staging, then extracts
both to a path containing spaces. Only the engine entry point receives executable
permissions, matching the native installer. Smoke uses the **extracted binary and
weights through the actual `worker/media_ops.py` implementation**, not a mocked
adapter, preinstalled whisper/llama, remote service or Python inference backend.
Build-tree DLL/library search paths are removed during execution.

- **whisper:** pinned upstream `samples/jfk.wav`, SHA-256
  `59dfb9a4acb36fe2a2affc14bacbee2920ff435cb13cc314a08c13f66ba7860e`.
  Real FFmpeg converts to 16 kHz mono PCM WAV; real `whisper-cli` receives the
  worker's `-m/-f/-otxt/-osrt/-of` flags. Require nonempty TXT/SRT, timestamp syntax,
  known `ask`/`country` words and normalized JFK word error rate **at most 0.35**.
  The original upstream archive, its MIT license and fixture remain together in
  the matching source artifact; the fixture is not silently copied to binary
  packs. Independently review recording rights before republishing source assets.
- **llama:** actual worker `summarize` and `translate_pdf` operations using its
  current offline CLI flags, temperature zero, 32,768-token context, two CPU
  threads and 128 output tokens. The two-sentence summary must retain **Alice,
  Friday, and five/5**. English-to-French output must contain **bonjour, Alice,
  vendredi**, and produce an actual PDF with `%PDF-` magic. Both text outputs must
  have 10–4,000 characters. No alternative prompt/template is substituted just
  to make the pack smoke pass; a model/worker incompatibility fails the gate.
- **Native/runtime:** ELF or PE must be x86_64. `readelf`/`dumpbin` dependencies
  are allowlisted to system runtimes only. Linux build RPATH/RUNPATH and any
  unbundled ggml/OpenMP/GPU library fail. Windows VCRUNTIME/MSVCP DLL dependencies
  fail rather than assuming end users have a redistributable installed.

`.build.json` and the Actions summary report actual fixture outputs, measured
quality counters, worker/fixture hashes and source artifact properties. Tiny
English transcription is not multilingual. A 0.5B quantized text model is a
low-resource baseline with limited instruction-following/factual/translation
quality. These tiny fixtures are sanity bounds, not an accuracy benchmark,
injection defense proof, or approval for high-stakes documents.

## Successful output and promotion

Only after all native gates pass does output leave private staging:

- Separate `<id>-<version>-<platform>.zip` engine and model payloads.
- Per-ZIP `.manifest.json`: exactly registry fields except `url`, including
  **actual ZIP** `sha256`, `downloadBytes`, `license` and `executable`.
- Engine-matched `-sources.zip`: original upstream archive (all original licenses
  and fixture), builder/worker source, pinned model cards/licenses, CMake cache,
  build plan and exact source checksums. Weights are not redundantly included.
- `.build.json`: both manifests, source ZIP digest/size and actual native smoke
  quality evidence. No URL, pending registry entry, release or model auto-install.

Payloads contain regular files only, fixed-date/sorted ZIP entries, no traversal,
backslashes, Windows drive/reserved names, case collisions or links. Enforced
limits: 750 MiB downloaded, 2 GiB extracted, 20,000 paths. Downloads require exact
HTTPS URL/size/SHA-256 pins, including cached files. Large files stream instead of
being loaded wholesale into builder memory.

After CI: review all four native results, licenses, model outputs and source ZIPs;
perform packaged-app consent/install/run and native interactive checks; publish
immutable release assets and source artifacts; independently download the exact
published URLs and recheck their ZIP SHA/size. **Only then** may the coordinator
populate registry entries with the real allowlisted release `url`. Engine and
model consent remain independent. Actions' expiring storage is not publication or
a durable source offer.

## Preparation-host verification (not native inference)

```sh
python -W error::ResourceWarning -m unittest discover -s scripts/tests -p test_ai_components.py -v
# 13 tests: actual ZIPs/digests/modes, limits, path/link/case rejection, cache pins,
# safe source extraction, notice copying, CLI plans/guards and quality/dependency gates.
```

Tests were introduced and observed failing before their corresponding behavior
was implemented; additional already-passing size/mode checks are characterization
coverage, not claimed RED evidence. The final case-collision regression failed
with “ValueError not raised” before the rejection was implemented. Actual source
and notice fetches plus extraction were exercised separately. `actionlint` 1.7.7
passes this workflow. No weights, native compiler build, real transcription,
real summary/translation, or desktop installer was run on the ARM64 host. Native
CI has **not** been triggered here; any first-run failure remains a real blocker,
not permission to weaken gates or advertise a usable pack.
