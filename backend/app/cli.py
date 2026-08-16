from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.core.models import RewriteSettings
from backend.app.nlp.analyzer import load_user_terms
from backend.app.service.rewrite_service import RewriteService


def _settings_from_args(args: argparse.Namespace) -> RewriteSettings:
    terms = list(args.protect_term or [])
    if args.dictionary:
        terms.extend(load_user_terms(Path(args.dictionary)))
    return RewriteSettings(
        rewrite_scope=args.rewrite_scope,
        strength=args.strength,
        preserve_layout=not args.no_preserve_layout,
        layout_sensitivity=args.layout_sensitivity,
        protect_terms=terms,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="local-rewrite")
    subparsers = parser.add_subparsers(dest="command", required=True)

    text_parser = subparsers.add_parser("rewrite-text")
    text_parser.add_argument("--text", required=True)
    text_parser.add_argument("--rewrite-scope", choices=("lexical", "lexical_and_sentence"), default="lexical")
    text_parser.add_argument("--strength", type=int, choices=(1, 2, 3), default=2)
    text_parser.add_argument("--layout-sensitivity", choices=("STRICT", "NORMAL", "LOOSE"), default="STRICT")
    text_parser.add_argument("--no-preserve-layout", action="store_true")
    text_parser.add_argument("--protect-term", action="append")
    text_parser.add_argument("--dictionary")

    document_parser = subparsers.add_parser("rewrite-document")
    document_parser.add_argument("input_file")
    document_parser.add_argument("--output-dir")
    document_parser.add_argument("--rewrite-scope", choices=("lexical", "lexical_and_sentence"), default="lexical")
    document_parser.add_argument("--strength", type=int, choices=(1, 2, 3), default=2)
    document_parser.add_argument("--layout-sensitivity", choices=("STRICT", "NORMAL", "LOOSE"), default="STRICT")
    document_parser.add_argument("--no-preserve-layout", action="store_true")
    document_parser.add_argument("--protect-term", action="append")
    document_parser.add_argument("--dictionary")

    subparsers.add_parser("model-status")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    service = RewriteService()
    if args.command == "model-status":
        print(json.dumps(service.model_status(), ensure_ascii=False, indent=2))
        return 0
    rewrite_settings = _settings_from_args(args)
    if args.command == "rewrite-text":
        result = service.rewrite_text(args.text, rewrite_settings)
    else:
        source = Path(args.input_file).resolve()
        result = service.rewrite_file(
            source,
            rewrite_settings=rewrite_settings,
            job_dir=Path(args.output_dir).resolve() if args.output_dir else None,
        )
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
