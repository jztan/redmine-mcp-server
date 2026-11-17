"""Put the email hint into the description of the tools that mail (#401).

The hint rides in the tool description, so the model reads it before it
plans its calls. It is added in ``tools/list`` rather than at registration:
there the description is already the part of the docstring before ``Args``,
which is what FastMCP serves. Tools are copied, never mutated: the registered
``Tool`` objects are shared by every request.
"""

from fastmcp.server.middleware import Middleware

from ._notifications import MAIL_EFFECTS, mail_hint, with_mail_hint

# The table is fixed, so which tools carry a hint is known at import.
HINTED_TOOLS = frozenset(name for name in MAIL_EFFECTS if mail_hint(name))


class MailHintMiddleware(Middleware):
    async def on_list_tools(self, context, call_next):
        tools = await call_next(context)
        return [
            (
                tool.model_copy(
                    update={"description": with_mail_hint(tool.name, tool.description)}
                )
                if tool.name in HINTED_TOOLS
                else tool
            )
            for tool in tools
        ]
