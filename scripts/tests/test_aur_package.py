"""AUR recipe rendering and publishing; makepkg/namcap/app smoke run in CI's Arch container."""
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
aur = runpy.run_path(str(ROOT / "scripts" / "aur_package.py"))


def test_release_tags_map_to_pkgver_that_sorts_prereleases_before_final():
    assert aur["pkgver_from_tag"]("v0.1.0") == "0.1.0"
    assert aur["pkgver_from_tag"]("v0.1.0-rc.2") == "0.1.0rc2"
    assert aur["pkgver_from_tag"]("v1.20.3-beta.10") == "1.20.3beta10"
    for tag in ("0.1.0", "v0.1", "v0.1.0-rc2", "v0.1.0-preview.1", "v01.1.0", "v0.1.0\n", "components-v0.1.0"):
        with pytest.raises(ValueError, match="release tag"):
            aur["pkgver_from_tag"](tag)


APPIMAGE_SHA = "16b0ebe4484820754224d1850a847990626e4c9e7a35cb7b5ac5b31c638761ca"
DOWNLOADS = "https://github.com/ClawPick2026/paperwork-desktop/releases/download/"


def github_release(tag="v0.1.0-rc.2", digest="sha256:" + APPIMAGE_SHA, name="Leafsmith_0.1.0_amd64.AppImage", **extra):
    """Shape of GET /repos/{repo}/releases/tags/{tag}, trimmed to the fields used."""
    assets = [{"name": "Leafsmith_0.1.0_x64-setup.exe", "browser_download_url": DOWNLOADS + tag + "/Leafsmith_0.1.0_x64-setup.exe",
               "size": 34073800, "digest": "sha256:" + "f" * 64},
              {"name": "SHA256SUMS-linux-x86_64.txt", "browser_download_url": DOWNLOADS + tag + "/SHA256SUMS-linux-x86_64.txt",
               "size": 318, "digest": "sha256:" + "0" * 64}]
    if name:
        assets.append({"name": name, "browser_download_url": DOWNLOADS + tag + "/" + name, "size": 139901432, "digest": digest})
    return {"tag_name": tag, "draft": False, "prerelease": "-" in tag,
            "html_url": "https://github.com/ClawPick2026/paperwork-desktop/releases/tag/" + tag, "assets": assets, **extra}


SUMS = f"{APPIMAGE_SHA}  Leafsmith_0.1.0_amd64.AppImage\n{'1' * 64}  Leafsmith-linux-corresponding-sources.zip\n"


def test_release_artifact_pins_the_appimage_only_when_checksum_sources_agree():
    assert aur["release_artifact"](github_release(), SUMS) == {
        "tag": "v0.1.0-rc.2", "pkgver": "0.1.0rc2", "prerelease": True,
        "release_url": "https://github.com/ClawPick2026/paperwork-desktop/releases/tag/v0.1.0-rc.2",
        "appimage": "Leafsmith_0.1.0_amd64.AppImage", "sha256": APPIMAGE_SHA, "size": 139901432}
    # Assets uploaded before GitHub recorded digests rely on the checked list alone.
    assert aur["release_artifact"](github_release(digest=None), SUMS)["sha256"] == APPIMAGE_SHA
    rejected = {
        "digest": (github_release(digest="sha256:" + "a" * 64), SUMS),
        "not in the checksum list": (github_release(), SUMS.replace("Leafsmith_0.1.0_amd64", "Other")),
        "exactly one": (github_release(name=None), SUMS),
        "does not match": (github_release(name="Leafsmith_0.2.0_amd64.AppImage"), SUMS.replace("0.1.0_amd64", "0.2.0_amd64")),
        "draft": (github_release(draft=True), SUMS),
        "release tag": (github_release(tag="components-v0.1.0"), SUMS),
        # Releases built before the Paperwork -> Leafsmith rename.
        "does not match release": (github_release(name="Paperwork_0.1.0_amd64.AppImage"), SUMS.replace("Leafsmith_0.1.0", "Paperwork_0.1.0")),
    }
    for message, (release, sums) in rejected.items():
        with pytest.raises(ValueError, match=message):
            aur["release_artifact"](release, sums)
    moved = github_release()
    moved["assets"][-1]["browser_download_url"] = "https://example.com/Leafsmith_0.1.0_amd64.AppImage"
    with pytest.raises(ValueError, match="download URL"):
        aur["release_artifact"](moved, SUMS)


MAINTAINER = "Jane Doe <jane at example dot org>"


def fake_srcinfo(directory):
    """Outside Arch, stand in for makepkg --printsrcinfo with the sourced values."""
    return bash_values(directory / "PKGBUILD", "pkgbase = $pkgname", "pkgver = $pkgver", "pkgrel = $pkgrel",
                       "source = ${source[0]}", "sha256sums = ${sha256sums[0]}", "pkgname = $pkgname")


def bash_values(pkgbuild, *expressions):
    script = 'set -eu; source "$1"; shift; for e in "$@"; do eval "v=\\"$e\\""; printf "%s\\n" "$v"; done'
    return subprocess.run(["bash", "-c", script, "bash", str(pkgbuild), *expressions],
                          check=True, capture_output=True, text=True).stdout


def write(directory, files):
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (directory / name).write_bytes(content)
    return directory


def test_render_pins_release_appimage_and_local_sources(tmp_path):
    artifact = aur["release_artifact"](github_release(), SUMS)
    files = aur["render"](artifact, MAINTAINER, 3, srcinfo=fake_srcinfo)
    assert set(files) == {"PKGBUILD", ".SRCINFO", "leafsmith.sh", "leafsmith.desktop"}
    package = write(tmp_path / "package", files)
    pkgbuild = files["PKGBUILD"].decode()
    assert pkgbuild.startswith("# Maintainer: " + MAINTAINER + "\n")
    assert "@" not in pkgbuild.replace(MAINTAINER, "")
    assert bash_values(package / "PKGBUILD", "$pkgname", "$pkgver", "$pkgrel", "${#source[@]}", "${source[0]}", "${sha256sums[*]}").splitlines() == [
        "leafsmith-bin", "0.1.0rc2", "3", "3",
        "leafsmith-0.1.0rc2.AppImage::" + DOWNLOADS + "v0.1.0-rc.2/Leafsmith_0.1.0_amd64.AppImage",
        " ".join([APPIMAGE_SHA, *(hashlib.sha256(files[n]).hexdigest() for n in ("leafsmith.sh", "leafsmith.desktop"))])]
    assert files[".SRCINFO"] == fake_srcinfo(package).encode()
    subprocess.run(["bash", "-n", str(package / "leafsmith.sh")], check=True)
    if shutil.which("desktop-file-validate"):
        subprocess.run(["desktop-file-validate", str(package / "leafsmith.desktop")], check=True)
    for maintainer in ("Jane Doe", "Jane <jane@example.org>\npkgver=9", "<jane@example.org>", "Jane $(id) <j@example.org>"):
        with pytest.raises(ValueError, match="maintainer"):
            aur["render"](artifact, maintainer, 1, srcinfo=fake_srcinfo)


ORDER = ["0.1.0rc1", "0.1.0rc2", "0.1.0rc10", "0.1.0", "0.2.0"]


def fake_vercmp(a, b):
    """Ordering that the real-vercmp test below checks against pacman in CI."""
    return (ORDER.index(a) > ORDER.index(b)) - (ORDER.index(a) < ORDER.index(b))


def git(directory, *args):
    return subprocess.run(["git", "-C", str(directory), *args], check=True, capture_output=True, text=True).stdout.strip()


def fake_aur(tmp_path):
    remote = tmp_path / "aur.git"
    subprocess.run(["git", "init", "--quiet", "--bare", "--initial-branch=master", str(remote)], check=True)
    return remote


def push_to_aur(remote, tmp_path, files, message="Upload"):
    """Stand-in for a maintainer's push, so the next plan sees published files."""
    checkout = tmp_path / ("checkout-" + hashlib.sha256(message.encode()).hexdigest()[:8])
    subprocess.run(["git", "clone", "--quiet", str(remote), str(checkout)], check=True, capture_output=True)
    git(checkout, "checkout", "--quiet", "-B", "master")
    for path in checkout.iterdir():
        if path.name != ".git":
            path.unlink()
    write(checkout, files)
    git(checkout, "add", "--all")
    git(checkout, "-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "--quiet", "-m", message)
    git(checkout, "push", "--quiet", "origin", "HEAD:master")
    return git(checkout, "rev-parse", "HEAD")


def plan(artifact, remote, out, maintainer=MAINTAINER):
    return aur["plan"](artifact, maintainer, str(remote), out, vercmp=fake_vercmp, srcinfo=fake_srcinfo)


def test_plan_uploads_new_versions_bumps_pkgrel_for_recipe_changes_and_never_downgrades(tmp_path):
    rc2 = aur["release_artifact"](github_release(), SUMS)
    remote = fake_aur(tmp_path)

    first = plan(rc2, remote, tmp_path / "first")
    assert {k: first[k] for k in ("action", "pkgver", "pkgrel", "aur_head", "aur_version")} == {
        "action": "publish", "pkgver": "0.1.0rc2", "pkgrel": 1, "aur_head": "", "aur_version": None}
    package = {name: (tmp_path / "first/package" / name).read_bytes() for name in sorted(first["files"])}
    assert sorted(package) == sorted(aur["PACKAGE_FILES"])
    assert first["files"] == {name: hashlib.sha256(content).hexdigest() for name, content in package.items()}
    assert json.loads((tmp_path / "first/plan.json").read_text()) == first
    head = push_to_aur(remote, tmp_path, package)

    again = plan(rc2, remote, tmp_path / "again")
    assert (again["action"], again["pkgrel"], again["aur_head"], again["aur_version"]) == ("unchanged", 1, head, "0.1.0rc2-1")

    # A recipe change for the same release is a new pkgrel of the same pkgver.
    changed = plan(rc2, remote, tmp_path / "changed", maintainer="Other Person <other at example dot org>")
    assert (changed["action"], changed["pkgver"], changed["pkgrel"]) == ("publish", "0.1.0rc2", 2)
    assert "pkgrel=2\n" in (tmp_path / "changed/package/PKGBUILD").read_text()

    older = github_release(tag="v0.1.0-rc.1")
    older = plan(aur["release_artifact"](older, SUMS), remote, tmp_path / "older")
    assert (older["action"], older["pkgrel"], older["aur_version"]) == ("older", 1, "0.1.0rc2-1")
    # Still rendered, so recipe changes are built and checked; publish refuses it.
    assert sorted(older["files"]) == sorted(aur["PACKAGE_FILES"])
    assert "pkgver=0.1.0rc1\n" in (tmp_path / "older/package/PKGBUILD").read_text()
    assert aur["publish"](tmp_path / "older", str(remote), MAINTAINER) is False

    newer = github_release(tag="v0.1.0")
    newer = plan(aur["release_artifact"](newer, SUMS), remote, tmp_path / "newer")
    assert (newer["action"], newer["pkgver"], newer["pkgrel"], newer["aur_head"]) == ("publish", "0.1.0", 1, head)


def test_plan_refuses_an_aur_repository_for_another_package(tmp_path):
    remote = fake_aur(tmp_path)
    push_to_aur(remote, tmp_path, {".SRCINFO": b"pkgbase = something-else\n\tpkgver = 1\n\tpkgrel = 1\n\npkgname = something-else\n",
                                   "PKGBUILD": b"pkgname=something-else\n"})
    with pytest.raises(ValueError, match="something-else"):
        plan(aur["release_artifact"](github_release(), SUMS), remote, tmp_path / "out")


WORKER = "opt/leafsmith/usr/lib/Leafsmith/worker/_internal/"
HOSTED = "/opt/hostedtoolcache/Python/3.12.15/x64/lib"


def test_namcap_gate_fails_on_every_error_except_the_reviewed_worker_runpath():
    reviewed = [f"leafsmith-bin E: insecure-runpath {HOSTED} {WORKER}libpython3.12.so.1.0",
                f"leafsmith-bin E: insecure-runpath {HOSTED} {WORKER}python3.12/lib-dynload/_bz2.cpython-312-x86_64-linux-gnu.so"]
    output = "\n".join(["leafsmith-bin W: dependency-detected-not-included libx11 (libraries ['usr/lib/libX11.so.6'] needed in files ['x'])",
                        *reviewed, "PKGBUILD (leafsmith-bin) W: missing-contributor", ""])
    assert aur["namcap_errors"](output) == ([], reviewed)
    for error in (f"leafsmith-bin E: insecure-runpath {HOSTED} opt/leafsmith/usr/bin/leafsmith",
                  f"leafsmith-bin E: insecure-runpath /home/runner/lib {WORKER}libpython3.12.so.1.0",
                  f"leafsmith-bin E: insecure-rpath {HOSTED} {WORKER}libpython3.12.so.1.0",
                  "PKGBUILD (leafsmith-bin) E: missing-license",
                  "leafsmith-bin E: dangling-symlink usr/share/licenses/x points to /nowhere"):
        assert aur["namcap_errors"](output + error + "\n") == ([error], reviewed)


def aur_files(remote, directory):
    subprocess.run(["git", "clone", "--quiet", str(remote), str(directory)], check=True, capture_output=True)
    return {p.name: p.read_bytes() for p in directory.iterdir() if p.name != ".git"}


def test_publish_pushes_exactly_the_validated_plan_and_refuses_a_moved_aur_or_altered_files(tmp_path):
    remote = fake_aur(tmp_path)
    rc1 = aur["release_artifact"](github_release(tag="v0.1.0-rc.1"), SUMS)
    base = push_to_aur(remote, tmp_path, {**aur["render"](rc1, MAINTAINER, 1, srcinfo=fake_srcinfo), "notes.txt": b"manual"})
    rc2 = aur["release_artifact"](github_release(), SUMS)
    planned = plan(rc2, remote, tmp_path / "rc2")

    assert aur["publish"](tmp_path / "rc2", str(remote), MAINTAINER) is True
    assert aur_files(remote, tmp_path / "after") == {n: (tmp_path / "rc2/package" / n).read_bytes() for n in planned["files"]}
    assert git(tmp_path / "after", "log", "-1", "--format=%an|%ae|%P|%s") == f"Jane Doe|jane at example dot org|{base}|Update to 0.1.0rc2-1"
    assert git(tmp_path / "after", "log", "-1", "--format=%b") == "Release v0.1.0-rc.2: " + rc2["release_url"]

    # A second run for the same release finds its files already published.
    assert aur["publish"](tmp_path / "rc2", str(remote), MAINTAINER) is False
    final = aur["release_artifact"](github_release(tag="v0.1.0"), SUMS)
    plan(final, remote, tmp_path / "final")
    (tmp_path / "final/package/PKGBUILD").write_text("pkgname=tampered\n")
    with pytest.raises(ValueError, match="plan"):
        aur["publish"](tmp_path / "final", str(remote), MAINTAINER)
    assert plan(rc2, remote, tmp_path / "same")["action"] == "unchanged"
    assert aur["publish"](tmp_path / "same", str(remote), MAINTAINER) is False

    plan(final, remote, tmp_path / "moved")
    push_to_aur(remote, tmp_path, {**aur_files(remote, tmp_path / "manual"), "notes.txt": b"manual"}, "Manual edit")
    with pytest.raises(ValueError, match="AUR changed"):
        aur["publish"](tmp_path / "moved", str(remote), MAINTAINER)


def test_first_publish_creates_the_aur_master_branch(tmp_path):
    remote = fake_aur(tmp_path)
    plan(aur["release_artifact"](github_release(), SUMS), remote, tmp_path / "out")
    assert aur["publish"](tmp_path / "out", str(remote), MAINTAINER) is True
    assert sorted(aur_files(remote, tmp_path / "after")) == sorted(aur["PACKAGE_FILES"])
    assert git(tmp_path / "after", "log", "--format=%s") == "Initial upload: 0.1.0rc2-1"


def test_a_rejected_aur_push_reports_the_servers_reason(tmp_path):
    remote = fake_aur(tmp_path)
    hook = remote / "hooks/pre-receive"
    hook.write_text("#!/bin/sh\necho 'error: The package base is owned by someone else' >&2\nexit 1\n")
    hook.chmod(0o755)
    plan(aur["release_artifact"](github_release(), SUMS), remote, tmp_path / "out")
    with pytest.raises(RuntimeError, match="owned by someone else"):
        aur["publish"](tmp_path / "out", str(remote), MAINTAINER)


def test_without_a_tag_the_newest_published_release_with_a_leafsmith_appimage_is_packaged():
    components = {"tag_name": "components-v0.1.0", "draft": False, "assets": [{"name": "tesseract.zip"}]}
    paperwork = github_release(tag="v0.1.0-rc.3", name="Paperwork_0.1.0_amd64.AppImage")
    releases = [github_release(tag="v0.2.0-rc.1", draft=True), components, paperwork, github_release(), github_release(tag="v0.1.0-rc.1")]
    assert aur["latest_appimage_release"](releases)["tag_name"] == "v0.1.0-rc.2"
    # Before the first Leafsmith release there is nothing to package yet.
    assert aur["latest_appimage_release"]([components, paperwork]) is None


def test_fetch_release_without_an_eligible_release_writes_nothing_and_succeeds(tmp_path, monkeypatch, capsys):
    paperwork = github_release(tag="v0.1.0-rc.2", name="Paperwork_0.1.0_amd64.AppImage")
    monkeypatch.setitem(aur["main"].__globals__, "github_json", lambda url, token: [paperwork])
    out = tmp_path / "release.json"
    assert aur["main"](["fetch-release", "--out", str(out)]) == 0
    assert not out.exists()
    assert "No published release has a Leafsmith_<version>_amd64.AppImage yet" in capsys.readouterr().out


def test_namcap_gate_fails_when_namcap_could_not_read_its_input():
    # namcap prints this and still exits 0.
    line = "Error: build/aur/leafsmith-bin.pkg.tar.zst not package or PKGBUILD"
    assert aur["namcap_errors"](line + "\n") == ([line], [])


@pytest.mark.skipif(not shutil.which("vercmp"), reason="pacman's vercmp runs in CI's Arch container")
def test_pacman_orders_mapped_tags_in_release_order():
    tags = ("v0.1.0-alpha.1", "v0.1.0-beta.2", "v0.1.0-rc.2", "v0.1.0-rc.10", "v0.1.0", "v0.1.1-rc.1", "v0.1.1", "v0.2.0", "v0.10.0")
    versions = [aur["pkgver_from_tag"](tag) for tag in tags]
    for older, newer in [*zip(versions, versions[1:]), *zip(ORDER, ORDER[1:])]:
        assert (aur["pacman_vercmp"](older, newer), aur["pacman_vercmp"](newer, older)) == (-1, 1), (older, newer)


@pytest.mark.skipif(not shutil.which("makepkg"), reason="makepkg runs in CI's Arch container")
def test_makepkg_reads_the_rendered_recipe():
    files = aur["render"](aur["release_artifact"](github_release(), SUMS), MAINTAINER, 2)
    srcinfo = files[".SRCINFO"].decode()
    assert aur["srcinfo_version"](srcinfo) == ("0.1.0rc2", 2)
    for line in ("source = leafsmith-0.1.0rc2.AppImage::" + DOWNLOADS + "v0.1.0-rc.2/Leafsmith_0.1.0_amd64.AppImage",
                 "sha256sums = " + APPIMAGE_SHA, "depends = libglvnd", "options = !strip"):
        assert "\t" + line + "\n" in srcinfo
    assert "webkit2gtk" not in srcinfo  # bundled in the AppImage


def test_namcap_gate_accepts_opt_and_dependency_reports_only_for_what_the_bundle_ships():
    bundled = {"libz.so.1", "libpng16.so.16"}  # file names shipped under opt/leafsmith/
    lib = ("leafsmith-bin E: dependency-detected-not-included zlib (libraries-needed ['usr/lib/libz.so.1'] "
           "['opt/leafsmith/usr/lib/libpng16.so.16', 'opt/leafsmith/usr/lib/libfreetype.so.6'])")
    python = ("leafsmith-bin E: dependency-detected-not-included python (python-modules-needed ['json', 'ctypes'] "
              f"['{WORKER}pptx/util.py'], python-modules-needed ['zlib'] ['{WORKER}pypdfium2/raw.py'])")
    opt = "leafsmith-bin E: elffile-in-questionable-dirs opt/"
    assert aur["namcap_errors"]("\n".join([lib, python, opt]), bundled) == ([], [lib, python, opt])
    for line in (
            # A host library the bundle does not ship must be declared in depends.
            "leafsmith-bin E: dependency-detected-not-included libxkbcommon (libraries-needed "
            "['usr/lib/libxkbcommon.so.0'] ['opt/leafsmith/usr/lib/libgtk-3.so.0'])",
            lib.replace("'opt/leafsmith/usr/lib/libfreetype.so.6'", "'usr/bin/leafsmith'"),
            lib.replace("libpng16.so.16'", "../../../usr/lib/libpng16.so.16'"),
            python.replace(WORKER, "opt/leafsmith/usr/share/"),
            lib[:-1] + ", programs-needed ['python3'] ['opt/leafsmith/usr/bin/tool'])",
            "leafsmith-bin E: dependency-detected-not-included dconf (dconf-needed-for-glib-schemas)",
            "leafsmith-bin E: elffile-not-in-allowed-dirs usr/share/leafsmith/tool"):
        assert aur["namcap_errors"](line, bundled) == ([line], []), line
