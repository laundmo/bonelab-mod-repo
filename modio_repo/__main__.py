from __future__ import annotations

import json
from collections import Counter
from datetime import datetime

import prisma
from prisma import Prisma
from prisma.models import File, Mod, Pallet, PalletError, Platform

from modio_repo.downloader import main as downloader_main
from modio_repo.slz_json import reset as reset_slzjson
from modio_repo.slz_repositoryfile import RepositoryFile
from modio_repo.utils import log


async def mark_duplicate_pallets(db: Prisma, mod: prisma.models.Mod):
    await db.file.group_by(["platform"], order={"added": "asc"})

    # where={
    #     "mod": mod,
    # },
    pallet.all()
    if len(pallets) > 1:
        barcodes = Counter([p.barcode for p in pallets])
        (common,) = barcodes.most_common(1)
        barcode, count = common
        if count > 1:
            await db.palleterror.create(
                data={
                    "file": file_,
                    "error": f"File contains duplicate pallet barcodes: {barcode}",
                }
            )


async def run():
    db = Prisma(auto_register=True)
    await db.connect()

    await downloader_main()

    mods = await db.mod.find_many(where={"malformed_pallet": True})

    # TODO: handle deletion of mods
    log("checking duplicate, malformed")
    for mod in mods:
        await mark_duplicate_pallets(mod)
        await set_malformed(mod)

    log("writing repo file")

    reset_slzjson()
    repofile = RepositoryFile(
        "./static/repository.json",
        "mod.io (unofficial)",
        "Unofficial repository of mod.io mods",
    )
    sfw_mods = await Mod.prisma().find_many(
        where={"malformed_pallet": False, "nsfw": False}
    )
    for mod in sfw_mods:
        await repofile.add_mod(mod)
    repofile.save()

    reset_slzjson()
    nsfw_repofile = RepositoryFile(
        "./static/nsfw_repository.json",
        "mod.io nsfw (unofficial)",
        "Unofficial repository of NSFW mod.io mods",
    )
    nsfw_mods = await Mod.prisma().find_many(
        where={"malformed_pallet": False, "nsfw": True}
    )
    for mod in nsfw_mods:
        await nsfw_repofile.add_mod(mod)
    nsfw_repofile.save()

    faulty_mods = await Mod.prisma().count(where={"malformed_pallet": True})
    with open("./static/site_meta.json", "w+") as f:
        json.dump(
            {
                "updated": datetime.utcnow().isoformat(),
                "nsfw_count": len(nsfw_mods),
                "sfw_count": len(sfw_mods),
                "faulty_count": faulty_mods,
            },
            f,
        )

    await db.disconnect()


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
    import time

    while True:
        try:
            main()
            log("Done!")
        except Exception as e:
            log(e)
        time.sleep(60 * 5)
