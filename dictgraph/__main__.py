"""Run: python -m dictgraph"""

from __future__ import annotations

import argparse
from pathlib import Path

from dictgraph.converter import convert

ROOT = Path(__file__).resolve().parent
DICT_DATA = ROOT / "dict_data"
OUTPUT = ROOT / "output"
DEFAULT_KEYWORDS_SEED = ROOT / "keywords_seed.json"


def _cmd_convert(args: argparse.Namespace) -> None:
    paths = convert(
        args.dict_data,
        args.output,
        keywords_seed=args.keywords_seed,
    )
    print("Wrote ontology CSV files:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


def _print_frame(title: str, df) -> None:
    print(f"\n{title} ({len(df)} rows)")
    if df.empty:
        print("  (no matches)")
        return
    print(df.to_string(index=False))


def _cmd_search(args: argparse.Namespace) -> None:
    from dictgraph.search import DictGraphIndex, RISK_TIERS

    index = DictGraphIndex.load(args.output)

    if args.tree:
        _print_frame(f"Category tree under '{args.tree}'", index.category_tree(args.tree))

    if args.categories:
        _print_frame(
            f"Categories matching '{args.categories}'",
            index.search_categories(args.categories, subtree=args.subtree),
        )

    if args.tier and not args.words:
        _print_frame(
            f"Categories in tier '{args.tier}'",
            index.categories_by_tier(args.tier),
        )

    if args.words:
        _print_frame(
            f"Words matching '{args.words}'",
            index.search_words(
                args.words,
                pos=args.pos,
                register=args.register,
                domain=args.domain,
                tier=args.tier,
                category=args.category,
            ),
        )

    if args.category and not args.words:
        _print_frame(
            f"Words in category '{args.category}'",
            index.words_in_category(args.category, include_descendants=not args.exact_category),
        )

    if args.pairs:
        _print_frame(f"Word pairs for '{args.pairs}'", index.word_pairs_for(args.pairs))

    if not any(
        [args.tree, args.categories, args.tier, args.words, args.category, args.pairs]
    ):
        print("No search filters provided. Examples:")
        print('  python -m dictgraph search --categories "hack"')
        print("  python -m dictgraph search --tier high")
        print('  python -m dictgraph search --words "firewall" --domain security')
        print("  python -m dictgraph search --tree lexicon")
        print(f"  Tiers: {', '.join(RISK_TIERS)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Dictgraph converter and CSV search.")
    sub = parser.add_subparsers(dest="command")

    convert_parser = sub.add_parser("convert", help="Convert dict .txt files to CSV graphs.")
    convert_parser.add_argument("--dict-data", type=Path, default=DICT_DATA)
    convert_parser.add_argument("--output", type=Path, default=OUTPUT)
    convert_parser.add_argument("--keywords-seed", type=Path, default=DEFAULT_KEYWORDS_SEED)
    convert_parser.set_defaults(func=_cmd_convert)

    search_parser = sub.add_parser("search", help="Search generated CSV graphs with pandas.")
    search_parser.add_argument("--output", type=Path, default=OUTPUT)
    search_parser.add_argument("--categories", type=str, default="", help="Substring match on category names.")
    search_parser.add_argument("--subtree", type=str, default="", help="Limit category search to a subtree root.")
    search_parser.add_argument("--tier", type=str, default="", help="Risk tier filter.")
    search_parser.add_argument("--words", type=str, default="", help="Substring match on words/meanings/tags.")
    search_parser.add_argument("--pos", type=str, default="")
    search_parser.add_argument("--register", type=str, default="")
    search_parser.add_argument("--domain", type=str, default="")
    search_parser.add_argument("--category", type=str, default="", help="Filter words by category name.")
    search_parser.add_argument(
        "--exact-category",
        action="store_true",
        help="Match category exactly (no descendant categories).",
    )
    search_parser.add_argument("--pairs", type=str, default="", help="Show word pairs involving this word.")
    search_parser.add_argument("--tree", type=str, default="", help="Print category tree from this root.")
    search_parser.set_defaults(func=_cmd_search)

    args = parser.parse_args()
    if args.command is None:
        args = parser.parse_args(["convert"])
        args.func = _cmd_convert
    args.func(args)


if __name__ == "__main__":
    main()
