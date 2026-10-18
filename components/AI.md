# Optional local AI packs — build and release gates

**Release status:** Whisper CPU engine and tiny-English model packs have passed real native transcription on Windows and Linux x86_64, and are [published with verified hashes and matching sources](https://github.com/ClawPick2026/paperwork-desktop/releases/tag/components-v0.1.0). The previous 0.5B text model failed the real native translation factuality gate on both platforms. The replacement **1.5B Q2_K is a pinned candidate only: native inference and release approval are pending**. The llama.cpp/text-model packs must not be advertised as available until their own gates pass. The general OCR/Office/FFmpeg pipeline is independent.

## Independent downloads and consent

| Registry/worker ID | Pack entry point | License / purpose |
|---|---|---|
| `whisper` | `bin/whisper-cli` (`.exe` on Windows) | whisper.cpp MIT engine, bundled third-party notices |
| `whisper_model` | `models/ggml-tiny.en.bin` | OpenAI Whisper tiny **English-only**, MIT, converted by whisper.cpp upstream |
| `llama` | `bin/llama-cli` (`.exe` on Windows) | llama.cpp MIT engine, bundled third-party notices |
| `llama_model` | `models/qwen2.5-1.5b-instruct-q2_k.gguf` | Candidate: official Qwen2.5-1.5B-Instruct GGUF, Q2_K, Apache-2.0 |

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

## Text candidate decision — quality approval pending

The recovered native diagnostics under
`artifacts/llama-real-diagnostics/ai-diagnostics-llama-<platform>/llama-<platform>/smoke`
show the same genuine 0.5B failure on Windows and Linux x86_64: the summary
preserved Alice, five and Friday, but translation returned
`Bonjour, mon nom est Alice. Le rendez-vous est mardi. [end of text]`.
The input says Friday; `mardi` means Tuesday. This was nonempty, on-task model
output with a factual error, not an interactive-CLI or empty-output failure.
The unchanged gate correctly rejects it. Never replace the model's answer with
hardcoded `vendredi`, change the fixture, or reduce required facts to pass.

The next candidate is **Qwen2.5-1.5B-Instruct Q2_K**, version
`qwen2.5-1.5b-q2k-91cad511-r1`. Its official card identifies 1.54B parameters
and a 32,768-token context.[2] The official API resolved the revision below;
Q2_K is 752,880,160 raw bytes, whereas Q3_K_M (924,455,968) and Q4_K_M
(1,117,320,736) exceed the unchanged 750 MiB raw-download cap.[1]
Greater parameter capacity with more aggressive quantization is a candidate
tradeoff, **not evidence of better translation**. The official model card and
the actual pinned license both specify Apache-2.0.[2][3]

This change preserves the llama.cpp source pin, build flags, worker protocol,
prompts, inference settings, prompt privacy and independent download/cloud
consent. No registry entry is added. The coordinator must next run the unchanged
real native worker smoke on both platforms. Output quality, runtime/memory use,
timeouts and final ZIP sizes remain CI gates; archive size caps are not RAM caps.
Publication and exact published-asset readback are still required before promotion.

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

The model pins below are **raw weight** byte counts and SHA-256s, not distribution
ZIP properties. Whisper's pin was originally obtained from pinned Hugging Face
LFS metadata. For the new Qwen candidate, the official API/LFS metadata was
requeried and the full immutable weight URL was actually downloaded and hashed
on the preparation host; all 752,880,160 bytes matched the pin.[1]
CI independently verifies every byte before packaging and again after extraction.

| Weights | Immutable model revision | Raw bytes | Raw SHA-256 |
|---|---|---:|---|
| [Whisper tiny.en](https://huggingface.co/ggerganov/whisper.cpp/tree/5359861c739e955e79d9a303bcbc70fb988958b1) | `5359861c739e955e79d9a303bcbc70fb988958b1` | 77,704,715 | `921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f` |
| [Official Qwen 1.5B GGUF Q2_K](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/tree/91cad51170dc346986eccefdc2dd33a9da36ead9) | `91cad51170dc346986eccefdc2dd33a9da36ead9` | 752,880,160 | `5ede348e91ce1e7a330926ec5b202c27b864d065149dc463257fde1f98865b3a` |

The candidate's immutable notice/card URLs were also downloaded, not inferred
from the old model. Exact measured bytes and SHA-256s:[2][3]

| Included notice | Raw bytes | Actual SHA-256 |
|---|---:|---|
| `Qwen-LICENSE` | 11,343 | `832dd9e00a68dd83b3c3fb9f5588dad7dcf337a0db50f7d9483f310cd292e92e` |
| `Qwen-model-card.md` | 4,856 | `57c72d4010fb11a98fc8e62dc8ef112b23a7a7525b71e571ca978d35cb3b2eec` |

The raw candidate leaves 33,551,840 bytes below the 786,432,000-byte (750 MiB)
download cap. An actual **preparation-only** ZIP containing those weights, the
two notices and a probe disclaimer measured 733,623,465 bytes downloaded and
752,896,517 bytes expanded. Installer-like extraction preserved the raw weight
SHA-256. This is a bounds/extraction probe, **not a distributable release pack**:
the final native build must include its engine attribution/provenance and pass
all existing 750 MiB ZIP / 2 GiB expanded / 20,000-path checks independently.

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
English transcription is not multilingual. The 1.5B Q2_K text model is a bounded,
aggressively quantized candidate with unverified native instruction-following,
factual and translation quality. These tiny fixtures are sanity bounds, not an accuracy benchmark,
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
# 15 tests: actual ZIPs/digests/modes, limits, path/link/case rejection, cache pins,
# source extraction, notices, CLI plans/guards, candidate pins and quality/dependency gates.
```

The candidate pin regression was run **before** changing the recipe: it failed
on the old 0.5B model for both platform plans, then passed after the minimal
pin/name/notice update. The obsolete test-only 500 MiB assumption now checks the
actual unchanged 750 MiB installer cap; the exact cap values are also asserted.
No semantic gate was weakened. Added characterization rejects each independently
missing summary fact and French marker, the observed wrong-weekday output, and
out-of-bounds lengths; these already-passing negative checks are not claimed RED
evidence. Replaying both recovered 0.5B native outputs through `assess_text`
also confirmed rejection. The focused suite passed all 15 tests. A broader
`unittest discover -s scripts/tests -v` run was blocked at import for
`test_freeze`, `test_frozen_pptx` and `test_packaged_operations` because this
interpreter lacks `pytest`; it is not claimed as a passing full scripts suite.
No global test dependencies were installed.

Local evidence is in
`/home/defaultuser/.hermes/cache/scratch/qwen15-candidate/`:
`hf-model-api.json`, `notice-proof.json`, `raw-weight-proof.json`,
`model-pack-bound-proof.json`, `old-model-rejection.json`,
`tdd-{red,green}.{json,log}` and `ai-suite.{json,log}`. TDD records include exact
commands, exit statuses and builder/test source hashes. Scratch evidence is
temporary, not a durable release source offer. The 1.5B candidate has **not** run
native inference here. Native CI and published-asset verification belong to the
coordinator; any candidate failure is a real blocker, not permission to weaken
gates or advertise a usable pack.

## Sources

[1] https://huggingface.co/api/models/Qwen/Qwen2.5-1.5B-Instruct-GGUF?blobs=true
[2] https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/91cad51170dc346986eccefdc2dd33a9da36ead9/README.md
[3] https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/91cad51170dc346986eccefdc2dd33a9da36ead9/LICENSE
