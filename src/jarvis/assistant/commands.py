"""Transport command names, independent of database and provider dependencies."""

SLASH_COMMANDS = frozenset(
    {
        "ask",
        "approve",
        "toolapprove",
        "toolstatus",
        "cancel",
        "remember",
        "memory",
        "forget",
        "new",
        "clear",
        "ai",
        "restricted",
        "docs",
        "doc",
        "askdoc",
        "deldoc",
    }
)

# Internal chat ingress uses the same privacy, pairing, budget and queue gates as /ask.
# It is deliberately not a public /chat command.
INFERENCE_COMMANDS = frozenset({"ask", "chat"})
