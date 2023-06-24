from __future__ import annotations

from tortoise import fields
from tortoise.models import Model


class Mod(Model):
    id = fields.IntField(pk=True, generated=False)
    name = fields.TextField()
    description = fields.TextField()
    mod_updated = fields.DatetimeField()
    last_checked = fields.DatetimeField()
    malformed_pallet = fields.BooleanField()
    nsfw = fields.BooleanField()
    thumbnailUrl = fields.TextField()
    rank = fields.IntField()
    downloads = fields.IntField()

    quest_file: fields.ReverseRelation[QuestModFile]
    pc_file: fields.ReverseRelation[PcModFile]

    async def get_quest_file(self):
        cached = getattr(self, "__quest_file_cached", None)
        self.__quest_file_cached = cached or await self.quest_file.all().first()
        return self.__quest_file_cached

    async def get_pc_file(self):
        cached = getattr(self, "__pc_file_cached", None)
        self.__pc_file_cached = cached or await self.pc_file.all().first()
        return self.__pc_file_cached

    async def get_last_file_change(self):
        pc_file = await self.get_pc_file()
        quest_file = await self.get_quest_file()

        match (pc_file, quest_file):
            case (PcModFile(added=pc_a), QuestModFile(added=q_a)):
                return max(pc_a, q_a)
            case (PcModFile(added=x), None) | (None, QuestModFile(added=x)):
                return x
            case (None, None):
                return None

    async def clear_files(self):
        quest_file = await self.get_quest_file()
        if quest_file is not None:
            await quest_file.delete()

        pc_file = await self.get_pc_file()
        if pc_file is not None:
            await pc_file.delete()


class PalletErrorBase(Model):
    id = fields.IntField(pk=True)
    error = fields.TextField()

    class Meta:
        abstract = True


class ModFileBase(Model):
    id: fields.IntField = fields.IntField(pk=True, generated=False)
    added = fields.DatetimeField()
    url = fields.TextField()

    mod: fields.ForeignKeyRelation[Mod]
    pallet_error: fields.ReverseRelation[PalletErrorBase]
    pallet: fields.ReverseRelation[PalletBase]

    class Meta:
        abstract = True


class PalletBase(Model):
    id = fields.IntField(pk=True)
    zip_path = fields.TextField()
    fs_path = fields.TextField()
    barcode = fields.TextField()
    author = fields.TextField()
    version = fields.TextField()
    sdkVersion = fields.TextField()

    class Meta:
        abstract = True


class QuestModFile(ModFileBase):
    mod: fields.OneToOneRelation[Mod] = fields.OneToOneField(
        "models.Mod", related_name="quest_file"
    )

    pallet_error: fields.ReverseRelation[QuestPalletError]
    pallet: fields.ReverseRelation[QuestPallet]

    class Meta:
        table = "quest_file"
        table_description = ""


class QuestPallet(PalletBase):
    file: fields.ForeignKeyRelation[QuestModFile] = fields.ForeignKeyField(
        "models.QuestModFile", related_name="pallet"
    )

    class Meta:
        table = "quest_pallet"
        table_description = ""


class QuestPalletError(PalletErrorBase):
    file: fields.OneToOneRelation[QuestModFile] = fields.OneToOneField(
        "models.QuestModFile", related_name="pallet_error"
    )

    class Meta:
        table = "quest_pallet_error"
        table_description = ""


class PcModFile(ModFileBase):
    mod: fields.OneToOneRelation[Mod] = fields.OneToOneField(
        "models.Mod", related_name="pc_file"
    )

    pallet_error: fields.ReverseRelation[PcPalletError]
    pallet: fields.ReverseRelation[PcPallet]

    class Meta:
        table = "pc_file"
        table_description = ""


class PcPallet(PalletBase):
    file: fields.ForeignKeyRelation[PcModFile] = fields.ForeignKeyField(
        "models.PcModFile", related_name="pallet"
    )

    class Meta:
        table = "pc_pallet"
        table_description = ""


class PcPalletError(PalletErrorBase):
    file: fields.OneToOneRelation[PcModFile] = fields.OneToOneField(
        "models.PcModFile", related_name="pallet_error"
    )

    class Meta:
        table = "pc_pallet_error"
        table_description = ""
