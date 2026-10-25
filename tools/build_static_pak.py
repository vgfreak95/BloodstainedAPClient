#!/usr/bin/env python3
"""Build the pinned static pak without dropping local cooked-asset patches.

The pinned SHA-256 and file count live in release/static_pak_manifest.json; --pin
records a reviewed build there (see release_info.py and RELEASING.md).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from build_ap_base import PROFILE
from build_config import apply_config
from release_info import GENERATED_ASSET_STEMS, PAK_MANIFEST, PakPin, load_pak_pin, sha256, write_pak_pin


VANILLA_OVERLAYS = (
    "BloodstainedRotN/Content/Core/UI/Map/MapManageBlueprint.uasset",
    "BloodstainedRotN/Content/Core/UI/Map/MapManageBlueprint.uexp",
    # Keep the vanilla minimap Blueprint in the override pak. The native client owns
    # AP marker rendering; this prevents stale True Randomizer UI bytecode resurfacing.
    "BloodstainedRotN/Content/Core/UI/Map/MiniMapBlueprint.uasset",
    "BloodstainedRotN/Content/Core/UI/Map/MiniMapBlueprint.uexp",
    "BloodstainedRotN/Content/Core/System/PBBookManager_BP.uasset",
    "BloodstainedRotN/Content/Core/System/PBBookManager_BP.uexp",
    # Start from the current vanilla room and apply only the AP-controlled gate.
    "BloodstainedRotN/Content/Core/Environment/ACT02_VIL/Level/m02VIL_005_Gimmick.umap",
    "BloodstainedRotN/Content/Core/Environment/ACT02_VIL/Level/m02VIL_005_Gimmick.uexp",
)

REQUIRED_OUTPUTS = VANILLA_OVERLAYS + (
    "BloodstainedRotN/Content/Core/Environment/ACT01_SIP/Level/m01SIP_004_Gimmick.umap",
    "BloodstainedRotN/Content/Core/Environment/ACT01_SIP/Level/m01SIP_004_Gimmick.uexp",
    "BloodstainedRotN/Content/Core/Environment/ACT01_SIP/Level/m01SIP_025_Gimmick.umap",
    "BloodstainedRotN/Content/Core/Environment/ACT01_SIP/Level/m01SIP_025_Gimmick.uexp",
    "BloodstainedRotN/Content/Archipelago/UI/AP_WallMarker.uasset",
    "BloodstainedRotN/Content/Archipelago/UI/AP_WallMarker.uexp",
)

RUNTIME_MARKER_STEMS = ("AP_ChestMarker", "AP_ShardMarker")
MARKER_DONOR = "BloodstainedRotN/Content/Core/UI/K2C/icon_8bitCrown.uasset"
MARKER_OUTPUT_DIR = "BloodstainedRotN/Content/Archipelago/UI"
PAK_VERSION = "V8A"
PAK_COMPRESSION = "Zlib"


def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
    print("+", subprocess.list2cmdline(command))
    return subprocess.run(command, check=True, **kwargs)


def remove_seed_specific_assets(stage: Path) -> None:
    for path in stage.rglob("*"):
        if path.is_file() and path.stem in GENERATED_ASSET_STEMS + RUNTIME_MARKER_STEMS:
            path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--source-pak", type=Path,
                        help="Clean True Randomizer-derived static pak input")
    inputs.add_argument("--true-randomizer-dir", type=Path,
                        help="Build an experimental AP-only base directly from pinned TR source")
    parser.add_argument("--baseline-pak", type=Path,
                        help="Required with TR source: existing shipped pak to audit against")
    parser.add_argument("--game-pak", type=Path, required=True,
                        help="Vanilla pakchunk0-WindowsNoEditor.pak")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repak", type=Path, required=True)
    parser.add_argument("--uasset-api-dir", type=Path, required=True)
    parser.add_argument("--ue4-dds-tools-dir", type=Path, required=True)
    parser.add_argument("--dotnet", default="dotnet")
    parser.add_argument("--keep-workdir", action="store_true")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite an existing output and its .base.json/.audit.json")
    parser.add_argument("--pin", action="store_true",
                        help=f"Record the reviewed output as the pinned pak in {PAK_MANIFEST.name}"
                             " and regenerate Mod/StaticPakPin.h")
    parser.add_argument("--update-profile", action="store_true",
                        help="TR source only: rewrite final_files in ap_base_profile.json from this "
                             "build after reviewing the audit, instead of failing on a difference")
    apply_config(parser, "static_pak")
    args = parser.parse_args()

    for path in (args.source_pak, args.baseline_pak, args.game_pak, args.repak):
        if path is None:
            continue
        if not path.is_file():
            parser.error(f"missing file: {path}")
    if args.true_randomizer_dir:
        if not args.baseline_pak:
            parser.error("--true-randomizer-dir requires --baseline-pak")
        if args.output.exists() and not args.force:
            parser.error("experimental output must be a new candidate path (or pass --force)")
    elif args.update_profile:
        parser.error("--update-profile requires --true-randomizer-dir")
    if args.force:
        for stale in (args.output, args.output.with_suffix(".base.json"),
                      args.output.with_suffix(".audit.json")):
            stale.unlink(missing_ok=True)
    args.output = args.output.resolve()
    args.game_pak = args.game_pak.resolve()
    args.repak = args.repak.resolve()
    args.uasset_api_dir = args.uasset_api_dir.resolve()
    args.ue4_dds_tools_dir = args.ue4_dds_tools_dir.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for dll in ("UAssetAPI.dll", "UAssetSnippet.dll", "Newtonsoft.Json.dll"):
        if not (args.uasset_api_dir / dll).is_file():
            parser.error(f"missing dependency: {args.uasset_api_dir / dll}")
    if not (args.ue4_dds_tools_dir / "main.py").is_file():
        parser.error(f"missing UE4-DDS-Tools package: {args.ue4_dds_tools_dir}")

    work = Path(tempfile.mkdtemp(prefix="bloodstained-static-pak-",
                                 dir=args.output.resolve().parent))
    stage = work / "stage"
    try:
        baseline_files = None
        if args.true_randomizer_dir:
            # Audit the existing artifact before generating a replacement candidate.
            from pyuepak import PakFile
            baseline = PakFile()
            baseline.read(str(args.baseline_pak.resolve()))
            baseline_files = {name: hashlib.sha256(baseline.read_file(name)).hexdigest()
                              for name in sorted(baseline.list_files())}
            run([sys.executable, str(Path(__file__).with_name("build_ap_base.py")),
                 "--true-randomizer-dir", str(args.true_randomizer_dir.resolve()),
                 "--game-pak", str(args.game_pak), "--output-dir", str(stage),
                 "--report", str(args.output.with_suffix(".base.json"))])
        else:
            run([str(args.repak), "unpack", "-q", "-o", str(stage), str(args.source_pak)])
        overlay_command = [str(args.repak), "unpack", "-q", "-f", "-o", str(stage)]
        for asset in VANILLA_OVERLAYS:
            overlay_command.extend(("-i", asset))
        overlay_command.append(str(args.game_pak))
        run(overlay_command)
        remove_seed_specific_assets(stage)

        project = Path(__file__).with_name("static_pak_patcher") / "StaticPakPatcher.csproj"
        nuget_config = project.with_name("NuGet.Config")
        run([
            args.dotnet, "restore", str(project), "--configfile", str(nuget_config),
            f"-p:UAssetApiDir={args.uasset_api_dir}",
        ])
        run([
            args.dotnet, "run", "--no-restore", "--project", str(project),
            f"-p:UAssetApiDir={args.uasset_api_dir}", "--", str(stage),
        ])
        marker_cooker = Path(__file__).with_name("cook_marker_textures.py")
        marker_donor = stage / MARKER_DONOR
        marker_output = stage / MARKER_OUTPUT_DIR
        marker_env = dict(os.environ, TEMP=str(work), TMP=str(work))
        run([
            sys.executable, str(marker_cooker), "--donor", str(marker_donor),
            "--png-dir", str(Path(__file__).parents[1] / "Assets"),
            "--output-dir", str(marker_output),
            "--ue4-dds-tools-dir", str(args.ue4_dds_tools_dir),
        ], env=marker_env)
        if args.true_randomizer_dir:
            # The vanilla crown is a build donor, not an AP override.
            for donor_file in marker_donor.parent.glob(marker_donor.stem + ".*"):
                donor_file.unlink()

        missing = [asset for asset in REQUIRED_OUTPUTS if not (stage / asset).is_file()]
        if missing:
            raise RuntimeError(f"static pak build is missing required assets: {missing}")

        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary_output = work / "BloodstainedAP.pak"
        pack_env = dict(os.environ)
        if args.true_randomizer_dir:
            # repak's parallel writer otherwise produces varying archive order.
            pack_env["RAYON_NUM_THREADS"] = "1"
        run([
            str(args.repak), "pack", "-q", "--version", PAK_VERSION,
            "--compression", PAK_COMPRESSION, str(stage), str(temporary_output),
        ], env=pack_env)
        listing = run([str(args.repak), "list", str(temporary_output)],
                      capture_output=True, text=True).stdout.splitlines()
        if any(Path(asset).stem in RUNTIME_MARKER_STEMS for asset in listing):
            raise RuntimeError("static pak contains a runtime-generated chest or shard texture")
        if baseline_files is not None:
            files = {p.relative_to(stage).as_posix(): sha256(p)
                     for p in sorted(stage.rglob("*")) if p.is_file()}
            if set(listing) != set(files):
                raise RuntimeError("Packed file inventory differs from staging inventory")
            profile = json.loads(PROFILE.read_text())
            if files != profile["final_files"]:
                if not args.update_profile:
                    raise RuntimeError("Final AP payload differs from the experimental profile; "
                                       "review the audit, then rerun with --update-profile")
                profile["final_files"] = files
                PROFILE.write_text(json.dumps(profile, indent=2) + "\n")
                print(f"updated final_files in {PROFILE}")
            packed = PakFile()
            packed.read(str(temporary_output))
            for name, expected in files.items():
                if hashlib.sha256(packed.read_file(name)).hexdigest() != expected:
                    raise RuntimeError(f"Packed payload mismatch: {name}")
            audit = {
                "status": "experimental; gameplay validation required before adoption",
                "baseline_sha256": sha256(args.baseline_pak),
                "candidate_sha256": sha256(temporary_output),
                "identical": sorted(n for n in files.keys() & baseline_files.keys() if files[n] == baseline_files[n]),
                "changed": sorted(n for n in files.keys() & baseline_files.keys() if files[n] != baseline_files[n]),
                "removed": sorted(baseline_files.keys() - files.keys()),
                "added": sorted(files.keys() - baseline_files.keys()),
                "files": files,
            }
            args.output.with_suffix(".audit.json").write_text(json.dumps(audit, indent=2) + "\n")
        shutil.copy2(temporary_output, args.output)
        built = PakPin(sha256(args.output), len(listing))
        print(f"built {args.output} ({built.file_count} files, sha256={built.sha256})")
        if args.pin:
            write_pak_pin(built)
            print(f"pinned in {PAK_MANIFEST}; rebuild the ASI with build_mod.py")
        elif built == load_pak_pin():
            print(f"matches the pin in {PAK_MANIFEST}")
        else:
            print(f"differs from the pin in {PAK_MANIFEST}; after review, rerun with --pin")
        return 0
    finally:
        if args.keep_workdir:
            print(f"kept work directory: {work}")
        else:
            shutil.rmtree(work)


if __name__ == "__main__":
    raise SystemExit(main())
