#!/usr/bin/env python3
"""Build an experimental, deterministic AP base from vanilla assets and TR helpers.

No GUI, config.ini, seed, installation, or randomizer Generate pipeline is used.
Run in a fresh Python process (.NET/System imports are process-global).
"""
from __future__ import annotations

import argparse
import copy
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import random
import shutil
import subprocess
import sys
import tempfile

from build_config import apply_config

PROFILE = Path(__file__).with_name("ap_base_profile.json")
CUSTOM_ITEMS = ("MightyRing", "InvisibleCloak", "RagdollBullet", "TimeTonic")
# Only these level mutations survive apply_default_tweaks. Everything else is
# reloaded from vanilla before the explicitly selected AP helper passes below.
PROGRESSION_LEVELS = {
    "m01SIP_000_Gimmick",  # trigger HavePatchPureMiriam
    "m03ENT_000_Gimmick",  # spike corridor magic doors
    "m05SAN_011_BG",       # duplicate boss door
    "m05SAN_017_Gimmick",  # independent lever flag
    "m07LIB_023_Gimmick",  # Craftwork staircase
    "m09TRN_004_Gimmick",  # train gate
    "m11UGD_019_Gimmick",  # Aqua Stream candle
    "m12SND_023_Gimmick",  # Alfred seal
    "m88BKR_003_Gimmick",  # Igniculus candle
}
NEW_ROWS = {
    "PB_DT_DropRateMaster": {"N2017_Shard", "Aquastream_Shard", "FamiliaIgniculus_Shard"},
    "PB_DT_GimmickFlagMaster": {"SAN_017_LockDoor", "AquastreamLantarn001", "IgniculusLantarn001"},
    "PB_DT_EnchantParameterType": {"BuffParryArt245", "BuffParryArt246"},
}
FIELDS = {
    "PB_DT_CharacterMaster": {"N2017": {"ItemDrop"}},
    "PB_DT_GimmickFlagMaster": {"RVA_003_ItemWall": {"Id"}},
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): sha(p)
            for p in sorted(root.rglob("*")) if p.is_file()}


def forbid_random(*args, **kwargs):
    raise RuntimeError("Randomness is forbidden in the AP static asset profile")


def project_defaults(manager):
    """Use upstream implementations, but retain only the reviewed semantic delta.

    The source and vanilla input digests are locked. This projection intentionally
    prevents the monolithic upstream defaults from exporting combat, cosmetics,
    title menus, extra-mode edits, or incidental vanilla item/drop rebalancing.
    """
    tables = copy.deepcopy(manager.datatable)
    strings = copy.deepcopy(manager.stringtable)
    constants = copy.deepcopy(manager.constant)
    manager.apply_default_tweaks()
    generated = copy.deepcopy(manager.datatable)
    generated_strings = copy.deepcopy(manager.stringtable)
    manager.datatable.clear()
    manager.datatable.update(tables)
    manager.stringtable.clear()
    manager.stringtable.update(strings)
    manager.constant.clear()
    manager.constant.update(constants)
    for table, rows in generated.items():
        for row, value in rows.items():
            custom = any(row == item or row.startswith(item + "_") for item in CUSTOM_ITEMS)
            if custom or row in NEW_ROWS.get(table, set()):
                if not custom and row in tables[table]:
                    raise RuntimeError(f"Expected a new row: {table}/{row}")
                tables[table][row] = value
        for row, fields in FIELDS.get(table, {}).items():
            for field in fields:
                tables[table][row][field] = rows[row][field]
    for table, rows in generated_strings.items():
        for key, value in rows.items():
            if any(key.endswith("_" + item) for item in CUSTOM_ITEMS):
                manager.stringtable[table][key] = value
    for table, positions in manager.datatable_entry_index.items():
        manager.datatable_entry_index[table] = {
            row: index for row, index in positions.items() if row in tables[table]}
    # Reload packages touched directly by upstream defaults. Datatable edits have
    # not yet been serialized, and will be applied to these pristine packages.
    for name in list(manager.game_data):
        if name not in PROGRESSION_LEVELS:
            extension = ".umap" if manager.file_to_type[name] == manager.FileType.Level else ".uasset"
            manager.game_data[name] = manager.UAsset(
                str(Path(manager.asset_dir) / manager.file_to_path[name] / (name + extension)),
                manager.EngineVersion.VER_UE4_22)


def ap_placeholders(manager, item):
    drops = manager.datatable["PB_DT_DropRateMaster"]
    shards = manager.datatable["PB_DT_ShardMaster"]
    for drop in item.vanilla_chests:
        name = "AP_" + drop
        item.add_game_item(-1, name, "Key", "None", (3968, 3968), name,
                           "One of many relics that is part of the Archipelago world", 0, False)
        item.empty_drop_entry(drop)
        drops[drop].update(RareItemId=name, RareItemQuantity=1, RareItemRate=100.0)
    canonical = {}
    for enemy, info in manager.constant["EnemyInfo"].items():
        drop = enemy + "_Shard"
        if not info["HasShard"] or drop not in drops:
            continue
        original = drops[drop]["ShardId"]
        kind = shards[original]["ShardType"].split("::")[-1]
        if kind == "Familia":
            kind = "Familiar"
        if kind not in {"Trigger", "Effective", "Directional", "Enchant", "Familiar", "Skill"}:
            raise RuntimeError(f"Unsupported shard type: {drop}/{original}/{kind}")
        name = "AP_" + drop
        item.add_game_item(-1, name, "Shard", kind, (1280, 3456),
                           manager.translation["Enemy"][enemy] + " Shard",
                           "A crystalized version of an Archipelago relic", 0, False)
        drops[drop].update(DropSpecialFlags="EDropSpecialFlag::DropShardOnce", ShardId=name)
        canonical[enemy] = name
    for name, row in drops.items():
        enemy = name.split("_")[0]
        if "Treasure" not in name and enemy in canonical:
            row["ShardId"] = canonical[enemy]
    return canonical


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--true-randomizer-dir", type=Path, required=True)
    parser.add_argument("--game-pak", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--worker-work", type=Path, help=argparse.SUPPRESS)
    apply_config(parser, "ap_base")
    args = parser.parse_args()
    source, pak_path, output, report = (p.resolve() for p in (
        args.true_randomizer_dir, args.game_pak, args.output_dir, args.report))
    if output.exists():
        parser.error("output-dir must not already exist")
    profile = json.loads(PROFILE.read_text())
    for name, expected in profile["source_files"].items():
        if not (source / name).is_file() or sha(source / name) != expected:
            raise RuntimeError(f"Unsupported True Randomizer input: {name}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.worker_work is None:
        # .NET keeps loaded DLLs locked until process exit on Windows.
        with tempfile.TemporaryDirectory(prefix="ap-base-", dir=output.parent) as temp:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:],
                            "--worker-work", temp], check=True)
        return
    old_cwd = Path.cwd()
    with nullcontext(str(args.worker_work)) as temp:
        work = Path(temp)
        # Copy only locked files. In particular, never copy config.ini or cached
        # Game/Mod assets, nor the nested C# source directory shadowing UAssetAPI.
        for name in profile["source_files"]:
            target = work / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, target)
        os.chdir(work)
        sys.path.insert(0, str(work))
        try:
            from pyuepak import PakFile
            import Manager as M
            import Utility
            from _randomizer import Item, Equipment, Enemy, Room, Graphic
            for name in ("seed", "random", "choice", "choices", "shuffle", "sample", "randint", "randrange", "uniform", "getrandbits", "Random", "SystemRandom"):
                setattr(random, name, forbid_random)
            M.load_file_info()
            # Classic Mode and lip-sync are not part of the AP Miriam profile.
            M.file_to_path = {n: p for n, p in M.file_to_path.items()
                              if "DLC_0002" not in p and not p.startswith("Classic2_") and p != M.lipsync_dir}
            M.file_to_type = {n: t for n, t in M.file_to_type.items() if n in M.file_to_path}
            archive = PakFile()
            archive.read(str(pak_path))
            wanted = {f"BloodstainedRotN/Content/{p}/{n}" for n, p in M.file_to_path.items()}
            inputs = {}
            for name in sorted(archive.list_files()):
                if str(PurePosixPath(name).with_suffix("")) not in wanted:
                    continue
                relative = PurePosixPath(name).relative_to("BloodstainedRotN/Content")
                if ".." in relative.parts:
                    raise RuntimeError(f"Unsafe pak path: {name}")
                target = work / "Game" / str(relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                data = archive.read_file(name)
                target.write_bytes(data)
                inputs[str(relative)] = hashlib.sha256(data).hexdigest()
            input_digest = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
            if input_digest != profile["vanilla_inputs_sha256"]:
                raise RuntimeError(f"Unsupported vanilla inputs: {input_digest}")
            print(f"Loaded {len(inputs)} verified vanilla files", flush=True)
            M.init()
            Utility.init()
            M.load_game_data()
            M.load_constant()
            M.load_translation()
            M.table_complex_to_simple()
            vanilla_tables = copy.deepcopy(M.datatable)
            for module in (Item, Equipment, Enemy, Room, Graphic):
                module.init()
            project_defaults(M)
            M.set_randomizer_events()
            M.remove_fire_shard_requirement()
            Item.fill_enemy_to_room()
            canonical = ap_placeholders(M, Item)
            Item.unlock_all_quests()
            Item.disable_shard_crafting()
            Item.remove_all_keys_from_shop()
            Item.add_starting_item("Shortcut")
            Item.update_container_types()
            Item.update_shard_candles()
            Item.update_drop_ids()
            M.mod_dir = str(work / "stage/BloodstainedRotN/Content")
            for path in M.file_to_path.values():
                (Path(M.mod_dir) / path).mkdir(parents=True, exist_ok=True)
            Graphic.import_mesh("SK_P1001")
            Equipment.add_armor_reference("InvisibleCloak")
            if M.datatable["PB_DT_CharacterParameterMaster"] != vanilla_tables["PB_DT_CharacterParameterMaster"]:
                raise RuntimeError("AP profile changed enemy combat parameters")
            for drop in Item.vanilla_chests:
                row = M.datatable["PB_DT_DropRateMaster"][drop]
                if row["RareItemId"] != "AP_" + drop or row["RareItemRate"] != 100.0:
                    raise RuntimeError(f"Missing AP check: {drop}")
            changes = {}
            for table, rows in M.datatable.items():
                for row, fields in rows.items():
                    before = vanilla_tables[table].get(row)
                    if before != fields:
                        changes[f"{table}/{row}"] = {
                            k: {"before": None if before is None else before.get(k), "after": v}
                            for k, v in fields.items() if before is None or before.get(k) != v}
            M.table_simple_to_complex()
            M.update_datatable_order()
            M.write_files()
            M.remove_unchanged_files()
            # Donors needed by the later native semantic patcher/texture cooker.
            for name in ("m01SIP_002_Gimmick", "icon_8bitCrown"):
                relative = Path(M.file_to_path[name])
                for original in (work / "Game" / relative).glob(name + ".*"):
                    target = Path(M.mod_dir) / relative / original.name
                    if not target.exists():
                        shutil.copyfile(original, target)
            stage = work / "stage"
            files = inventory(stage)
            if profile.get("output_files") and files != profile["output_files"]:
                raise RuntimeError("AP base output differs from the reviewed profile")
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps({"profile": profile["name"], "vanilla_inputs_sha256": input_digest,
                                          "chest_checks": len(Item.vanilla_chests), "shard_checks": len(canonical),
                                          "files": files, "table_changes": changes}, indent=2) + "\n")
            shutil.copytree(stage, output)
            print(f"Built AP base: {len(files)} files; report: {report}", flush=True)
        finally:
            os.chdir(old_cwd)


if __name__ == "__main__":
    main()
