from __future__ import annotations

from collections import Counter
from typing import Type

from tortoise import Tortoise, run_async

from modio_repo.downloader import main as downloader_main
from modio_repo.models import Mod, ModFileBase, PcPalletError, QuestPalletError
from modio_repo.slz_json import RefList, SLZContainer, SLZObject, SLZType
from modio_repo.slz_repositoryfile import RepositoryFile


async def check_duplicate_pallet_for(
    file_: ModFileBase, error: Type[PcPalletError | QuestPalletError]
):
    pallets = await file_.pallet.all()
    if len(pallets) > 1:
        barcodes = Counter([p.barcode for p in pallets])
        (common,) = barcodes.most_common(1)
        barcode, count = common
        if count > 1:
            err = error(
                file=file_,
                error=f"{file_.url} contains duplicate pallet barcodes: {barcode}",
            )
            await err.save()


async def mark_duplicate_pallets(mod: Mod):
    pc_file = await mod.get_pc_file()
    if pc_file is not None:
        await check_duplicate_pallet_for(pc_file, PcPalletError)

    quest_file = await mod.get_quest_file()
    if quest_file is not None:
        await check_duplicate_pallet_for(quest_file, QuestPalletError)


async def run():
    await Tortoise.init(
        db_url="sqlite://db.sqlite3", modules={"models": ["modio_repo.models"]}
    )
    await Tortoise.generate_schemas()
    await downloader_main()

    mods = await Mod.filter(malformed_pallet=False)
    repofile = RepositoryFile(
        "./static/repository.json",
        "mod.io (unofficial)",
        "Unofficial repository of mod.io mods",
    )
    nsfw_repofile = RepositoryFile(
        "./static/nsfw_repository.json",
        "mod.io nsfw (unofficial)",
        "Unofficial repository of NSFW mod.io mods",
    )
    # TODO: handle deletion of mods
    for mod in mods:
        await mark_duplicate_pallets(mod)
        await set_malformed(mod)
        if mod.nsfw:
            await nsfw_repofile.add_mod(mod)
        else:
            await repofile.add_mod(mod)

    repofile.save()
    nsfw_repofile.save()


async def set_malformed(mod):
    pc_file = await mod.get_pc_file()
    if pc_file is not None:
        count = await pc_file.pallet_error.all().count()
        if count > 0:
            mod.malformed_pallet = True  # type: ignore
            await mod.save()

    quest_file = await mod.get_quest_file()
    if quest_file is not None:
        count = await quest_file.pallet_error.all().count()
        if count > 0:
            mod.malformed_pallet = True  # type: ignore
            await mod.save()


def main():
    run_async(run())


if __name__ == "__main__":
    main()
