# Releasing Bloodstained AP World and Client

## Overview and Explanation

### Files overview
- `build_pipeline.ps1`: sets up `.venv` and runs the whole pipeline below in order.
- `generate_base_pak.py`: runs unmodified True Randomizer with the historical AP settings and writes `output/TrueRandomizer-AP-raw.pak`, the baseline the static pak is audited against.
- `build_ap_base.py` / `.ps1`: builds the deterministic AP base from vanilla assets and TR helpers into `ap-base/` (report in `ap-base.json`).
- `build_mod.py`: regenerates the version/pin headers, then builds and installs `BloodstainedAP.asi`.
- `build_static_pak.py` / `.ps1`: builds the static pak (`output/BloodstainedAP-candidate.pak`); `--pin` records it in the manifest.
- `build_release.py` / `build_release_bundle.ps1`: validates and packages the release zip into `releases/`.
- `build_config.py` / `build_config.toml`: per-machine argument defaults for the build scripts.
- `release_info.py`: shared release metadata; regenerates `Mod/ClientVersion.h` and `Mod/StaticPakPin.h`.
- `cook_marker_textures.py`: cooks the marker textures; called by `build_static_pak.py`.
- `compose_minimap_diagnostic.py`: debugging aid that overlays the AP atlas on a minimap capture.

### Release File pipeline order
`.\build_pipeline.ps1` runs the whole pipeline. It needs Python 3.13+ on `PATH`
(or `-Python <path>`), creates `.venv` if missing and installs
`requirements-ap-base.txt` and `True-Randomization/_requirements.txt` whenever
they change. Options:
- `-RebuildBaseline`: regenerate the baseline pak (otherwise reused when present).
- `-ApBase`: also run the standalone AP base build.
- `-Pin`: pin the static pak after review.
- `-Clean`: full ASI rebuild.
- `-SkipRelease`: stop before packaging.
- `-RecreateVenv`: rebuild `.venv` from scratch.

To run the steps by hand, use this order:

1. `generate_base_pak.py`: produces the raw TR baseline pak.
2. `build_ap_base.ps1`: builds the AP base (`build_static_pak` also runs this itself in TR source mode).
3. `build_static_pak.ps1`: builds, audits and optionally pins the static pak.
4. `build_mod.py`: builds and installs the ASI.
5. `build_release_bundle.ps1`: packages the release zip.

## Requirements
- repak-cli v0.2.3 (path set by `repak` in `build_config.toml`)
- .NET 10
- Python 3.13+

## Files edited by hand
- `../version.toml`
- `tools/build_config.toml`

## Generated files must not be edited by hand:
- `Mod/ClientVersion.h`: regenerated from `version.toml` (the protocol Major/Minor/Build come from `min_archipelago_version`).
- `Mod/StaticPakPin.h`: regenerated from `release/static_pak_manifest.json`.

`build_mod.py` regenerates both before every build. 
`build_static_pak.py --pin` regenerates them when it records a new pin. 
You can also regenerate them on demand with `python release_info.py`. Unchanged headers are not rewritten, so they don't trigger rebuilds.

`release/README.txt` is a template. `build_release.py` fills in `{version}`,
`{min_ap_version}` and `{package_suffix}`, where `{package_suffix}` is
` <label> package` when `--package-label` is set and empty otherwise. Write literal
braces as `{{` and `}}`. The "saves before 1.1.0 are rejected" line refers to the
save-format cutoff, not the current version, so leave it alone.

## Version bump


1. Set `version` in `version.toml`. If needed, also set `min_archipelago_version`.
2. Set the same `world_version` and `minimum_ap_version` in the APWorld's
   `archipelago.json`. `build_release.py` refuses a mismatched APWorld.
3. If the static pak changed, rebuild and review it (see `STATIC_PAK.md`):
   ```powershell
   .\build_static_pak.ps1 --force
   ```
   The output says whether the build matches the current pin. After review, record it:
   ```powershell
   .\build_static_pak.ps1 --force --pin
   ```
4. Build and install the ASI. This regenerates the headers, so the new version and pin
   are compiled in:
   ```powershell
   .venv\Scripts\python.exe build_mod.py --clean
   ```
5. Build the bundle:
   ```powershell
   .\build_release_bundle.ps1
   ```
   It writes `releases\BloodstainedAP-<version>[-<label>].zip` and fails if:
   - the pak doesn't match the pin (hash or file count);
   - the pak contains seed-specific or paid-DLC assets;
   - the ASI doesn't embed the release version (a stale build);
   - the APWorld's versions don't match `version.toml`, or the APWorld can't be imported.
6. Commit `version.toml`, `Mod/ClientVersion.h`, and the manifest and
   `Mod/StaticPakPin.h` if the pak was re-pinned.

## Test packages

Set `package-label` in `[release]` of `build_config.toml`, or pass `--package-label beta1`. The label is added to the zip name and to the README title, and `manifest.json` records `"test_build": true`.
