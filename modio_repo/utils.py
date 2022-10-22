from datetime import datetime
from pathlib import Path

from modio.client import Mod as ApiMod


class PalletLoadError(Exception):
    def __init__(self, message, pallet_id: int):
        # Call the base class constructor with the parameters it needs
        super().__init__(message)

        # Now for your custom code...
        self.modio_file_id = pallet_id


def get_api_mod_updated(api_mod: ApiMod) -> datetime:
    if api_mod.file is None:
        return api_mod.updated
    return max(datetime.fromtimestamp(api_mod.file.date), api_mod.updated)


def log(*msg):
    print(datetime.now().isoformat(), *msg)
