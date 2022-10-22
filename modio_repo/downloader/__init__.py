import asyncio
import os
import re
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, List, Type

import aiohttp
import modio
import pytz
from dotenv import load_dotenv
from modio.client import Game
from modio.client import Mod as ApiMod
from prisma.models import File, Mod, Pallet

from modio_repo.downloader.mod_files import ModFiles
from modio_repo.downloader.pallets import PalletHandler
from modio_repo.utils import PalletLoadError, get_api_mod_updated, log

load_dotenv()

MODIO_API_KEY = os.getenv("MODIO_API_KEY")
MODIO_API_SECRET = os.getenv("MODIO_API_SECRET")

# ingame repo downloading:  https://discord.com/channels/918643357998260246/918649756463538216/1026581323525148713
# 1. Open data as zip
# 2. Find all files named pallet.json in the zip
# 3. Load all pallet.json's in the zip into their own respective Pallet object in memory
# 4. Stage (extract temporarily) each mod - that is, each directory containing a pallet.json - into %appdata%\..\LocalLow\Stress Level Zero\BONELAB\ModsStaging\Downloads\{barcode}, deleting it if it already exists. NOTE: This is a staging area, not the final destination.
# 5. Move that directory to the Mods/ directory and ask AssetWarehouse to load

# TODO: add explicit tag to the database mod


def mod_logo_url(mod: ApiMod):
    if mod.logo is None:
        return "https://thumb.modcdn.io/games/38ef/3809/crop_128x128/bonelabthumb.png"
    else:
        return re.sub(
            r"(crop_\d+x\d+)", "crop_128x128", mod.logo.small or mod.logo.original
        )


class ModSkip(Exception):
    pass


class Run:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def run(self, onepage: bool = False):
        client = modio.Client(api_key=MODIO_API_KEY, access_token=MODIO_API_SECRET)
        log("logged in")
        await client.start()

        game = await client.async_get_game(3809)  # 3809 = bonelab

        tasks = []

        async for mods in self.generate_mods(game, onepage):
            tasks.append(self.insert_mods(mods))

        await asyncio.gather(*tasks)
        await client.close()

    async def generate_mods(
        self, game: Game, onepage: bool
    ) -> AsyncGenerator[List[ApiMod], None]:
        mods_result, pagination = await game.async_get_mods()
        yield mods_result
        if onepage:
            return
        while not pagination.max():
            filters = modio.Filter()
            filters.offset(pagination.next())
            mods_result, pagination = await game.async_get_mods(filters=filters)
            yield mods_result

    async def insert_mods(self, mods_result: List[ApiMod]):
        log(f"working on {len(mods_result)}")
        for api_mod in mods_result:
            try:
                await self.insert_update_mod(api_mod)
            except ModSkip:
                log("Skipped ", api_mod.name)

    async def insert_update_mod(self, api_mod: ApiMod):
        mod = await Mod.prisma().find_first(where={"id": api_mod.id})
        if mod is None:
            await self.insert_mod(api_mod)
        else:
            changed = False

            # check if mod updated
            if mod.mod_updated < api_mod.updated.astimezone(pytz.UTC):
                changed = True

            # check if new mod file
            last_file = await File.prisma().find_first(
                where={"mod_id": mod.id}, order={"added": "desc"}
            )
            if (
                api_mod.file is None
                or last_file is None
                or datetime.fromtimestamp(api_mod.file.date, tz=pytz.UTC)
                > last_file.added
            ):
                changed = True

            if changed:
                log(f"Mod has changed, updating and re-downloading {api_mod.name}")
                await self.insert_mod(api_mod)

    async def insert_mod(self, api_mod: ApiMod):
        id: int = api_mod.id
        name: str = api_mod.name
        summary: str = api_mod.summary
        updated = get_api_mod_updated(api_mod)
        logo = mod_logo_url(api_mod)
        explicit = api_mod.maturity.value == api_mod.maturity.explicit.value

        mod = await Mod.prisma().upsert(
            where={"id": api_mod.id},
            data={
                "create": {
                    "id": id,
                    "name": name,
                    "description": summary,
                    "mod_updated": updated,
                    "last_checked": datetime.now(),
                    "thumbnailUrl": logo,
                    "malformed_pallet": False,
                    "nsfw": explicit,
                },
                "update": {
                    "name": name,
                    "description": summary,
                    "mod_updated": updated,
                    "last_checked": datetime.now(),
                    "thumbnailUrl": logo,
                    "malformed_pallet": False,
                    "nsfw": explicit,
                    "files": {"set": []},
                },
            },
        )

        await self.insert_mod_files(api_mod, mod)

    async def insert_mod_files(self, api_mod: ApiMod, mod: Mod):
        mf = ModFiles(mod, api_mod, self.session)

        await mf.insert_mod_files()

        # for each platform?

        pc_file = await File.prisma().find_first(
            where={"mod_id": mod.id, "platform_id": 0}
        )
        if pc_file is not None:
            await self.pallet_from_file(mod, pc_file)

        quest_file = await File.prisma().find_first(
            where={"mod_id": mod.id, "platform_id": 1}
        )
        if quest_file is not None:
            await self.pallet_from_file(mod, quest_file)

    async def pallet_from_file(
        self,
        mod: Mod,
        file: File,
    ):
        try:
            ph = PalletHandler(mod, file, self.session)
            await ph.run()
        except PalletLoadError as e:
            if e.modio_file_id == -999:
                log("pallet error", e)
            mod.malformed_pallet = True
            await mod.prisma().update(
                where={"id": mod.id}, data={"malformed_pallet": True}
            )
            raise ModSkip


async def delete_old_pallets():
    pallets = await Pallet.prisma().find_many()

    paths = [Path(pallet.fs_path).resolve() for pallet in pallets]
    for pallet_file in PalletHandler.PATH.glob("*.json"):
        if pallet_file.resolve() not in paths:
            pallet_file.unlink()
            log(f"Expunged {pallet_file.relative_to(Path())}")


async def main():
    async with aiohttp.ClientSession() as session:
        await delete_old_pallets()
        r = Run(session)
        log("starting run")
        await r.run()
