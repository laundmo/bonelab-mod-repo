from datetime import datetime

import aiohttp
import modio
from modio.client import Mod as ApiMod
from modio.enums import TargetPlatform
from modio.entities import ModFilePlatform

from modio_repo.models import Mod, PcModFile, QuestModFile
from modio_repo.utils import log

def contains_targetplatforms(modplatforms: list[ModFilePlatform], targetplatforms: list[TargetPlatform]):
    return len([ modplatform for modplatform in modplatforms for targetplatform in targetplatforms if modplatform.platform == targetplatform ]) > 0

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
        for file_data in dl_urls:
            if file_data.platforms is not None:
                platforms = file_data.platforms
                if need_oculus and contains_targetplatforms(platforms, [TargetPlatform.android, TargetPlatform.oculus]):
                    log("\tQuest: " + file_data.url)
                    r = await self.session.head(file_data.url)
                    mf = QuestModFile(
                        id=file_data.id,
                        added=datetime.fromtimestamp(file_data.date),
                        url=r.headers["Location"],
                        mod=self.mod,
                    )
                    await mf.save()
                    need_oculus = False

                if need_pc and contains_targetplatforms(platforms, [TargetPlatform.windows]):
                    log("\tPC: " + file_data.url)
                    r = await self.session.head(file_data.url)
                    mf = PcModFile(
                        id=file_data.id,
                        added=datetime.fromtimestamp(file_data.date),
                        url=r.headers["Location"],
                        mod=self.mod,
                    )
                    await mf.save()
                    need_pc = False

    async def get_quest(self) -> QuestModFile | None:
        return await self.mod.quest_file.all().first()

    async def get_pc(self) -> PcModFile | None:
        return await self.mod.pc_file.all().first()
