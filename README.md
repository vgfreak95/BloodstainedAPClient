[![CI](https://github.com/vgfreak95/BloodstainedModdingSDK/actions/workflows/msbuild.yml/badge.svg)](https://github.com/vgfreak95/BloodstainedModdingSDK/actions/workflows/msbuild.yml)
[![License](https://img.shields.io/github/license/vgfreak95/BloodstainedModdingSDK)](LICENSE)
[![Last Commit](https://img.shields.io/github/last-commit/vgfreak95/BloodstainedModdingSDK)](https://github.com/vgfreak95/BloodstainedModdingSDK/commits/main)

# BloodstainedAPClient
The BloodstainedAPClient is an Archipelago Client which allows users to connect to Archipelago Servers from Bloodstained.

## Game Distribution Functionality
- Steam
- GOG (untested)
- Epic (untested)

## Terms
- Game Shipping Directory = `steamapps\common\Bloodstained Ritual of the Night\BloodstainedRotN\Binaries\Win64`
- Plugins Directory = `steamapps\common\Bloodstained Ritual of the Night\BloodstainedRotN\Binaries\Win64\plugins`

## Migration from Pre 1.1.0 Versions
1. Remove `Content\Paks\~mods\Randomizer.pak`
2. Remove `version.dll` from Game Shipping Directory

## Installation
1. Download the latest Bloodstained AP bundle from [Releases](https://github.com/vgfreak95/BloodstainedAPClient/releases/latest).
2. Copy the bundle's `Game` directory into the game installation directory, preserving its folder structure.
3. Launch the game, check top-right of title screen to verify installation.
4. Create a new story save, then press `F5` to open the mod menu.

> Pre-1.1.0 AP story saves are intentionally unsupported.

## Archipelago:
Instructions can be found here: [Archipelago Setup Guide for Bloodstained: Ritual of the Night](https://github.com/vgfreak95/BloodstainedAP/blob/bloodstained/worlds/bloodstained_rotn/docs/setup_en.md)

## Troubleshooting
The Release client writes connection transitions and location-check reconciliation to
`%LOCALAPPDATA%\BloodstainedRotN\Saved\Logs\BloodstainedAP.log`. Include that file with the matching Archipelago
server log when reporting connection or missing-check problems.

## Building from Source:

### Prerequisites:
- Visual Studio version that supports .slnx
- MSBuild tools v145
- Windows 10 / 11

### Building:
1. Clone/Download the `main` branch of the repository with command `git clone --recurse-submodules=subprojects`. `main` will always be stable latest functional code.
2. Open a VS Administrator Terminal, and `cd` into the project root directory/folder.
3. Run `vcpkg install --triplet x64-windows-static-md` to install openssl and zlib. The packages are defined in `vcpkg.json` in project root directory/folder.
4. Open the `BloodstainedAPClient.vcxproj` and modify the `<BSGamePath>` sections to match your Games target destination.
5. Exit the game, then run `python tools/build_mod.py` for a parallel incremental Release x64 build. The helper uses 16 compiler workers by default and installs `BloodstainedAP.asi` into the Plugins Directory.
6. Set paths correctly in `tools/build_config.toml`. Each process of the build pipeline is explained in `tools/RELEASES.md`
7. Launch the game and load a save, then press `F5` to open the mod menu. Explore the GUI and add custom content inside `Mod\Gui.cpp`.

## Contributing:
1. Fork the main repository, and make a PR. 
2. All PRs must pass a full build process on PR creator's local machine and through maintainers machines to ensure consistent build process.
3. Notes on LLMs: All LLMs are *currently* acceptable, when creating a PR the models name *must* be present for tracking purposes. Provide screenshots to prove the model used. This rule is subject to change over time.

## Shoutouts:
- Trexounay: For building EnderMagnolia Randomizer, its architecture is used as a foundation for this project.
- Lakifume: For building the Bloodstained TrueRandomizer, will be a huge help for research
- Tourmi: For creating an Baseline APWorld, various modding repositories and attempting this themselves. Their Archipelago foundation will help jumpstart the Archipelago portion of this project.
- Berserker: For creating user friendly build system implementation, in-game tracker, and using archipelago client best practices in the codebase.

## Authors Note:
I built this project from the ground up through my own blood, sweat, and tears. It was meant to be an educational and learning experience for myself. My livestreams demonstrated that. Even though I don't use LLMs for more than general brainstorming and ideas, people who contribute with them are allowed.
