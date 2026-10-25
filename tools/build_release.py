"""Build the single-root Bloodstained AP distribution bundle.

The release version comes from the repository's version.toml and the pinned static pak
from release/static_pak_manifest.json (see release_info.py and RELEASING.md).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import zipfile
from pathlib import Path

from build_config import apply_config
from release_info import (
    GENERATED_ASSET_STEMS,
    PAK_MANIFEST,
    ReleaseInfo,
    load_pak_manifest,
    load_pak_pin,
    load_version,
    sha256,
)


FORBIDDEN_GENERATED_ASSETS = tuple(f"/{stem.lower()}." for stem in GENERATED_ASSET_STEMS)
PAID_DLC_PATH_MARKERS = (
    "/dlc_0002/",
    "/classic2",
    "/succubus",
    "/magicgirl",
    "/magicalgirl",
    "/japanese",
)
APWORLD_EXCLUDED_TOP_LEVEL = {"data", "generated", "generators", "test"}


def validate_pak(pak: Path, repak: Path) -> None:
    pin = load_pak_pin()
    actual_hash = sha256(pak)
    if actual_hash != pin.sha256:
        raise ValueError(
            f"static pak hash {actual_hash} does not match the pin in {PAK_MANIFEST}; "
            "pin a reviewed pak with build_static_pak.py --pin (see RELEASING.md)"
        )
    listing = subprocess.run(
        [str(repak), "list", str(pak)], check=True, capture_output=True, text=True
    ).stdout.splitlines()
    paths = [path.strip() for path in listing if path.strip()]
    if len(paths) != pin.file_count:
        raise ValueError(
            f"static pak contains {len(paths)} files, {PAK_MANIFEST} pins {pin.file_count}"
        )
    for path in paths:
        normalized = "/" + path.replace("\\", "/").lower()
        generated_asset = next(
            (asset for asset in FORBIDDEN_GENERATED_ASSETS if asset in normalized), None
        )
        if generated_asset:
            raise ValueError(f"seed-specific generated asset remains in static pak: {path!r}")
        marker = next((marker for marker in PAID_DLC_PATH_MARKERS if marker in normalized), None)
        if marker:
            raise ValueError(f"paid-DLC path {path!r} matched forbidden marker {marker!r}")


def validate_asi(asi: Path, info: ReleaseInfo) -> None:
    # ClientVersion::Display is embedded verbatim; a stale ASI lacks the new version.
    if f"{info.version}\0".encode() not in asi.read_bytes():
        raise ValueError(
            f"{asi} does not contain client version {info.version}; rebuild it with build_mod.py"
        )


def validate_apworld(
    apworld: Path, archipelago_root: Path, python_executable: Path, info: ReleaseInfo
) -> None:
    with zipfile.ZipFile(apworld) as archive:
        manifest_name = next(
            (name for name in archive.namelist() if name.endswith("/archipelago.json")), None
        )
        if not manifest_name:
            raise ValueError("APWorld has no archipelago.json")
        manifest = json.loads(archive.read(manifest_name))
    if manifest.get("world_version") != info.version:
        raise ValueError(
            f"APWorld version is {manifest.get('world_version')!r}, expected {info.version}"
        )
    if manifest.get("minimum_ap_version") != info.min_ap_version:
        raise ValueError(f"APWorld does not require Archipelago {info.min_ap_version}")

    probe = textwrap.dedent(
        """
        import pathlib
        import sys
        import types

        archive, repository = sys.argv[1:]
        worlds = types.ModuleType("worlds")
        worlds.__package__ = "worlds"
        worlds.__path__ = [str(pathlib.Path(repository) / "worlds")]
        sys.modules["worlds"] = worlds
        sys.path.insert(0, repository)
        sys.path.insert(0, archive)

        import bloodstained_rotn

        assert bloodstained_rotn.RitualWorld.game == "Bloodstained: Ritual of the Night"
        """
    )
    result = subprocess.run(
        [str(python_executable), "-c", probe, str(apworld), str(archipelago_root)],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        details = (result.stdout + result.stderr).strip()
        raise ValueError(f"APWorld cannot be imported from its built archive:\n{details}")


def build_apworld(source: Path, output: Path) -> None:
    manifest = json.loads(source.joinpath("archipelago.json").read_text(encoding="utf-8"))
    manifest.update({"compatible_version": 7, "version": 7})
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(source)
            if relative.parts[0] in APWORLD_EXCLUDED_TOP_LEVEL or "__pycache__" in relative.parts:
                continue
            if path.suffix in {".pyc", ".pyo"} or path.name in {".apignore", "archipelago.json"}:
                continue
            archive.write(path, Path(source.name) / relative)
        archive.writestr(Path(source.name, "archipelago.json").as_posix(), json.dumps(manifest))


def write_deterministic_zip(source_root: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source_root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(source_root.parent).as_posix()
            info = zipfile.ZipInfo(relative, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compresslevel=9)


def main() -> None:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--asi", type=Path, default=repository / "x64/Release/BloodstainedAP.asi")
    parser.add_argument("--pak", type=Path, required=True, help="Pinned developer reference pak")
    parser.add_argument("--repak", type=Path, required=True)
    parser.add_argument("--loader", type=Path, required=True, help="Ultimate ASI Loader renamed winhttp.dll")
    parser.add_argument(
        "--archipelago-root",
        type=Path,
        default=repository.parent / "BloodstainedAP",
        help="Archipelago source tree used to smoke-test the built APWorld",
    )
    parser.add_argument(
        "--archipelago-python",
        type=Path,
        help="Python interpreter with Archipelago's dependencies (defaults to its .venv when present)",
    )
    parser.add_argument(
        "--true-randomizer-license",
        type=Path,
        default=repository.parents[1] / "randomizer/True-Randomization/LICENSE",
        help="License for the True Randomizer-derived static pak",
    )
    parser.add_argument(
        "--asi-loader-license",
        type=Path,
        default=repository.parents[1] / "tools/Ultimate-ASI-Loader-source/license",
        help="License for the Ultimate ASI Loader",
    )
    apworld_source = parser.add_mutually_exclusive_group(required=True)
    apworld_source.add_argument("--apworld", type=Path)
    apworld_source.add_argument("--world-source", type=Path, help="Loose worlds/bloodstained_rotn directory")
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Bundle .zip path, or a directory to receive BloodstainedAP-<version>[-<label>].zip",
    )
    parser.add_argument("--package-label", help="Test-package label recorded in README and manifest")
    apply_config(parser, "release")
    args = parser.parse_args()

    for path in (
        args.asi,
        args.pak,
        args.repak,
        args.loader,
        args.asi_loader_license,
        args.true_randomizer_license,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)
    if not args.archipelago_root.joinpath("worlds", "AutoWorld.py").is_file():
        raise FileNotFoundError(f"not an Archipelago source tree: {args.archipelago_root}")
    if args.archipelago_python is None:
        venv_python = args.archipelago_root / ".venv" / "Scripts" / "python.exe"
        args.archipelago_python = venv_python if venv_python.is_file() else Path(sys.executable)
    if not args.archipelago_python.is_file():
        raise FileNotFoundError(args.archipelago_python)
    info = load_version()
    root_name = f"BloodstainedAP-{info.version}"
    package_name = f"{root_name}-{args.package_label}" if args.package_label else root_name
    output = args.output if args.output.suffix == ".zip" else args.output / f"{package_name}.zip"
    validate_pak(args.pak, args.repak)
    validate_asi(args.asi, info)

    with tempfile.TemporaryDirectory(prefix="bloodstained-ap-release-") as temporary:
        temporary_path = Path(temporary)
        if args.world_source:
            if not args.world_source.is_dir():
                raise FileNotFoundError(args.world_source)
            apworld_path = temporary_path / "bloodstained_rotn.apworld"
            build_apworld(args.world_source, apworld_path)
        else:
            if not args.apworld.is_file():
                raise FileNotFoundError(args.apworld)
            apworld_path = args.apworld
        validate_apworld(apworld_path, args.archipelago_root, args.archipelago_python, info)

        root = Path(temporary) / root_name
        game_binary = root / "Game/BloodstainedRotN/Binaries/Win64"
        mod_paks = root / "Game/BloodstainedRotN/Content/Paks/~mods"
        archipelago = root / "Archipelago"
        game_binary.joinpath("plugins").mkdir(parents=True)
        mod_paks.mkdir(parents=True)
        archipelago.mkdir(parents=True)
        shutil.copy2(args.asi, game_binary / "plugins/BloodstainedAP.asi")
        shutil.copy2(args.loader, game_binary / "winhttp.dll")
        shutil.copy2(args.pak, mod_paks / "BloodstainedAP.pak")
        shutil.copy2(apworld_path, archipelago / "bloodstained_rotn.apworld")
        readme = repository.joinpath("release/README.txt").read_text(encoding="utf-8").format(
            version=info.version,
            min_ap_version=info.min_ap_version,
            package_suffix=f" {args.package_label} package" if args.package_label else "",
        )
        root.joinpath("README.txt").write_text(readme, encoding="utf-8")
        pak_manifest = {"package_version": info.version, **load_pak_manifest()}
        root.joinpath("static_pak_manifest.json").write_text(
            json.dumps(pak_manifest, indent=2) + "\n", encoding="utf-8"
        )
        shutil.copy2(repository / "LICENSE.txt", root / "LICENSE-BloodstainedAPClient.txt")
        shutil.copy2(args.asi_loader_license, root / "LICENSE-Ultimate-ASI-Loader.txt")
        shutil.copy2(args.true_randomizer_license, root / "LICENSE-True-Randomizer.txt")

        manifest = {
            "package": package_name,
            "client_world_version": info.version,
            "required_archipelago_version": info.min_ap_version,
            "test_build": bool(args.package_label),
            "files": {
                "Game/BloodstainedRotN/Binaries/Win64/plugins/BloodstainedAP.asi": sha256(
                    game_binary / "plugins/BloodstainedAP.asi"
                ),
                "Game/BloodstainedRotN/Content/Paks/~mods/BloodstainedAP.pak": sha256(
                    mod_paks / "BloodstainedAP.pak"
                ),
                "Game/BloodstainedRotN/Binaries/Win64/winhttp.dll": sha256(
                    game_binary / "winhttp.dll"
                ),
                "Archipelago/bloodstained_rotn.apworld": sha256(
                    archipelago / "bloodstained_rotn.apworld"
                ),
            },
        }
        root.joinpath("manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        write_deterministic_zip(root, output)

    print(f"Built {output}")
    print(f"SHA-256: {sha256(output)}")


if __name__ == "__main__":
    main()
