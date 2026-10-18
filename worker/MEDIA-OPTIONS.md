# Native media/AI worker

`media_ops.OPERATIONS` = `enhance_image`, `compress_video`, `transcribe`, `summarize`, `translate_pdf`.

## Exact integration contract

```python
run({"operation": "enhance_image", "inputs": ["/absolute/input.png"],
     "output_dir": "/absolute/existing/private/job", "options": {}, "engines": {}})
# -> {"outputs": [{"path": "/absolute/existing/private/job/enhanced.jpg",
#                  "name": "enhanced.jpg", "mime": "image/jpeg"}], "details": {...}}
```

Exactly one input per request; maximum file size 512 MiB. Rust MUST grant selected inputs, create a private per-job directory, and supply engine/model paths exclusively from its consented, versioned registry. Frontend must never choose executable paths. Errors raise actionable `ValueError` (underlying malformed-file errors may also propagate to shared worker error handling). No subprocess shell, frontend commands, automatic installation, model downloads, or cloud fallback. Existing outputs are never overwritten. All returned outputs are inside the job directory; temporary files are cleaned. Job cancellation/process-tree limits remain the host's responsibility. FFmpeg only accepts local file/pipe protocols and allowlisted media demuxers.

## Options (keys not listed for an operation have no effect)

| Operation | Options and defaults | Output |
|---|---|---|
| `enhance_image` | `brightness=1`, `contrast=1`, `sharpness=1` (finite 0–4); `format="jpeg"` (`jpeg/png/webp`); `quality=85` (integer 1–100; PNG uses lossless optimization); `width=16384`, `height=16384` (integer 1–16384 bounding box, aspect-preserving, never upscales) | `enhanced.jpg/png/webp` |
| `compress_video` | `crf=36` (integer 10–63); `max_height=1080` (integer 64–2160); `timeout=600` seconds (1–1800); `max_duration=7200` seconds (1–14400) | `compressed.webm`, VP9/Opus |
| `transcribe` | `provider="whisper.cpp"` or `openai-compatible`; `language="auto"` (local language code); `timeout=600` (1–1800; cloud HTTP capped at 300); `max_duration=7200` (1–14400); remote options below | `transcript.txt`, `transcript.srt` |
| `summarize` | Model options below | `summary.md`, model-generated map/reduce summary |
| `translate_pdf` | Model options below; required `language` (language name or BCP-47 code, 2–60 word/space/hyphen characters) | `translated.pdf`, `translated.txt` |

Image processing uses Pillow, not generative AI; maximum 40 million pixels, EXIF orientation applied. Static output uses the first image frame. Compression may not reduce size. Video/audio output stops at `max_duration`; the returned details explicitly disclose that limit. Video selects the first video and optional first audio stream, drops metadata/subtitles, uses two encoding threads. H.264 and optional native/generative image stacks are deliberately not exposed: there is no verified redistributable runtime pack for them here.

### Summary/translation model options

- `provider="ollama"` (default), `"llama.cpp"`, or `"openai-compatible"`.
- `model`: explicitly selected installed Ollama model or provider model (required). No arbitrary default model/download. For llama.cpp it is an optional display label: omitted or empty (`""`) uses the internal label `registry-model`; the actual weights must still be the installed registry file `engines.llama_model`.
- `endpoint="http://127.0.0.1:11434"` for Ollama, **loopback only**. Remote provider endpoint is required, includes API base (e.g. `https://host/v1`), and gets `/chat/completions` appended. No query, fragment or embedded URL credentials. HTTPS required except literal loopback/localhost. Redirects and environment proxies disabled.
- `chunk_chars=12000` (integer 1000–24000); `max_input_chars=1000000` (integer 1000–4000000); `max_tokens=1024` (integer 64–4096); `max_requests=128` (integer 1–256); `timeout=120` seconds per request (1–300). No retries. Each HTTP response capped at 1 MiB. Input exceeding configured bounds fails, never silently discards tail chapters. Map/reduce consumes the same request budget and fails if summaries cannot shrink. Explicit server truncation is an error; llama CLI has no structured finish reason, so verify completeness manually.
- Inputs: UTF-8 text or text-based PDF, at most 2000 PDF pages; 16 MiB decoded content limit per page. Scans require OCR first. Parsing/model processes still need host memory/resource limits against hostile documents.
- Model tasks carry an untrusted-data system prompt and JSON document field; no tools are exposed. This limits execution capability, not a guarantee against model hallucinations or prompt injection affecting prose. Consumers must render generated Markdown safely.

### Explicit optional cloud/BYOK

For every `openai-compatible` job, `cloud_consent` must be the boolean `true`, including loopback provider adapters. This is checked before outbound requests. `endpoint` and `model` are required. Rust must supply only the key explicitly entered for that job as `options.api_key` (1–4096 printable ASCII characters). Never persist/log the key or serialize it into saved job history. Ambient credentials, including `PAPERWORK_API_KEY` and `GITHUB_TOKEN`, are never read or used. The presence of `api_key_env` is rejected, even if empty/null or an explicit key is also supplied. Missing/invalid keys fail with a value-free error directing the user to `options.api_key`. Module emits no logs, prompts, transcripts, API keys, or provider error bodies.

Transcription appends `/audio/transcriptions`, uploads FFmpeg-extracted 16 kHz mono PCM WAV (maximum 25 MiB), and requests `verbose_json`. A provider must return nonempty `text` and actual timestamped `segments`; missing timestamps fail rather than inventing SRT timing. `language` currently affects local whisper only. Cloud consent allows sending the extracted audio to the selected provider, which may retain it or charge fees.

## Engine keys (absolute files supplied only by registry)

- `ffmpeg`: needed for video and all transcription, including cloud.
- `whisper`, `whisper_model`: whisper.cpp CLI and separately consented local model. No `options.model_path` escape hatch.
- `llama`, `llama_model`: llama.cpp CLI and separately consented GGUF. Uses bounded noninteractive completion, 32768 context and two CPU threads. Prompts, generated-text staging and engine diagnostics are created inside a private `llama-*` subdirectory of `output_dir`, closed and cleaned on success or exceptions. Both summary and translation pass the job directory through the adapter. Actual selected runtime/version/model template needs native integration verification; intercepted CLI tests cannot establish supported flags or generation quality.
- `pdf_font`: optional licensed TrueType font for translation. Defaults to ReportLab's bundled Bitstream Vera. Missing glyphs fail honestly; select a suitable font for CJK/other scripts. Complex-script shaping is not guaranteed.

Translation produces a **new text document, not an original-layout PDF**. Figures, tables, annotations and original typography are not preserved. Both PDF and TXT contain this notice. Verify translated meaning and model facts against the source.

## Licensing / release boundary

App code is MIT, not all dependencies/models. Installed versions: Pillow 12.2.0 (MIT-CMU/HPND family notice), pypdf 6.13.3 (BSD-3-Clause), ReportLab 4.4.10 (BSD family, plus font notices), charset-normalizer 3.5.2 (MIT). Preserve wheel license files and ReportLab Bitstream Vera font notice in frozen packaging. No AGPL dependencies added. Optional whisper.cpp/llama.cpp code and each model retain their own licenses; model acceptance must show exact version, source, size, license and consent. Do not claim all models are MIT.

The **test-host FFmpeg is GPLv3-or-later**, built with `--enable-gpl --enable-version3` and x264/x265. It was executed externally for tests, NOT copied or redistributed. VP9/libvpx + Opus were verified in real output; codec selection alone does not change a binary's license. Release needs a separately audited LGPL-compatible FFmpeg build with appropriate notices/source obligations and no GPL/nonfree components. Runtime pack distribution/CI is coordinator-owned.

## Verification

```sh
.venv-media/bin/python -m pip install -r worker/media-requirements.txt
PAPERWORK_TEST_FFMPEG=/absolute/test/ffmpeg \
  .venv-media/bin/python -W error -m unittest discover -s worker/tests -p 'test_media*.py' -v
```

`PAPERWORK_TEST_FFPROBE` can override ffprobe (otherwise sibling of FFmpeg). This environment is test-only; application paths are never hardcoded. Real image pixels and real FFmpeg VP9/Opus output are inspected, WAV conversion is real. HTTP fixtures and intercepted CLI responses are explicitly **adapter tests, not model/speech quality evidence**. Cloud adapters use explicit fixture keys and retain no-request-before-consent assertions. Security tests use ambient credential sentinels and observe that configuration never reads the environment; no HTTP is needed. Local adapter tests inspect the actual prompt under the job directory, verify cleanup after engine failure, and read back real summary/PDF/TXT artifacts for omitted/empty display labels. No model download or cloud request is part of these tests. Real-model/runtime compatibility and quality smoke tests belong to runtime-pack CI, not this adapter suite. Original artifact RED/GREEN evidence and the host-license audit remain in `media-evidence.log`; privacy-regression RED/GREEN commands, hashes and exit statuses are captured separately in the release-review tool output.
