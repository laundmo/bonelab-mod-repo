from __future__ import annotations

import json
import re
from contextlib import suppress
from dataclasses import dataclass
from functools import partial
from json import JSONEncoder
from typing import Any, Callable, ClassVar, Generic, Type, TypeVar


# Use __json__ or the default func
class SLZJSONEncoder(JSONEncoder):
    def default(self, o: Any):
        if isinstance(o, SLZContainer):
            return o.__json__()
        else:
            a = getattr(o.__class__, "__json__") or JSONEncoder.default(self, o)
            return a(o)


dumps = partial(json.dumps, cls=SLZJSONEncoder)
dump = partial(json.dump, cls=SLZJSONEncoder)

refable_types: dict[str, Type[Refable]] = {}


def reset():
    for typ in refable_types.values():
        typ.elements = {}


def object_hook(o: Any):
    # set refs where possible
    for key in o.keys():
        if key in refable_types:
            with suppress(ValueError):
                o[key] = Ref.from_str(o[key])

    # try making SLZContainer
    with suppress(ValueError):
        return SLZContainer.__from_json__(o)

    # try making Refable objects
    for typ in refable_types.values():
        with suppress(ValueError):
            return typ.__from_json__(o)
    return o


loads = partial(json.loads, object_hook=object_hook)
load = partial(json.load, object_hook=object_hook)


class RefableMeta(type):
    def __new__(cls: Type[Type[Refable]], name, bases, dct):  # type: ignore
        cls_obj = type.__new__(cls, name, bases, dct)
        if hasattr(cls_obj, "ref_pattern"):
            cls_obj.elements = {}
            refable_types[cls_obj.ref_key] = cls_obj
        return cls_obj

    def __call__(cls, *args, **kwargs):
        obj = type.__call__(cls, *args, **kwargs)
        class_ = type(obj)
        id_ = len(class_.elements) + 1
        obj.ref = Ref(class_, id_)
        class_.elements[id_] = obj
        return obj


class Refable(metaclass=RefableMeta):
    elements: ClassVar[dict[int, Refable]]
    ref_pattern: ClassVar[str]
    ref_key: ClassVar[str]
    ref: Ref

    @classmethod
    def __from_json__(cls, o: dict[str, Any]):
        raise NotImplementedError("Subclasses of Refable must implement __from_json__")

    def __json__(self):
        raise NotImplementedError("Subclasses of Refable must implement __json__")


class Ref:
    def __init__(self, reference: Type[Refable], id_: int):
        self.ref_type = reference
        self.ref_id = id_

    def __eq__(self, other: Ref):
        return self.ref_type == other.ref_type and self.ref_id == other.ref_id

    @property
    def ref(self):
        return self.ref_type.ref_pattern.format(self.ref_id)

    @classmethod
    def from_str(cls, ref: str) -> Ref:
        for refable in refable_types.values():
            match = re.match(refable.ref_pattern.replace("{}", r"(\d+)"), ref)
            if match is not None:
                return cls(refable, int(match.group(1)))
        else:
            raise ValueError("could not parse ref")

    def resolve(self):
        return self.ref_type.elements[self.ref_id]

    def __json__(self):
        return self.ref

    def __str__(self):
        return self.ref

    def __repr__(self):
        return f"<Ref {self.ref_id}:{self.ref_type.__name__}>"


@dataclass(eq=True)
class SLZType(Refable):
    ref_pattern: ClassVar[str] = "t:{}"
    ref_key: ClassVar[str] = "type"
    fullname: str

    def __json__(self):
        return {
            "type": str(self.ref),
            "fullname": self.fullname,
        }

    @classmethod
    def __from_json__(cls, o: dict[str, Any]):
        fullname = o.get("fullname")
        ref = o.get("type")
        if fullname is not None and ref is not None:
            obj = cls(fullname)
            obj.ref = ref
            return obj
        raise ValueError()

    def __repr__(self):
        return (
            f"<SLZType {self.ref.ref_id} {self.fullname.split(',')[0].split('.')[-1]}>"
        )


class SLZObject(Refable):
    ref_pattern = "o:{}"
    ref_key = "ref"

    def __init__(self, type_: Ref, **kwargs: Any):
        self.data = kwargs
        self.type = type_

    def __eq__(self, other: SLZObject) -> bool:
        return self.data == other.data and self.ref == other.ref

    def __json__(self):
        return {**self.data, "isa": {"type": self.type}}

    @classmethod
    def __from_json__(cls, o: dict[str, Any]):
        if "isa" in o.keys():
            isa = o.pop("isa")
            return cls(isa["type"], **o)
        raise ValueError()

    def __repr__(self):
        return f"<SLZObject {str(self.type)}>"


T = TypeVar("T", SLZType, SLZObject)


class SLZContainer(Generic[T]):
    def __init__(self, elements: list[T]):
        self.data = {e.ref.ref_id: e for e in elements}

    def __eq__(self, other: SLZContainer[T]):
        return all(s == o for s, o in zip(self.data.values(), other.data.values()))

    def __iter__(self):
        return iter(self.data.values())

    def __getitem__(self, item: int | Ref | str):
        if isinstance(item, int):
            return self.data[item]

        ref = Ref.from_str(item) if isinstance(item, str) else item
        return self.data[ref.ref_id]

    def __setitem__(self, item: int | Ref | str, value: T):
        if isinstance(item, int):
            self.data[item] = value
            return

        ref = Ref.from_str(item) if isinstance(item, str) else item
        self.data[ref.ref_id] = value

    def append(self, value: T):
        self.data[value.ref.ref_id] = value

    def __contains__(self, item: int | Ref | str):
        if isinstance(item, int):
            return item in self.data

        ref = Ref.from_str(item) if isinstance(item, str) else item
        return ref.ref_id in self.data

    def __len__(self):
        return len(self.data)

    def __json__(self):
        json_obj = {}
        for item in self.data.values():
            json_obj[str(item.ref)] = item.__json__()
        return json_obj

    @classmethod
    def __from_json__(cls, o: dict[str, Any]) -> SLZContainer[T]:
        obj = cls([])
        for ref, value in o.items():
            ref = Ref.from_str(ref)
            value.ref = ref
            obj.append(value)
        return obj

    def __repr__(self):
        return self.data.__repr__()


class RefList:
    def __init__(
        self,
        container: SLZContainer[SLZObject],
        filter_: Callable[[SLZObject], bool] = lambda x: True,
    ) -> None:
        self.container = container
        self.filter = filter_

    def __json__(self):
        result = []
        for item in self.container:
            if self.filter(item):
                result.append(
                    {
                        "ref": item.ref,
                        "type": item.type.ref,
                    }
                )
        return result


def test():
    b = SLZType("TestType1")

    a = {
        "types": SLZContainer(
            [
                b,
                SLZType("TestType2"),
                SLZType("TestType3"),
                SLZType("TestType4"),
                SLZType("TestType5"),
            ]
        ),
        "mods": SLZContainer(
            [SLZObject(b.ref, randomdata="yooo"), SLZObject(b.ref, randomdata="boooo")]
        ),
    }

    a_str = dumps(a)
    print(a_str)

    loaded = loads(a_str)
    assert a == loaded
    print("successful roundtrip")
    with open("./static/pallets/2971377_0.json") as f:
        pallet = load(f)

    pallet["objects"]

    with open("./static/pallets/2971377_0_new.json", "w+") as f:
        dump(pallet, f)


if __name__ == "__main__":
    test()
