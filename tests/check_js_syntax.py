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
    print(f"{path}: parses cleanly")
    return True

if __name__ == "__main__":
    sys.exit(0 if all(check(p) for p in (sys.argv[1:] or ["app.js"])) else 1)
