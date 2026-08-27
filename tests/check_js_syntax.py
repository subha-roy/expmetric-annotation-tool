"""Parse app.js. esprima predates a few operators the app legitimately uses, so those
are normalized away before parsing -- this checks structure, not grammar level."""
import re, sys, esprima

def check(path):
    s = open(path).read()
    t = s.replace("||=", "=").replace("&&=", "=").replace("??=", "=")
    t = re.sub(r"\bcatch\s*\{", "catch (_e) {", t)   # optional catch binding
    t = re.sub(r"\?\.(?=[(\[])", "", t)                # optional call/index
    t = t.replace("?.", ".")                          # optional chaining
    t = t.replace("??", "||")                         # nullish coalescing
    try:
        esprima.parseScript(t, {"tolerant": False})
    except Exception as e:
        print(f"{path}: SYNTAX ERROR: {e}")
        ln = getattr(e, "lineNumber", None)
        if ln:
            for i in range(max(0, ln - 4), min(len(t.splitlines()), ln + 3)):
                print(f"{i+1:5d}| {t.splitlines()[i]}")
        return False
    if not check_defined(t, path):
        return False
    print(f"{path}: parses cleanly, all called helpers defined")
    return True


GLOBALS = {
    "if", "for", "while", "switch", "catch", "return", "typeof", "function", "new",
    "await", "else", "do", "try", "throw", "delete", "void", "in", "of", "case",
    "parseInt", "parseFloat", "isNaN", "String", "Number", "Boolean", "Array",
    "Object", "JSON", "Math", "Date", "Promise", "Set", "Map", "Error", "RegExp",
    "Uint8Array", "TextEncoder", "TextDecoder", "Blob", "URL", "FileReader",
    "atob", "btoa", "fetch", "alert", "confirm", "setTimeout", "clearTimeout",
    "setInterval", "requestAnimationFrame", "indexedDB", "crypto", "console",
    "document", "window", "localStorage", "structuredClone", "encodeURIComponent",
}


def check_defined(src, path):
    """Catch a call to a top-level helper that was never defined -- a parse-clean file
    that throws ReferenceError the moment it loads."""
    # comments and string/template literals are not code: scanning them invents
    # "calls" out of ordinary prose like "the sample (below)"
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    src = re.sub(r"//[^\n]*", " ", src)
    src = re.sub(r"`(?:\\.|[^`\\])*`", '""', src, flags=re.S)
    src = re.sub(r"'(?:\\.|[^'\\\n])*'", '""', src)
    src = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', src)
    declared = set(re.findall(r"\b(?:function|const|let|var)\s+([A-Za-z_$][\w$]*)", src))
    declared |= set(re.findall(r"\b(?:const|let|var)\s*\{([^}]*)\}", src) and
                    [n.strip() for grp in re.findall(r"\b(?:const|let|var)\s*\{([^}]*)\}", src)
                     for n in grp.split(",")])
    declared |= set(re.findall(r"([A-Za-z_$][\w$]*)\s*=>", src))          # arrow params
    declared |= set(re.findall(r"function\s*\(([^)]*)\)", src) and
                    [n.strip().lstrip("...") for grp in re.findall(r"\(([^)]*)\)\s*=>", src)
                     for n in grp.split(",")])
    for grp in re.findall(r"\(([^()]*)\)\s*=>", src):        # arrow params
        declared |= {n.strip().lstrip(".") for n in grp.split(",") if n.strip()}
    called = set(re.findall(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(", src))
    missing = sorted(n for n in called - declared - GLOBALS if not n.isupper())
    if missing:
        print(f"{path}: CALLED BUT NEVER DEFINED: {missing}")
        return False
    return True

if __name__ == "__main__":
    sys.exit(0 if all(check(p) for p in (sys.argv[1:] or ["app.js"])) else 1)
