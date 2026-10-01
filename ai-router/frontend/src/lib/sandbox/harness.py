import ast
import builtins
import io
import json
import sys
import traceback


def _eq(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b or a == b and type(a) == type(b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < 1e-9
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_eq(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_eq(a[k], b[k]) for k in a)
    return a == b


def _parse_expected(text):
    try:
        return True, json.loads(text)
    except Exception:
        pass
    try:
        return True, ast.literal_eval(text)
    except Exception:
        return False, str(text).strip()


def _fmt_exc(e):
    tb = e.__traceback__.tb_next if e.__traceback__ is not None else None
    text = "".join(traceback.format_exception(type(e), e, tb)).strip()
    return text[-1500:]


def _no_input(*args, **kwargs):
    raise EOFError("input() isn't available in this console; use the values given in the task instead")


def _zorah_run(code, tests_json):
    tests = json.loads(tests_json)
    result = {"stdout": "", "error": None, "tests": []}
    builtins.input = _no_input
    g = {"__name__": "__main__"}

    buf = io.StringIO()
    real_out, real_err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = buf
    try:
        exec(compile(code, "<your code>", "exec"), g)
    except SystemExit:
        pass
    except BaseException as e:  # noqa: BLE001 - learner code can raise anything
        result["error"] = _fmt_exc(e)
    finally:
        sys.stdout, sys.stderr = real_out, real_err
    text = buf.getvalue()
    result["stdout"] = text[:20000] + ("\n…(output truncated)" if len(text) > 20000 else "")

    for t in tests:
        r = {"name": t.get("name", ""), "passed": False, "message": ""}
        try:
            if t.get("type") == "stdout":
                if result["error"]:
                    raise RuntimeError("your program stopped with an error, see the Errors tab")
                want = str(t.get("expected", "")).replace("\r", "").strip()
                got = text.replace("\r", "").strip()
                r["passed"] = got == want
                if not r["passed"]:
                    r["message"] = "expected output %r but got %r" % (want, got)
            else:
                if result["error"]:
                    raise RuntimeError("your code has an error, see the Errors tab")
                sys.stdout = sys.stderr = io.StringIO()
                try:
                    value = eval(t["expr"], g)
                finally:
                    sys.stdout, sys.stderr = real_out, real_err
                ok, expected = _parse_expected(t.get("expected", ""))
                r["passed"] = _eq(value, expected) if ok else str(value).strip() == expected
                if not r["passed"]:
                    r["message"] = "%s gave %r but should give %s" % (t["expr"], value, t.get("expected"))
        except BaseException as e:  # noqa: BLE001
            r["message"] = (type(e).__name__ + ": " + str(e)).strip(": ")
        result["tests"].append(r)
    return json.dumps(result)
