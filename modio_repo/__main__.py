from __future__ import annotations

import datetime
import json
import os
import zipfile
from asyncio import exceptions
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, List, Optional, Tuple
from zipfile import ZipFile

import modio
import requests
from dotenv import load_dotenv
from modio.client import Mod

load_dotenv()

MODIO_API_KEY = os.getenv("MODIO_API_KEY")
MODIO_API_SECRET = os.getenv("MODIO_API_SECRET")

session = requests.Session()


def log(*msg):
    print(datetime.datetime.now().isoformat(), *msg)


class MetadataStorage:
    PATH = Path("./cache/file_listing")
    PATH.mkdir(exist_ok=True, parents=True)

    def __init__(self):
        self.PATH.mkdir(exist_ok=True, parents=True)

    def listing_path(self, mod_id: int):
        return self.PATH / f"{mod_id}.json"

    def get_data(self, mod_id: int):
        path = self.listing_path(mod_id)
        if path.exists():
            with path.open(encoding="utf-8") as fobj:
                return json.load(fobj)

    def get_metadata(self, key: str, mod: ModioMod):
        data = self.get_data(mod.id)
        if data is None:
            return None
        if datetime.datetime.fromisoformat(data["updated"]) < mod.updated:
            return None
        if data.get(key) == True:
            return data.get(key)
        return data.get(key)

    def store_metadata(self, key: str, value: Any, mod: ModioMod):
        data = self.get_data(mod.id)
        if data is None:
            data = {
                key: value,
            }
        else:
            with self.listing_path(mod.id).open(encoding="utf-8") as fobj:
                data = json.load(fobj)
                data[key] = value
        data["updated"] = mod.updated.isoformat()
        data["pallet_checked"] = mod.main_file.id
        with self.listing_path(mod.id).open("w+", encoding="utf-8") as fobj:
            json.dump(data, fobj)


class PalletLoadError(Exception):
    pass


class Pallet:
    PATH = Path("./static/pallets/")
    PATH.mkdir(exist_ok=True, parents=True)

    def __init__(self, modio_file_id: int):
        self.modio_file_id = modio_file_id

        if not self.path.exists():
            full = self.download()
            self.get_from_zip(full)

        all_data = self.load_pallet()

        pallet_data = self.read_pallet_content(all_data)
        self.barcode = pallet_data["barcode"]
        self.title = pallet_data["title"]
        self.author = pallet_data["author"]
        self.version = pallet_data["version"]
        self.sdkVersion = pallet_data["sdkVersion"]

    @property
    def path(self):
        return self.PATH / f"{self.modio_file_id}.json"

    def load_pallet(self):
        with self.path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def download(self):
        with session.get(
            f"https://api.mod.io/mods/file/{str(self.modio_file_id)}", stream=True
        ) as r:
            try:
                r.raise_for_status()
            except requests.exceptions.HTTPError as e:
                raise PalletLoadError("Could not open mod file url") from e

            memoryfile = BytesIO()
            log("downloading pallet", self.modio_file_id)
            for chunk in r.iter_content(chunk_size=8192):
                memoryfile.write(chunk)
            log("done downloading, extracting zip in memory")

            return memoryfile

    def get_from_zip(self, file_like):
        try:
            zf = ZipFile(file_like)
        except zipfile.BadZipfile as e:
            raise PalletLoadError("Bad Zip") from e

        try:
            file_list = zf.infolist()
            found_pallets_wrong = []
            for pfile in file_list:
                path = Path(pfile.filename)
                if len(path.parts) == 2 and pfile.filename.endswith("pallet.json"):
                    with open(self.path, "wb+") as f:
                        f.write(zf.read(pfile))
                        break
                elif "pallet.json" in pfile.filename:
                    found_pallets_wrong.append(pfile.filename)
            else:
                if len(found_pallets_wrong) > 0:
                    raise PalletLoadError(
                        "pallet.json found in wrong location(s):</br>"
                        + "</br>".join(found_pallets_wrong)
                    )
                raise PalletLoadError("pallet.json not found in zip.")
        except NotImplementedError as e:
            raise PalletLoadError("???") from e

    def read_pallet_content(self, data):
        types = data.get("types")
        if types is None:
            raise PalletLoadError('Could not find "types" in json')

        pallet_key = None

        for key, typ in types.items():
            if "SLZ.Marrow.Warehouse.Pallet" in typ["fullname"]:
                pallet_key = key

        if pallet_key is None:
            raise PalletLoadError("Could not find key for SLZ.Marrow.Warehouse.Pallet")

        pallet_obj = None

        for obj in data["objects"].values():
            if obj["isa"]["type"] == pallet_key:
                pallet_obj = obj

        if pallet_obj is None:
            raise PalletLoadError(f"No object with key {pallet_key} found in pallet.")

        return pallet_obj


class ModNotLoadable(Exception):
    pass


@dataclass
class ModList:
    mods: List[ModioMod]

    def extend(self, other_list: List[Mod]) -> None:
        for mod in other_list:
            try:
                modio_mod = ModioMod(mod)
            except ModNotLoadable:
                continue
            self.mods.append(modio_mod)


def set_broken_pallet(name: str, error: str, mod: ModioMod):
    p = Path("./cache/broken.json")

    with p.open("r", encoding="utf-8") as f:
        broken_pallets = json.load(f)

    broken_pallets[str(mod.main_file.id)] = {
        "name": name,
        "error": error,
        "mod": mod.id,
    }

    with p.open("w", encoding="utf-8") as f:
        json.dump(broken_pallets, f)


def remove_broken_pallet(mod: ModioMod):
    p = Path("./cache/broken.json")
    if not p.exists():
        with p.open("w+", encoding="utf-8") as f:
            json.dump({}, f)

    with p.open("r", encoding="utf-8") as f:
        broken_pallets = json.load(f)
    try:
        del broken_pallets[str(mod.main_file.id)]
    except:
        pass
    with p.open("w", encoding="utf-8") as f:
        json.dump(broken_pallets, f)


class ModioMod:
    meta = MetadataStorage()

    def __init__(self, mod: Mod):
        self.mod = mod
        self.store_metadata("last_checked", datetime.datetime.now().isoformat())
        # early exit if a broken state is know from a previous run
        # uses the metadata cache timeout mechanism
        try:
            broken = self.get_metadata("malformed_pallet")
            if broken:
                raise ModNotLoadable
            elif broken is None:
                # on timeout remove the broken state for the retry
                remove_broken_pallet(self)
                # unset the malformed_pallet state so it makes sure the next state is good
                self.store_metadata("malformed_pallet", False)

            self.load_pallet()
        except PalletLoadError as e:
            self.store_metadata("malformed_pallet", True)

            cause = ""
            if e.__cause__ is not None:
                cause = f"</br>due to</br>{str(e.__cause__)}"

            set_broken_pallet(
                f"{self.mod.submitter.username}.{self.mod.name}",
                f"{str(e)}{cause}",
                self,
            )
            log("broken pallet for mod " + str(self.id))
            raise ModNotLoadable

    @property
    def main_file(self):
        if self.mod.file is None:
            raise PalletLoadError("Mod does not have a file, cannot load pallet.")
        return self.mod.file

    def load_pallet(self):
        self.pallet = Pallet(self.main_file.id)

    def get_metadata(self, key: str):
        return self.meta.get_metadata(key, self)

    def store_metadata(self, key: str, value: Any):
        self.meta.store_metadata(key, value, self)

    @property
    def id(self):
        return self.mod.id

    @property
    def updated(self):
        return datetime.datetime.fromtimestamp(self.main_file.date)

    @property
    def logo_url(self):
        if self.mod.logo is None:
            return (
                "https://thumb.modcdn.io/games/38ef/3809/crop_128x128/bonelabthumb.png"
            )
        else:
            return self.mod.logo.small or self.mod.logo.original

    @property
    def explicit(self):
        return self.mod.maturity.value == self.mod.maturity.explicit.value

    @property
    def file_urls(self):
        dl_urls = self.get_metadata("files")
        if dl_urls is None:
            filters = modio.Filter()
            # All endpoints are sorted by the id column in ascending order by default (oldest first). therefor, reversing key gets us the newest dl_urls
            filters.sort(key="id", reverse=True)
            filters.limit(4)

            log("Getting file list from API for mod " + str(self.id))

            dl_urls, _ = self.mod.get_files(filters=filters)
            oculus = None
            pc = None
            for f in dl_urls:
                if f.platforms is not None:
                    if (
                        f.platforms[0]["platform"] == "android"
                        or f.platforms[0]["platform"] == "oculus"
                    ) and oculus is None:
                        r = session.head(f.url)
                        oculus = r.headers["Location"]
                    if f.platforms[0]["platform"] == "windows" and pc is None:
                        r = session.head(f.url)
                        pc = r.headers["Location"]
            dl_urls = {"pc": pc, "oculus": oculus}
            self.store_metadata("files", dl_urls)
        return dl_urls

    def to_json(self, offset: int) -> Tuple[int, Any, str]:
        listing_id = f"o:{offset}"
        offset += 1
        data = {
            listing_id: {
                "barcode": self.pallet.barcode,
                "title": self.mod.name,
                "author": self.pallet.author,
                "version": self.pallet.version,
                "sdkVersion": self.pallet.sdkVersion,
                "description": self.mod.description,
                "internal": False,
                "tags": [],
                "thumbnailUrl": self.logo_url,
                "manifestUrl": (
                    f"https://blrepo.laund.moe/pallets/{self.pallet.modio_file_id}.json"
                ),
                "targets": {},
                "isa": {"type": "t:2"},
            }
        }
        urls = self.file_urls
        if urls["oculus"] is not None:
            oculus_file_id = f"o:{offset}"
            offset += 1
            data[oculus_file_id] = {
                "thumbnailOverride": None,
                "url": urls["oculus"],
                "isa": {"type": "t:3"},
            }
            data[listing_id]["targets"]["oculus-quest"] = {
                "ref": oculus_file_id,
                "type": "t:3",
            }

        if urls["pc"] is not None:
            pc_file_id = f"o:{offset}"
            offset += 1
            data[pc_file_id] = {
                "thumbnailOverride": None,
                "url": urls["pc"],
                "isa": {"type": "t:3"},
            }
            data[listing_id]["targets"]["pc"] = {"ref": pc_file_id, "type": "t:3"}
        return offset, data, listing_id


def get_mods():
    log("starting authentication...")
    client = modio.Client(api_key=MODIO_API_KEY, access_token=MODIO_API_SECRET)
    log("successfully authenticated, requesting mods list")
    game = client.get_game(3809)  # 3809 = bonelab

    mods_container = ModList([])

    mods_result, pagination = game.get_mods()
    mods_container.extend(mods_result)
    while not pagination.max():
        log("next page")
        filters = modio.Filter()
        filters.offset(pagination.next())
        mods_result, pagination = game.get_mods(filters=filters)
        mods_container.extend(mods_result)
    return mods_container


def write_errors_file():
    with open("./cache/broken.json", "r", encoding="utf-8") as f:
        broken_pallets = json.load(f)
    res = ""
    m = MetadataStorage()
    for d in broken_pallets.values():
        d["name"]
        d["error"]
        meta = m.get_data(d["mod"])
        upd = ""
        if meta is not None:
            upd = meta["updated"]
        # meta["updated"]
        # meta["last_checked"]
        res += f"<tr><td>{d['name']}</td><td>{d['error']}</td><td>{upd}</td></tr>\n"

    with open("./static/errors.html", "w+", encoding="utf-8") as f:
        f.write(
            f"""
<!doctype html>
<html>

    <head>
        <title>mod.io repository errors</title>
        <meta name="description" content="Errors encountered fetching mods from mod.io">
        <meta name="keywords" content="modding repository mod.io bonelab">
        <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.2.1/dist/css/bootstrap.min.css" rel="stylesheet"
            integrity="sha384-iYQeCzEYFbKjA/T2uDLTpkwGzCiq6soy8tYaI1GyVh/UjpbCx/TYkiZhlZB6+fzT" crossorigin="anonymous">

        <style>
            .center {{
                margin: auto;
                width: 50%;
                padding: 10px;
            }}


            body {{
                font-family: Sans-Serif;
            }}
        </style>
    </head>

    <body>
        <div class="center content">
            <table class="table">
                <thead>
                <tr>
                    <th>Mod</th>
                    <th>Error</th>
                    <th>Last Mod Update</th>
                </tr>
                </thead>
                <tbody>
                {res}
                </tbody>
            </table>
        </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.2.1/dist/js/bootstrap.bundle.min.js"
        integrity="sha384-u1OknCvxWvY5kfmNBILK2hRnQC3Pr17a+RTT6rIHI7NnikvbZlHgTPOOmMi466C8" crossorigin="anonymous">
        </script>

    </body>
</html>
"""
        )
    return len(broken_pallets)


def main():
    mods_container = get_mods()
    error_count = write_errors_file()

    sfw_count = make_sfw(mods_container)
    nsfw_count = make_nsfw(mods_container)

    with open("./static/site_meta.json", "w+", encoding="utf-8") as f:
        data = {
            "updated": datetime.datetime.now().isoformat(),
            "nsfw_count": nsfw_count,
            "sfw_count": sfw_count,
            "faulty_count": error_count,
        }
        json.dump(data, f)

    log("done!")


def make_nsfw(mods_container):
    nsfw_listings = list(filter(lambda x: x.explicit, mods_container.mods))
    nsfw_repo_json = make_json(
        nsfw_listings,
        "NSFW mod.io mods",
        "tries to include as many mods as possible.",
    )

    with open("./static/nsfw_repository.json", "w+", encoding="utf-8") as f:
        json.dump(nsfw_repo_json, f)

    return len(nsfw_listings)


def make_sfw(mods_container):
    sfw_listings = list(filter(lambda x: not x.explicit, mods_container.mods))
    sfw_repo_json = make_json(
        sfw_listings,
        "mod.io mods",
        "tries to include as many mods as possible.",
    )

    with open("./static/repository.json", "w+", encoding="utf-8") as f:
        json.dump(sfw_repo_json, f)

    return len(sfw_listings)


def make_json(listings: Iterable[ModioMod], title: str, description: str):
    json_base = {
        "version": 1,
        "root": {"ref": "o:1", "type": "t:1"},
        "objects": {
            "o:1": {
                "title": title,
                "description": description,
                "mods": [],
                "isa": {"type": "t:1"},
            },
        },
        "types": {
            "t:1": {
                "type": "t:1",
                "fullname": (
                    "SLZ.Marrow.Forklift.Model.ModRepository, SLZ.Marrow.SDK,"
                    " Version=0.0.0.0, Culture=neutral, PublicKeyToken=null"
                ),
            },
            "t:2": {
                "type": "t:2",
                "fullname": (
                    "SLZ.Marrow.Forklift.Model.ModListing, SLZ.Marrow.SDK,"
                    " Version=0.0.0.0, Culture=neutral, PublicKeyToken=null"
                ),
            },
            "t:3": {
                "type": "t:3",
                "fullname": (
                    "SLZ.Marrow.Forklift.Model.DownloadableModTarget, SLZ.Marrow.SDK,"
                    " Version=0.0.0.0, Culture=neutral, PublicKeyToken=null"
                ),
            },
        },
    }

    offset = 2
    mods = []
    for listing in listings:
        offset, data, listing_id = listing.to_json(offset)
        json_base["objects"].update(data)
        mods.append({"ref": listing_id, "type": "t:2"})
    json_base["objects"]["o:1"]["mods"] = mods
    return json_base


if __name__ == "__main__":
    import time

    while True:
        main()
        time.sleep(60 * 8)
