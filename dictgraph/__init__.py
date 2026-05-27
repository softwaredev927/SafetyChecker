"""Dictionary file to CSV ontology graph converter."""

from dictgraph.converter import convert, load_dict_files, parse_text_dict_file

__all__ = [
    "convert",
    "load_dict_files",
    "parse_text_dict_file",
    "DictGraphIndex",
    "RISK_TIERS",
]


def __getattr__(name: str):
    if name in ("DictGraphIndex", "RISK_TIERS"):
        from dictgraph.search import DictGraphIndex, RISK_TIERS

        return DictGraphIndex if name == "DictGraphIndex" else RISK_TIERS
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
