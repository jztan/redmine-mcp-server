"""Append the server's text-formatting syntax block to text-writing tools (#440).

The block rides in the tool description, so the model reads the syntax rules
in the same place it reads how to call the tool, without having to remember
to ask first. Tools are copied, never mutated: the registered ``Tool`` objects
are shared by every request.
"""

import logging

from fastmcp.server.middleware import Middleware

from ._text_formatting import FORMATTED_TEXT_TOOLS, TEXT_BLOCKS, current_format

logger = logging.getLogger("redmine_mcp_server")


class TextFormattingMiddleware(Middleware):
    async def on_list_tools(self, context, call_next):
        tools = await call_next(context)
        if not any(tool.name in FORMATTED_TEXT_TOOLS for tool in tools):
            return tools
        try:
            value = (await current_format()).value
        except Exception as exc:  # tools/list must never fail over this
            logger.warning("text_formatting resolution failed: %s", exc)
            value = "unknown"
        block = TEXT_BLOCKS[value]
        return [
            (
                tool.model_copy(
                    update={
                        "description": f"{tool.description or ''}\n\n{block}".strip()
                    }
                )
                if tool.name in FORMATTED_TEXT_TOOLS
                else tool
            )
            for tool in tools
        ]
