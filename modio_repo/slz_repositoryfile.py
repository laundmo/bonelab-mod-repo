from modio_repo.models import Mod, PcPallet, QuestPallet
from modio_repo.slz_json import RefList, SLZContainer, SLZObject, SLZType, dump
from modio_repo.utils import log


class RepositoryFile:
    def __init__(self, filename: str, reponame: str, repo_description: str):
        self.filename = filename

        self.t_repo = SLZType(
            "SLZ.Marrow.Forklift.Model.ModRepository, SLZ.Marrow.SDK, Version=0.0.0.0,"
            " Culture=neutral, PublicKeyToken=null"
        )
        self.t_list = SLZType(
            "SLZ.Marrow.Forklift.Model.ModListing, SLZ.Marrow.SDK, Version=0.0.0.0,"
            " Culture=neutral, PublicKeyToken=null"
        )
        self.t_target = SLZType(
            "SLZ.Marrow.Forklift.Model.DownloadableModTarget, SLZ.Marrow.SDK,"
            " Version=0.0.0.0, Culture=neutral, PublicKeyToken=null"
        )
        self.types = SLZContainer([self.t_repo, self.t_list, self.t_target])
        self.objects: SLZContainer[SLZObject] = SLZContainer([])
        self.repository = {
            "version": 1,
            "root": {"ref": "o:1", "type": self.t_repo.ref},
            "objects": self.objects,
            "types": self.types,
        }
        self.objects.append(
            SLZObject(
                self.t_repo.ref,
                title=reponame,
                description=repo_description,
                mods=RefList(
                    self.objects, filter_=lambda x: x.type.resolve() == self.t_list
                ),
            )
        )

    def save(self):
        with open(self.filename, "w+") as f:
            dump(self.repository, f)

    async def add_mod(self, mod: Mod):
        targets = {}

        pc_file = await mod.get_pc_file()

        quest_file = await mod.get_quest_file()

        pallets: list[PcPallet | QuestPallet] = []
        if pc_file is not None:
            pallets.extend(await pc_file.pallet)
        if quest_file is not None:
            pallets.extend(await quest_file.pallet)

        # TODO: what should really be used for the barcode?
        # what if there are multiple pallets in these files?
        if len(pallets) > 0:
            pallet = pallets[0]
            self.maybe_add_platform(targets, "pc", pc_file)
            self.maybe_add_platform(targets, "oculus-quest", quest_file)
            file_ = await pallet.file
            self.objects.append(
                SLZObject(
                    self.t_list.ref,
                    barcode=pallet.barcode,
                    title=self.titlesorthack(mod),
                    description=mod.description,
                    author=pallet.author,
                    version=pallet.version,
                    sdkVersion=pallet.sdkVersion,
                    internal=False,
                    tags=[],
                    thumbnailUrl=mod.thumbnailUrl,
                    manifestUrl=f"https://blrepo.laund.moe/pallets/{file_.id}_0.json",
                    targets=targets,
                )
            )

    def maybe_add_platform(self, targets, platform, file_):
        if file_ is not None:
            target = SLZObject(
                self.t_target.ref,
                thumbnailOverride=None,
                url=file_.url,
            )
            self.objects.append(target)
            targets[platform] = {
                "ref": target.ref,
                "type": target.type,
            }

    # in-game ui sorting hack based on ranks (trending)
    def titlesorthack(self, mod: Mod):
        rank = ""
        if mod.rank is not None:
            rank = f'<size=0%>{mod.rank:09d}</size>'
        return f'{rank}{mod.name}\n  <mspace=-0.2>▬ꜜ</mspace>    {mod.downloads}'