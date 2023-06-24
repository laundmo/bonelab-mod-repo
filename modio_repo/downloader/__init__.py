import asyncio
import os
from random import random
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import AsyncGenerator, Generator, List, Type

import aiohttp
import modio
import pytz
from dotenv import load_dotenv
from modio.client import Game
from modio.client import Mod as ApiMod
from modio_repo.downloader.mod_files import ModFiles
from modio_repo.downloader.pallets import PalletHandler
from modio_repo.models import (
    Mod,
    PalletBase,
    PalletErrorBase,
    PcModFile,
    PcPallet,
    PcPalletError,
    QuestPallet,
    QuestPalletError,
)
from modio_repo.utils import PalletLoadError, get_api_mod_updated, log
from tortoise import Tortoise, run_async

load_dotenv()

MODIO_API_KEY = os.getenv("MODIO_API_KEY")
MODIO_API_SECRET = os.getenv("MODIO_API_SECRET")

# paralell downloads
par_download_sem = asyncio.Semaphore(8)

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
        # use the semaphore to limit paralellism
        async with par_download_sem:
            log(f"working on {len(mods_result)}")
            for api_mod in mods_result:
                try:
                    await self.insert_update_mod(api_mod)
                except ModSkip:
                    log("Skipped ", api_mod.name)

    async def insert_update_mod(self, api_mod: ApiMod):
        mod = await Mod.filter(id=api_mod.id).first()
        if mod is None:
            await self.insert_mod(api_mod)
        else:
            changed = False


            # check if mod updated
            if mod.mod_updated < api_mod.updated.astimezone(pytz.UTC):
                changed = True
            
            # check if pallet exists (random chance to not redownload all missing ones every time)
            if random() > 0.95:
                pc_file = await mod.get_pc_file()
                if pc_file is not None:
                    pc_pallet = await pc_file.pallet.all().first()
                    if pc_pallet is None:
                        changed = True
                quest_file = await mod.get_quest_file()
                if quest_file is not None:
                    pc_pallet = await quest_file.pallet.all().first()
                    if pc_pallet is None:
                        changed = True
             
            # check if new mod file
            last_file_change = await mod.get_last_file_change()
            if (
                api_mod.file is None
                or last_file_change is None
                or datetime.fromtimestamp(api_mod.file.date, tz=pytz.UTC)
                > last_file_change
            ):
                changed = True

            if changed:
                log(f"Mod has changed, updating and re-downloading {api_mod.name}")
                await self.insert_mod(api_mod)
            else:
                await self.update_stats_mod(api_mod)

    async def update_stats_mod(self, api_mod: ApiMod):
        mod, created = await Mod.update_or_create(
            id=api_mod.id,
            defaults={
                "name": api_mod.name,
                "description": api_mod.summary,
                # "mod_updated": get_api_mod_updated(api_mod),
                # "last_checked": datetime.now(),
                "thumbnailUrl": mod_logo_url(api_mod),
                "malformed_pallet": False,
                "nsfw": api_mod.maturity.value == api_mod.maturity.explicit.value,
                "rank": api_mod.stats.rank,
                "downloads": api_mod.stats.downloads,
            },
        )

        await mod.save()

    async def insert_mod(self, api_mod: ApiMod):
        mod, created = await Mod.update_or_create(
            id=api_mod.id,
            defaults={
                "name": api_mod.name,
                "description": api_mod.summary,
                "mod_updated": get_api_mod_updated(api_mod),
                "last_checked": datetime.now(),
                "thumbnailUrl": mod_logo_url(api_mod),
                "malformed_pallet": False,
                "nsfw": api_mod.maturity.value == api_mod.maturity.explicit.value,
                "rank": api_mod.stats.rank,
                "downloads": api_mod.stats.downloads,
            },
        )

        await mod.save()

        if not created:
            # re-pull files if changed
            await mod.clear_files()

        await self.insert_mod_files(api_mod, mod)

    async def insert_mod_files(self, api_mod, mod):
        mf = ModFiles(mod, api_mod, self.session)

        await mf.insert_mod_files()

        pc_file = await mod.get_pc_file()
        if pc_file is not None:
            await self.pallet_from_file(mod, pc_file, PcPalletError)

        quest_file = await mod.get_quest_file()
        if quest_file is not None:
            await self.pallet_from_file(mod, quest_file, QuestPalletError)

    async def pallet_from_file(self, mod: Mod, file, error_cls: Type[PalletErrorBase]):
        try:
            ph = PalletHandler(mod, file, self.session)
            await ph.run()
        except PalletLoadError as e:
            if e.modio_file_id == -999:
                log("pallet error", e)
            await Mod.filter(id=mod.id).update(malformed_pallet=True)
            error = error_cls(file=file, error=str(e))
            await error.save()
            raise ModSkip


async def delete_old_pallets():
    pallets: List[PcPallet | QuestPallet] = []
    pallets.extend(await QuestPallet.all())
    pallets.extend(await PcPallet.all())

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
