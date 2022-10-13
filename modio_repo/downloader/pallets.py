from __future__ import annotations

import asyncio
import json
from io import BytesIO
from pathlib import Path
from typing import Any, Generic, List, Tuple, Type, TypeVar
from zipfile import BadZipfile, ZipFile

import aiofiles
import aiohttp

from modio_repo.models import Mod, PcModFile, PcPallet, QuestModFile, QuestPallet
from modio_repo.utils import PalletLoadError, log

T = TypeVar("T", QuestModFile, PcModFile)


class PalletHandler(Generic[T]):
    PATH = Path("./static/pallets/")
    PATH.mkdir(exist_ok=True, parents=True)

    def __init__(self, mod: Mod, file: T, session: aiohttp.ClientSession):
        self.file = file
        self.modio_file_id = file.id
        self.mod = mod
        self.session = session

    @property
    def path(self):
        return self.PATH / f"{self.modio_file_id}.json"

    async def run(self):
        db_pallet = await self.file.pallet.all().first()

        if db_pallet is not None:
            return db_pallet

        pallet_type = self.get_pallet_class()
        try:
            file_obj = await self.download()
        except asyncio.exceptions.TimeoutError:
            raise PalletLoadError("Could not downlaod mod file", -999)
        pallet_list = await self.get_from_zip(file_obj)

        for zf_path, fs_path in pallet_list:
            data = self.get_pallet_content(fs_path)

            db_pallet = pallet_type(
                barcode=data["barcode"],
                author=data["author"],
                version=data["version"],
                sdkVersion=data["sdkVersion"],
                zip_path=str(zf_path),
                fs_path=str(fs_path),
                file=self.file,
            )
            await db_pallet.save()

    def get_pallet_class(self):
        if isinstance(self.file, QuestModFile):
            return QuestPallet
        elif isinstance(self.file, PcModFile):
            return PcPallet
        else:
            raise NotImplementedError("Unknown File ORM Model passed!")

    async def download(self):
        async with self.session.get(
            f"https://api.mod.io/mods/file/{str(self.modio_file_id)}"
        ) as response:
            try:
                response.raise_for_status()
            except aiohttp.ClientError as e:
                raise PalletLoadError("Could not open mod file url", self.modio_file_id)

            memoryfile = BytesIO()
            log("downloading pallet", self.modio_file_id)
            async for data in response.content.iter_chunked(8192):
                memoryfile.write(data)
            log("done downloading, extracting zip in memory")

            return memoryfile

    async def get_from_zip(self, file_like) -> List[Tuple[Path, Path]]:
        try:
            zf = ZipFile(file_like)
        except BadZipfile as e:
            raise PalletLoadError(str(e), self.modio_file_id)

        try:
            file_list = zf.infolist()
            found_pallets = []

            for pfile in file_list:
                path_in_zf = Path(pfile.filename)
                if pfile.filename.endswith("pallet.json"):
                    fs_path = self.path.with_stem(
                        self.path.stem + f"_{len(found_pallets)}"
                    )
                    async with aiofiles.open(fs_path, "wb+") as f:
                        await f.write(zf.read(pfile))
                        found_pallets.append((path_in_zf, fs_path))
            if len(found_pallets) < 0:
                raise PalletLoadError(
                    "pallet.json not found in zip.",
                    self.modio_file_id,
                )
            return found_pallets
        except NotImplementedError as e:
            raise PalletLoadError(
                "Unknown Errror",
                self.modio_file_id,
            ) from e

    def get_pallet_content(self, file: Path) -> dict[str, Any]:
        with file.open("r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except UnicodeDecodeError:
                print(file.resolve())
                raise PalletLoadError("Pallet is not UTF-8", self.modio_file_id)
            return self._read_pallet_content(data)

    def _read_pallet_content(self, data: dict[Any, Any]):
        types = data.get("types")
        if types is None:
            raise PalletLoadError('Could not find "types" in json', self.modio_file_id)

        pallet_key = None

        for key, typ in types.items():
            if "SLZ.Marrow.Warehouse.Pallet" in typ["fullname"]:
                pallet_key = key

        if pallet_key is None:
            raise PalletLoadError(
                "Could not find key for SLZ.Marrow.Warehouse.Pallet", self.modio_file_id
            )

        pallet_obj = None

        for obj in data["objects"].values():
            if obj["isa"]["type"] == pallet_key:
                pallet_obj = obj

        if pallet_obj is None:
            raise PalletLoadError(
                f"No object with key {pallet_key} found in pallet.", self.modio_file_id
            )

        return pallet_obj
