from datetime import datetime

import aiohttp
import modio
from modio.client import Mod as ApiMod
from prisma.models import File, Mod, Pallet, PalletError, Platform

from modio_repo.utils import log


class ModFiles:
    def __init__(
        self, mod: Mod, api_mod: ApiMod, session: aiohttp.ClientSession
    ) -> None:
        self.mod = mod
        self.api_mod = api_mod
        self.session = session

    async def insert_mod_files(self):
        filters = modio.Filter()
        # All endpoints are sorted by the id column in ascending order by default (oldest first). therefor, reversing key gets us the newest dl_urls
        filters.sort(key="id", reverse=True)
        filters.limit(10)

        log("Getting file list from API for mod " + str(self.mod.id))

        dl_urls, _ = await self.api_mod.async_get_files(filters=filters)

        need_oculus = True
        need_pc = True
        platforms = {p.name: p for p in await Platform.prisma().find_many()}
        for file_data in dl_urls:
            if file_data.platforms is not None:
                platform = file_data.platforms[0]["platform"]
                r = await self.session.head(file_data.url)

                if (platform == "android" or platform == "oculus") and need_oculus:
                    platform = platforms["Quest"]
                    need_oculus = False

                elif platform == "windows" and need_pc:
                    platform = platforms["Pc"]
                    need_pc = False

                await File.prisma().create(
                    data={
                        "id": file_data.id,
                        "added": datetime.fromtimestamp(file_data.date),
                        "mod_id": self.mod.id,
                        "url": r.headers["Location"],
                        "platform_id": platform.id,
                    }
                )
