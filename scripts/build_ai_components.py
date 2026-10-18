#!/usr/bin/env python3
"""Pinned, opt-in native AI engine/weight packs; never publishes or edits registry."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile
import zipfile

MAX_DOWNLOAD = 750 * 1024 * 1024
MAX_EXTRACTED = 2 * 1024 * 1024 * 1024
MAX_FILES = 20000
PLATFORMS = {"linux-x86_64", "windows-x86_64"}
# Source archive hashes measured from actual downloads, not Git object hashes.
SOURCES = {
    "whisper": {"name": "whisper-v1.7.6.tar.gz", "version": "1.7.6", "tag": "v1.7.6",
                "commit": "a8d002cfd879315632a579e73f0148d06959de36", "bytes": 7309272,
                "url": "https://codeload.github.com/ggml-org/whisper.cpp/tar.gz/a8d002cfd879315632a579e73f0148d06959de36",
                "sha256": "7b17da903114ed45d82f48c030e3be6a5a8a279f884b2f733706dbb4e832fb6b"},
    "llama": {"name": "llama-b6780.tar.gz", "version": "b6780", "tag": "b6780",
              "commit": "b22572e97dc51757d3ebe917a5a283385010ec68", "bytes": 25959077,
              "url": "https://codeload.github.com/ggml-org/llama.cpp/tar.gz/b22572e97dc51757d3ebe917a5a283385010ec68",
              "sha256": "46387109730a3ea6c288afcc3af56dcbf3c00bbde1618eb1b3b038be1785ef16"},
}
MODELS = {
    "whisper": {"name": "ggml-tiny.en.bin", "version": "tiny-en-5359861c-r1", "license": "MIT",
                "revision": "5359861c739e955e79d9a303bcbc70fb988958b1", "bytes": 77704715,
                "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-tiny.en.bin",
                "sha256": "921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f"},
    "llama": {"name": "qwen2.5-0.5b-instruct-q4_k_m.gguf", "version": "qwen2.5-0.5b-q4km-9217f5db-r1",
              "license": "Apache-2.0", "revision": "9217f5db79a29953eb74d5343926648285ec7e67", "bytes": 491400032,
              "url": "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/9217f5db79a29953eb74d5343926648285ec7e67/qwen2.5-0.5b-instruct-q4_k_m.gguf",
              "sha256": "74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db"},
}
NOTICES = {
    "whisper": [
        {"name": "OpenAI-Whisper-LICENSE", "bytes": 1063,
         "url": "https://raw.githubusercontent.com/openai/whisper/v20250625/LICENSE",
         "sha256": "b5d65a59060e68c4ff940e1eddfa6f94b2d68fdf58ed7f4dd57721c997e35e9d"},
        {"name": "Whisper-model-card.md", "bytes": 3196,
         "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/README.md",
         "sha256": "21fd967098804f33fc84e803fb0e5ab7666d71801f4027cf28a65e7af09c1758"},
    ],
    "llama": [
        {"name": "Qwen-LICENSE", "bytes": 11343,
         "url": "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/9217f5db79a29953eb74d5343926648285ec7e67/LICENSE",
         "sha256": "832dd9e00a68dd83b3c3fb9f5588dad7dcf337a0db50f7d9483f310cd292e92e"},
        {"name": "Qwen-model-card.md", "bytes": 4856,
         "url": "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/9217f5db79a29953eb74d5343926648285ec7e67/README.md",
         "sha256": "fa1fede7f775a20f111cc098c00900092020572ce78976970a5b0ad9ca211999"},
    ],
}
JFK_SHA256 = "59dfb9a4acb36fe2a2affc14bacbee2920ff435cb13cc314a08c13f66ba7860e"
WINDOWS_NOTICES = [
    {"name": "Microsoft-STL-LICENSE.txt", "bytes": 12550,
     "url": "https://raw.githubusercontent.com/microsoft/STL/vs-2022-17.14/LICENSE.txt",
     "sha256": "1fc6b6db121d4555d8f661937d7f6013693cd8fd67495d5e5d98c1d18fb83eda"},
    {"name": "Microsoft-STL-NOTICE.txt", "bytes": 10762,
     "url": "https://raw.githubusercontent.com/microsoft/STL/vs-2022-17.14/NOTICE.txt",
     "sha256": "11dee60b182033b92dfcce5344093eb05e009e2c0339ce551f5667b3838c8223"},
]


def build_plan(component, target):
    if component not in SOURCES or target not in PLATFORMS:
        raise ValueError("Choose whisper/llama on native Windows/Linux x86_64")
    # Portable CPU baseline; no AVX requirement, GPU backend or download-capable CURL.
    flags = ["-DCMAKE_BUILD_TYPE=Release", "-DBUILD_SHARED_LIBS=OFF", "-DGGML_BACKEND_DL=OFF",
             "-DGGML_NATIVE=OFF", "-DGGML_CPU=ON", "-DGGML_OPENMP=OFF", "-DGGML_LLAMAFILE=OFF",
             "-DGGML_BLAS=OFF", "-DGGML_ACCELERATE=OFF", "-DGGML_CUDA=OFF", "-DGGML_METAL=OFF",
             "-DGGML_VULKAN=OFF", "-DGGML_HIP=OFF", "-DGGML_SYCL=OFF", "-DGGML_RPC=OFF",
             "-DGGML_OPENCL=OFF", "-DGGML_KOMPUTE=OFF", "-DGGML_MUSA=OFF", "-DGGML_CCACHE=OFF",
             *[f"-DGGML_{x}=OFF" for x in ("AVX", "AVX2", "AVX_VNNI", "AVX512", "AVX512_VBMI",
                                         "AVX512_VNNI", "AVX512_BF16", "BMI2", "FMA", "F16C", "SSE42")],
             f"-D{component.upper()}_CURL=OFF", f"-D{component.upper()}_BUILD_TESTS=OFF",
             f"-D{component.upper()}_BUILD_SERVER=OFF"]
    if component == "whisper":
        flags += ["-DWHISPER_BUILD_EXAMPLES=ON", "-DWHISPER_SDL2=OFF", "-DWHISPER_FFMPEG=OFF",
                  "-DWHISPER_COREML=OFF", "-DWHISPER_OPENVINO=OFF"]
    else:
        flags += ["-DLLAMA_BUILD_COMMON=ON", "-DLLAMA_BUILD_TOOLS=ON", "-DLLAMA_BUILD_EXAMPLES=OFF",
                  "-DLLAMA_OPENSSL=OFF", "-DLLAMA_LLGUIDANCE=OFF", "-DGGML_WEBGPU=OFF"]
    if target.startswith("windows"):
        flags += ["-DCMAKE_C_COMPILER=cl", "-DCMAKE_CXX_COMPILER=cl",
                  "-DCMAKE_POLICY_DEFAULT_CMP0091=NEW", "-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded"]
    return {"component": component, "platform": target, "source": dict(SOURCES[component]),
            "model": dict(MODELS[component]), "notices": NOTICES[component],
            "runtimeNotices": WINDOWS_NOTICES if target.startswith("windows") else [], "cmake": flags}


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fetch(pin, cache):
    import urllib.request
    cache = Path(cache)
    if (not re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]) or not pin["url"].startswith("https://")
            or safe_name(pin["name"]) != Path(pin["name"]).name
            or not isinstance(pin["bytes"], int) or not 0 < pin["bytes"] <= MAX_DOWNLOAD):
        raise ValueError("An HTTPS URL, safe basename, exact size and SHA-256 are required")
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / pin["name"]
    if not path.exists():
        partial = path.with_name(path.name + ".partial")
        try:
            with urllib.request.urlopen(pin["url"], timeout=180) as response, partial.open("wb") as out:
                if not response.geturl().startswith("https://"):
                    raise ValueError("Download redirected outside HTTPS")
                while chunk := response.read(1024 * 1024):
                    out.write(chunk)
                    if out.tell() > pin["bytes"]:
                        raise ValueError("Download exceeds pinned size")
            if partial.stat().st_size != pin["bytes"] or digest(partial) != pin["sha256"]:
                raise ValueError("Download checksum/size mismatch")
            partial.replace(path)
        finally:
            partial.unlink(missing_ok=True)
    if path.is_symlink() or path.stat().st_size != pin["bytes"] or digest(path) != pin["sha256"]:
        raise ValueError(f"Cached checksum/size mismatch: {path}")
    return path


def safe_name(name):
    if (not name or name.startswith("/") or "\\" in name or ":" in name
            or any(part in {"", ".", ".."} for part in name.split("/"))):
        raise ValueError(f"Unsafe archive path: {name}")
    for part in name.split("/"):
        if (part.endswith((".", " ")) or any(ord(c) < 32 for c in part)
                or any(c in part for c in '<>"|?*')
                or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part)):
            raise ValueError(f"Nonportable archive path: {name}")
    return name


def unpack_source(archive, destination):
    destination = Path(destination)
    if destination.exists():
        raise ValueError("Source destination must not exist")
    with tarfile.open(archive) as source:
        entries = source.getmembers()
        if len(entries) > MAX_FILES or sum(e.size for e in entries) > MAX_EXTRACTED:
            raise ValueError("Source archive exceeds limits")
        seen = set()
        for entry in entries:
            name = safe_name(entry.name.rstrip("/"))
            if name.casefold() in seen or not (entry.isfile() or entry.isdir()):
                raise ValueError(f"Duplicate or special source entry: {entry.name}")
            seen.add(name.casefold())
        destination.mkdir(parents=True)
        # Explicit regular-file extraction avoids links/devices and tarfile version differences.
        for entry in entries:
            path = destination / entry.name
            if entry.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(entry) as incoming, path.open("xb") as out:
                    shutil.copyfileobj(incoming, out, 1024 * 1024)
    return destination


def extract_pack(archive, destination, executable, is_engine):
    safe_name(executable)
    destination = Path(destination)
    if destination.exists() or Path(archive).stat().st_size > MAX_DOWNLOAD:
        raise ValueError("Empty destination and bounded archive required")
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        if len(entries) > MAX_FILES or sum(e.file_size for e in entries) > MAX_EXTRACTED:
            raise ValueError("Extracted ZIP exceeds limits")
        seen = set()
        for entry in entries:
            name = safe_name(entry.filename)
            kind = stat.S_IFMT(entry.external_attr >> 16)
            if name.casefold() in seen or kind not in {0, stat.S_IFREG} or entry.is_dir():
                raise ValueError("ZIP must contain unique regular files only")
            seen.add(name.casefold())
        if executable not in {e.filename for e in entries}:
            raise ValueError("ZIP lacks entry point")
        destination.mkdir(parents=True)
        for entry in entries:
            path = destination / entry.filename
            path.parent.mkdir(parents=True, exist_ok=True)
            with source.open(entry) as incoming, path.open("xb") as out:
                shutil.copyfileobj(incoming, out, 1024 * 1024)
            path.chmod(0o700 if is_engine and entry.filename == executable else 0o600)
    return destination


def create_pack(payload, output, metadata):
    payload, output = Path(payload), Path(output)
    required = {"id", "name", "version", "platform", "license", "executable"}
    if (set(metadata) != required or metadata["id"] not in {"whisper", "llama", "whisper_model", "llama_model"}
            or metadata["platform"] not in PLATFORMS
            or not re.fullmatch(r"[A-Za-z0-9._-]+", metadata["version"])):
        raise ValueError("Invalid component metadata")
    safe_name(metadata["executable"])
    paths = sorted(payload.rglob("*"))
    seen = set()
    for path in paths:
        relative = safe_name(path.relative_to(payload).as_posix())
        if relative.casefold() in seen:
            raise ValueError(f"Duplicate/colliding archive path: {relative}")
        seen.add(relative.casefold())
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError(f"Only regular files/directories allowed: {path}")
    if not (payload / metadata["executable"]).is_file():
        raise ValueError("Missing component entry point")
    if len(paths) > MAX_FILES or sum(p.stat().st_size for p in paths if p.is_file()) > MAX_EXTRACTED:
        raise ValueError("Pack exceeds installer limits")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"{metadata['id']}-{metadata['version']}-{metadata['platform']}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as target:
        for path in paths:
            if not path.is_file():
                continue
            relative = path.relative_to(payload).as_posix()
            entry = zipfile.ZipInfo(relative, (1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            mode = 0o755 if relative == metadata["executable"] and not metadata["id"].endswith("_model") else 0o644
            entry.external_attr = (stat.S_IFREG | mode) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            with path.open("rb") as source, target.open(entry, "w", force_zip64=True) as dest:
                shutil.copyfileobj(source, dest, 1024 * 1024)
    if archive.stat().st_size > MAX_DOWNLOAD:
        archive.unlink()
        raise ValueError("Archive exceeds download limit")
    manifest = dict(metadata, sha256=digest(archive), downloadBytes=archive.stat().st_size)
    manifest_path = archive.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {"archive": str(archive), "manifest": manifest, "manifestPath": str(manifest_path)}


def audit_links(target, text):
    if target == "linux-x86_64":
        names = re.findall(r"\(NEEDED\).*?\[([^\]]+)\]", text)
        allowed = {"libc.so.6", "libm.so.6", "libstdc++.so.6", "libgcc_s.so.1", "libpthread.so.0",
                   "libdl.so.2", "librt.so.1", "ld-linux-x86-64.so.2"}
        if re.search(r"\((?:RPATH|RUNPATH)\)", text):
            raise ValueError("Build-path RPATH/RUNPATH is not distributable")
    elif target == "windows-x86_64":
        names = [x.lower() for x in re.findall(r"^\s+([A-Za-z0-9_.-]+\.dll)\s*$", text, re.M | re.I)]
        # /MT: no redistributable MSVC DLLs and no unbundled ggml/OpenMP dependencies.
        allowed = {"kernel32.dll", "advapi32.dll", "shell32.dll", "user32.dll", "ws2_32.dll", "ole32.dll",
                   "bcrypt.dll", "ntdll.dll", "shlwapi.dll", "winmm.dll", "ucrtbase.dll", "gdi32.dll"}
    else:
        raise ValueError("Unknown target")
    if not names or set(names) - allowed:
        raise ValueError(f"Unaudited native runtime dependencies: {sorted(set(names) - allowed)}")
    return sorted(set(names))


def assess_speech(text, srt):
    reference = "and so my fellow americans ask not what your country can do for you ask what you can do for your country".split()
    words = re.findall(r"[a-z]+", text.lower())
    row = list(range(len(words) + 1))
    for index, word in enumerate(reference, 1):
        next_row = [index]
        for other_index, other in enumerate(words, 1):
            next_row.append(min(next_row[-1] + 1, row[other_index] + 1, row[other_index - 1] + (word != other)))
        row = next_row
    wer = row[-1] / len(reference)
    if (not words or wer > 0.35 or "country" not in words or "ask" not in words
            or not re.search(r"\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}", srt)):
        raise ValueError(f"Speech fixture quality gate failed (WER {wer:.3f}, max 0.35; TXT/SRT required)")
    return {"wordErrorRate": wer, "maxWordErrorRate": 0.35, "timestampSyntax": True,
            "reference": " ".join(reference), "transcript": text}


def assess_text(summary, translated):
    summary_lower, translated_lower = summary.lower(), translated.lower()
    facts = ["alice" in summary_lower, "friday" in summary_lower,
             bool(re.search(r"\bfive\b|\b5\b", summary_lower))]
    tokens = [word in translated_lower for word in ("bonjour", "alice", "vendredi")]
    if (not all(facts) or not all(tokens) or not 10 <= len(summary) <= 4000
            or not 10 <= len(translated) <= 4000):
        raise ValueError("Text fixture quality gate failed (all three summary facts and French markers required)")
    return {"summaryFactHits": sum(facts), "summaryFactsRequired": 3, "translationTokenHits": sum(tokens),
            "translationTokensRequired": 3, "maxOutputCharacters": 4000,
            "summary": summary, "translation": translated,
            "qualityLimit": "Fixture sanity only, not general factuality or translation accuracy."}


def copy_notices(component, source, payload):
    source, payload = Path(source), Path(payload)
    selected = {p for p in source.rglob("*") if p.is_file()
                and p.name.lower().startswith(("license", "copying", "notice"))}
    # Full vendored files preserve inline BSD/MIT/public-domain notices, not just labels.
    for directory in ("vendor", "ggml/src/ggml-cpu"):
        selected.update(p for p in (source / directory).rglob("*") if p.is_file())
    if component == "whisper":
        for name in ("examples/miniaudio.h", "examples/stb_vorbis.c"):
            path = source / name
            if not path.is_file():
                raise ValueError(f"Missing third-party notice-bearing source: {name}")
            selected.add(path)
    if not (source / "LICENSE").is_file():
        raise ValueError("Missing upstream LICENSE")
    for path in sorted(selected):
        out = payload / "licenses/upstream" / path.relative_to(source)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, out)


def run(command, cwd=None, env=None):
    print("+ " + " ".join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), cwd=cwd, env=env, check=True, timeout=3600, shell=False)


def native_audit(executable, target):
    if target.startswith("windows"):
        tool = shutil.which("dumpbin")
        if not tool:
            raise RuntimeError("Run from a native x64 Visual Studio developer environment (dumpbin required)")
        headers = subprocess.check_output([tool, "/HEADERS", str(executable)], text=True, errors="replace")
        if not re.search(r"8664 machine \(x64\)", headers, re.I):
            raise ValueError("Expected native PE x86_64 executable")
        text = subprocess.check_output([tool, "/DEPENDENTS", str(executable)], text=True, errors="replace")
    else:
        headers = subprocess.check_output(["readelf", "-h", str(executable)], text=True)
        if "Advanced Micro Devices X86-64" not in headers:
            raise ValueError("Expected native ELF x86_64 executable")
        text = subprocess.check_output(["readelf", "-d", str(executable)], text=True)
    return {"systemDependencies": audit_links(target, text), "headers": headers, "dependencyAudit": text}


def smoke(component, engine, model, source, work, ffmpeg):
    import importlib.util
    repository = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("pack_media_ops", repository / "worker/media_ops.py")
    media = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(media)
    work.mkdir(parents=True)
    engines = {component: str(engine), component + "_model": str(model)}
    # Only OS libraries on PATH: staged/build-tree DLLs cannot conceal missing pack dependencies.
    previous_path = os.environ.get("PATH", "")
    previous_library_path = os.environ.pop("LD_LIBRARY_PATH", None)
    os.environ["PATH"] = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32") if os.name == "nt" else "/usr/bin:/bin"
    try:
        if component == "whisper":
            fixture = source / "samples/jfk.wav"
            if digest(fixture) != JFK_SHA256:
                raise ValueError("Pinned speech fixture changed")
            engines["ffmpeg"] = str(ffmpeg)
            result = media.run({"operation": "transcribe", "inputs": [str(fixture)], "output_dir": str(work),
                                "engines": engines, "options": {"language": "en", "timeout": 600, "max_duration": 20}})
            text = (work / "transcript.txt").read_text(encoding="utf-8")
            srt = (work / "transcript.srt").read_text(encoding="utf-8")
            quality = assess_speech(text, srt)
            quality["fixtureSha256"] = JFK_SHA256
            quality["workerDetails"] = result["details"]
        else:
            summary_input = work / "summary-input.txt"
            summary_input.write_text("Alice approved a five dollar budget. The team will meet on Friday.", encoding="utf-8")
            translation_input = work / "translation-input.txt"
            translation_input.write_text("Hello, my name is Alice. The meeting is on Friday.", encoding="utf-8")
            summary_dir, translation_dir = work / "summary", work / "translation"
            summary_dir.mkdir()
            translation_dir.mkdir()
            options = {"provider": "llama.cpp", "max_tokens": 128, "timeout": 300}
            summary_result = media.run({"operation": "summarize", "inputs": [str(summary_input)],
                                        "output_dir": str(summary_dir), "engines": engines, "options": options})
            translation_result = media.run({"operation": "translate_pdf", "inputs": [str(translation_input)],
                                            "output_dir": str(translation_dir), "engines": engines,
                                            "options": dict(options, language="French")})
            if not (translation_dir / "translated.pdf").read_bytes().startswith(b"%PDF-"):
                raise ValueError("Worker did not produce a translated PDF")
            quality = assess_text((summary_dir / "summary.md").read_text(encoding="utf-8"),
                                  (translation_dir / "translated.txt").read_text(encoding="utf-8"))
            quality["fixtureSha256"] = {p.name: digest(p) for p in (summary_input, translation_input)}
            quality["workerDetails"] = [summary_result["details"], translation_result["details"]]
    finally:
        os.environ["PATH"] = previous_path
        if previous_library_path is not None:
            os.environ["LD_LIBRARY_PATH"] = previous_library_path
    quality["workerSha256"] = digest(repository / "worker/media_ops.py")
    quality["mode"] = "actual native CLI and separately extracted model through worker; no mock/provider/cloud"
    return quality


def build(component, target, work, output, allow_model_downloads=False, ffmpeg=None):
    import platform
    if not allow_model_downloads:
        raise RuntimeError("Explicit --allow-model-downloads is required; weights are never downloaded implicitly")
    host = ("windows" if os.name == "nt" else platform.system().lower()) + "-" + platform.machine().lower().replace("amd64", "x86_64")
    if target != host:
        raise RuntimeError(f"A native {target} runner is required, not {host}")
    plan = build_plan(component, target)
    ffmpeg = Path(ffmpeg or shutil.which("ffmpeg") or "").resolve()
    if component == "whisper" and not ffmpeg.is_file():
        raise RuntimeError("Native FFmpeg required on the CI runner for the real worker transcription smoke")
    work, output = Path(work).resolve() / f"{component}-{target}", Path(output).resolve()
    if work.exists():
        raise ValueError(f"Use an empty work directory; existing work preserved: {work}")
    # Keep all pack files private until compilation, extraction, dependency/quality gates pass.
    work.mkdir(parents=True)
    sources = work / "sources"
    archive = fetch(plan["source"], sources)
    extracted = unpack_source(archive, work / "source")
    trees = list(extracted.iterdir())
    if len(trees) != 1 or not trees[0].is_dir():
        raise ValueError("Expected one upstream source root")
    source = trees[0]
    engine_payload, model_payload = work / "engine-payload", work / "model-payload"
    (engine_payload / "bin").mkdir(parents=True)
    (model_payload / "models").mkdir(parents=True)
    weights = fetch(plan["model"], work / "weights-cache")
    shutil.copyfile(weights, model_payload / "models" / weights.name)
    for pin in plan["notices"]:
        notice = fetch(pin, sources)
        for payload in (engine_payload, model_payload):
            (payload / "licenses").mkdir(exist_ok=True)
            shutil.copyfile(notice, payload / "licenses" / notice.name)
    for pin in plan["runtimeNotices"]:
        notice = fetch(pin, sources)
        shutil.copyfile(notice, engine_payload / "licenses" / notice.name)
    copy_notices(component, source, engine_payload)
    # The whisper.cpp conversion also carries its own MIT attribution in the weight pack.
    shutil.copyfile(source / "LICENSE", model_payload / "licenses" / f"{component}.cpp-LICENSE")
    build_dir = work / "cmake-build"
    cmake = shutil.which("cmake")
    if not cmake:
        raise RuntimeError("CMake is required on the native build runner")
    # Archive builds must not accidentally report the enclosing app's git commit.
    build_environment = dict(os.environ, GIT_CEILING_DIRECTORIES=str(work))
    run([cmake, "-S", source, "-B", build_dir, "-G", "Ninja", *plan["cmake"]], env=build_environment)
    run([cmake, "--build", build_dir, "--config", "Release", "--target", component + "-cli", "--parallel", "2"], env=build_environment)
    executable = component + "-cli" + (".exe" if target.startswith("windows") else "")
    binary = build_dir / "bin" / executable
    if not binary.is_file():
        raise ValueError("Upstream target did not produce the expected CLI")
    audit = native_audit(binary, target)
    shutil.copyfile(binary, engine_payload / "bin" / executable)
    cache = build_dir / "CMakeCache.txt"
    toolchain = {
        "cmake": subprocess.check_output([cmake, "--version"], text=True),
        "python": platform.python_version(), "host": platform.platform(),
        "pipFreeze": subprocess.check_output([__import__("sys").executable, "-m", "pip", "freeze"], text=True),
        "cmakeCache": cache.read_text(encoding="utf-8", errors="replace"),
    }
    provenance = {"plan": plan, "toolchain": toolchain, "nativeAudit": audit, "builderSha256": digest(__file__)}
    for payload in (engine_payload, model_payload):
        (payload / "PROVENANCE.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
        (payload / "NOTICE.txt").write_text(
            "Optional local AI pack. Engines and weights require separate end-user installation consent.\n"
            "Engine: MIT; weights retain their independently included license and model card.\n"
            "No Python interpreter, FFmpeg or model download client is distributed by these packs.\n"
            "Linux: Ubuntu 22.04 baseline; system glibc/libstdc++/libgcc runtimes required.\n"
            "Windows: x86_64, statically linked MSVC CRT (/MT); only OS DLL dependencies allowed.\n"
            "Compiled with the runner's licensed Visual Studio toolchain on Windows. Runtime and\n"
            "third-party redistribution terms must be reviewed before publishing.\n"
            "Tiny English speech and 0.5B quantized text models have limited accuracy. Verify all output.\n",
            encoding="utf-8")
    engine_metadata = {"id": component, "name": component + ".cpp CPU engine", "version": plan["source"]["version"] + "-cpu-r1",
                       "platform": target, "license": "MIT (vendored notices included)", "executable": "bin/" + executable}
    model_metadata = {"id": component + "_model", "name": "Whisper tiny English" if component == "whisper" else "Qwen2.5 0.5B Instruct Q4_K_M",
                      "version": plan["model"]["version"], "platform": target, "license": plan["model"]["license"],
                      "executable": "models/" + weights.name}
    staging = work / "artifacts"
    engine_pack = create_pack(engine_payload, staging, engine_metadata)
    model_pack = create_pack(model_payload, staging, model_metadata)
    relocated = work / "relocated smoke installation"
    installed_engine = extract_pack(engine_pack["archive"], relocated / "engine", engine_metadata["executable"], True)
    installed_model = extract_pack(model_pack["archive"], relocated / "model", model_metadata["executable"], False)
    if digest(installed_model / model_metadata["executable"]) != plan["model"]["sha256"]:
        raise ValueError("Extracted weights differ from upstream pin")
    # Audit the ZIP-installed binary too, not just the staging binary.
    native_audit(installed_engine / engine_metadata["executable"], target)
    quality = smoke(component, installed_engine / engine_metadata["executable"],
                    installed_model / model_metadata["executable"], source, work / "smoke", ffmpeg)
    shutil.copyfile(__file__, sources / "build_ai_components.py")
    repository = Path(__file__).resolve().parents[1]
    shutil.copyfile(repository / "worker/media_ops.py", sources / "media_ops.py")
    shutil.copyfile(cache, sources / "CMakeCache.txt")
    (sources / "build-plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    checksums = {p.name: {"sha256": digest(p), "bytes": p.stat().st_size} for p in sources.iterdir() if p.is_file()}
    (sources / "SOURCE-CHECKSUMS.json").write_text(json.dumps(checksums, indent=2) + "\n", encoding="utf-8")
    source_archive = Path(shutil.make_archive(str(staging / (Path(engine_pack["archive"]).stem + "-sources")), "zip", sources))
    record = {"engine": engine_pack["manifest"], "model": model_pack["manifest"], "smoke": quality,
              "sources": {"name": source_archive.name, "sha256": digest(source_archive), "bytes": source_archive.stat().st_size}}
    (staging / (Path(engine_pack["archive"]).stem + ".build.json")).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    output.mkdir(parents=True, exist_ok=True)
    for artifact in staging.iterdir():
        destination = output / artifact.name
        if destination.exists():
            raise ValueError(f"Refusing to replace existing artifact: {destination}")
    for artifact in staging.iterdir():
        shutil.copyfile(artifact, output / artifact.name)
    print(json.dumps(record, indent=2))
    return record


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", required=True, choices=sorted(SOURCES))
    parser.add_argument("--platform", required=True, choices=sorted(PLATFORMS))
    parser.add_argument("--work", type=Path, default=Path("build/ai-components"))
    parser.add_argument("--output", type=Path, default=Path("dist/ai-components"))
    parser.add_argument("--plan", action="store_true", help="Print pinned recipe only; no downloads")
    parser.add_argument("--allow-model-downloads", action="store_true", help="Explicit builder/CI consent to fetch both engine source and separate weights")
    parser.add_argument("--ffmpeg", type=Path, help="Runner-only FFmpeg for worker speech smoke (never bundled here)")
    args = parser.parse_args()
    if args.plan:
        print(json.dumps(build_plan(args.component, args.platform), indent=2))
    else:
        build(args.component, args.platform, args.work, args.output, args.allow_model_downloads, args.ffmpeg)


if __name__ == "__main__":
    main()
