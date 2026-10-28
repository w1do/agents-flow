"""Case-insensitive protected components in paths and unstructured report text."""
import re


def sensitive(name):
    name = name.casefold()
    return (name.startswith((".env", "id_rsa", ".secrets")) or name.endswith((".pem", ".key", ".env"))
            or name in {".git", ".agent-token", ".npmrc", ".pypirc"})


# Keep escaped characters and quoted fragments together before inspecting names.
# Query tails stay attached so masking also removes all URL parameters.
TOKEN = re.compile(r"""(?:\\[\s\S]|'[^']*'|"(?:\\[\s\S]|[^"\\])*"|[^\s\\"'`<>;&|()\[\]{},:?#])+(?:[?#][^\s\"\'`<>;,]*)?""")
WORD = re.compile(r"[^\s\"\'`<>;&|()\[\]{},:?#]+(?:[?#][^\s\"\'`<>;,]*)?")
MEMBER = re.compile(r"[A-Za-z_$]\w*(?:\.\w+)*\.key")


def member_identifier(value):
    """Only benign member accesses qualify for the KeyboardEvent.key exception."""
    return bool(MEMBER.fullmatch(value)) and not any(
        sensitive(part) or sensitive("." + part) for part in value[:-4].split(".")
    )


def normalized(value):
    value = re.sub(r"\\\r?\n|\\([\s\S])", lambda match: match[1] or "", value)
    return re.sub(r"""(['"])(.*?)\1""", r"\2", value, flags=re.DOTALL)


def redact_paths(text):
    def replace(match):
        token = match[0]
        # Inspect both spellings: shell quoting must never weaken path masking.
        for form in (token, normalized(token)):
            for fragment in WORD.finditer(form):
                for word in re.split(r"[&|()\[\]{}]", fragment[0]):
                    path = re.split(r"[?#]", word, maxsplit=1)[0]
                    for candidate in path.split("="):
                        candidate = candidate.rstrip(".!")
                        if path == word and member_identifier(candidate):
                            continue
                        if any(sensitive(part) for part in candidate.split("/")):
                            if token[0] == token[-1] and token[0] in "'\"":
                                return token[0] + "[REDACTED]" + token[-1]
                            return "[REDACTED]"
        return token

    return TOKEN.sub(replace, text)
