from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from backend.app.core.models import RewriteSettings
from backend.app.service.rewrite_service import RewriteService


TOOLS = [
    {
        "name": "rewrite_text",
        "description": "Run the complete fail-closed lexical rewrite pipeline on local text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "rewrite_scope": {"type": "string", "enum": ["lexical", "lexical_and_sentence"], "default": "lexical"},
                "strength": {"type": "integer", "enum": [1, 2, 3], "default": 2},
                "preserve_layout": {"type": "boolean", "default": True},
                "protect_terms": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["text"],
        },
    },
    {
        "name": "rewrite_document",
        "description": "Run the complete fail-closed lexical rewrite pipeline on a local TXT or DOCX file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "input_file": {"type": "string"},
                "rewrite_scope": {"type": "string", "enum": ["lexical", "lexical_and_sentence"], "default": "lexical"},
                "strength": {"type": "integer", "enum": [1, 2, 3], "default": 2},
                "preserve_layout": {"type": "boolean", "default": True},
                "protect_terms": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["input_file"],
        },
    },
]


def _result_content(payload: Any) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False),
            }
        ]
    }


def _handle_tool(name: str, arguments: dict[str, Any], service: RewriteService) -> dict[str, Any]:
    rewrite_settings = RewriteSettings(
        rewrite_scope=arguments.get("rewrite_scope", "lexical"),
        strength=arguments.get("strength", 2),
        preserve_layout=arguments.get("preserve_layout", True),
        protect_terms=arguments.get("protect_terms", []),
        user_terms=arguments.get("user_terms", []),
    )
    if name == "rewrite_text":
        result = service.rewrite_text(arguments["text"], rewrite_settings)
        rewritten_text = arguments["text"]
        if result.output_file and Path(result.output_file).exists():
            rewritten_text = Path(result.output_file).read_text(encoding="utf-8")
        return {
            "success": result.success,
            "changes": result.audit.changed,
            "rejected": result.audit.rejected,
            "protected": result.audit.protected,
            "output_file": result.output_file,
            "audit_file": result.audit_file,
            "rewritten_text": rewritten_text,
        }
    if name == "rewrite_document":
        result = service.rewrite_file(Path(arguments["input_file"]).resolve(), rewrite_settings=rewrite_settings)
        return {
            "success": result.success,
            "changes": result.audit.changed,
            "rejected": result.audit.rejected,
            "protected": result.audit.protected,
            "output_file": result.output_file,
            "audit_file": result.audit_file,
        }
    raise ValueError(f"Unknown tool: {name}")


def main() -> None:
    service = RewriteService()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            method = request.get("method")
            request_id = request.get("id")
            if method == "initialize":
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "local-rewrite-desk", "version": "0.1.0"},
                    },
                }
            elif method == "notifications/initialized":
                continue
            elif method == "tools/list":
                response = {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
            elif method == "tools/call":
                params = request.get("params", {})
                payload = _handle_tool(params["name"], params.get("arguments", {}), service)
                response = {"jsonrpc": "2.0", "id": request_id, "result": _result_content(payload)}
            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
        except Exception as exc:
            response = {
                "jsonrpc": "2.0",
                "id": request.get("id") if isinstance(request, dict) else None,
                "error": {"code": -32000, "message": str(exc)},
            }
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
