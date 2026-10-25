"""Run unmodified upstream TR using the historical AP settings, in isolation."""
import argparse
import os
from pathlib import Path
import shutil
import sys

from build_config import apply_config

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "True-Randomization"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--game-root", type=Path, required=True,
                    help="Bloodstained install directory, read for the original game assets")
parser.add_argument("--dotnet-root", type=Path,
                    help="sets DOTNET_ROOT for pythonnet (default: leave the environment alone)")
apply_config(parser, "base_pak")
args = parser.parse_args()
GAME = args.game_root.resolve()
if not GAME.is_dir():
    parser.error(f"game root not found: {GAME}")
if args.dotnet_root:
    os.environ["DOTNET_ROOT"] = str(args.dotnet_root)
os.chdir(SOURCE)
sys.path.insert(0, str(SOURCE))
import Randomizer as R

class Progress:
    def setLabelText(self, text):
        print(text, flush=True)

R.config.set("Archipelago", "bEnable", "true")
R.config.set("ItemRandomization", "bOverworldPool", "true")
R.config.set("ItemRandomization", "iOverworldPoolComplexity", "3")
R.config.set("GameDifficulty", "bNormal", "false")
R.config.set("GameDifficulty", "bHard", "true")
R.config.set("GameDifficulty", "bNightmare", "false")
R.config.set("Misc", "sSeed", "3768323637")
R.config.set("Misc", "bIgnoreDLC", "false")
R.Manager.load_file_info()
R.Manager.load_translation()
class Context:
    owned_dlc = [R.DLCType.Shantae]
R.MainWindow.update_file_info(Context())
R.config.set("Misc", "sGamePath", str(GAME))
print("Importing original game assets read-only", flush=True)
R.Import(list(R.Manager.file_to_path)).process()
target = ROOT / "generation-target"
(target / "BloodstainedRotN/Binaries/Win64").mkdir(parents=True, exist_ok=True)
R.config.set("Misc", "sGamePath", str(target))
output = ROOT / "output"
output.mkdir(parents=True, exist_ok=True)
with (output / "generator-settings.ini").open("w") as stream:
    R.config.write(stream)
R.Generate(Progress(), 3768323637, "", [], Context.owned_dlc).process()
shutil.copyfile(target / "BloodstainedRotN/Content/Paks/~mods/Randomizer.pak",
                output / "TrueRandomizer-AP-raw.pak")
print("Initial pak generated", flush=True)
