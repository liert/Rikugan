"""Shared helpers for Binary Ninja tool modules."""

from __future__ import annotations

import inspect
from typing import Any, Iterable, List, Optional, Sequence, Tuple

from ...core.errors import ToolError
from ...core.host import get_binary_ninja_view, get_current_address, navigate_to, set_current_address
from ...core.logging import log_debug


def get_bn_module() -> Any:
    try:
        import binaryninja as bn  # type: ignore[import-not-found]
    except Exception as e:  # pragma: no cover - runtime guarded by host detection
        raise ToolError(f"Binary Ninja API unavailable: {e}") from e
    return bn


def require_bv() -> Any:
    bv = get_binary_ninja_view()
    if bv is None:
        raise ToolError(
            "No active BinaryView. Open a binary in Binary Ninja and invoke Rikugan from that view.",
        )
    return bv


def current_ea_or_default(default: int = 0) -> int:
    ea = get_current_address()
    return int(ea) if ea is not None else int(default)


def parse_addr_like(value: Any) -> int:
    if isinstance(value, int):
        return value
    return int(str(value), 0)


def call_compat(obj: Any, *method_names: str, default: Any = None, **kwargs: Any) -> Any:
    """Call first existing method name on *obj*, returning default on failure."""
    for name in method_names:
        meth = getattr(obj, name, None)
        if not callable(meth):
            continue
        try:
            return meth(**kwargs)
        except TypeError:
            # Some BN APIs are positional-only across versions.
            if kwargs:
                try:
                    return meth(*kwargs.values())
                except Exception as _e:
                    log_debug(f"call_compat positional fallback failed for {name}: {_e}")
                    continue
        except Exception as _e:
            log_debug(f"call_compat failed for {name}: {_e}")
            continue
    return default


def get_function_at(bv: Any, ea: int) -> Any:
    ea = int(ea)
    f = call_compat(bv, "get_function_at", default=None, addr=ea)
    if f is not None:
        return f
    f = call_compat(bv, "get_function_at", default=None, address=ea)
    if f is not None:
        return f

    get_containing = getattr(bv, "get_functions_containing", None)
    if callable(get_containing):
        try:
            funcs = list(get_containing(ea))
            if funcs:
                return funcs[0]
        except Exception as e:
            log_debug(f"get_functions_containing failed at 0x{ea:x}: {e}")
    return None


def get_function_name(func: Any) -> str:
    name = getattr(func, "name", None)
    if name:
        return str(name)
    sym = getattr(func, "symbol", None)
    if sym is not None:
        sname = getattr(sym, "full_name", None) or getattr(sym, "name", None)
        if sname:
            return str(sname)
    start = getattr(func, "start", 0)
    return f"sub_{int(start):x}"


def get_function_end(func: Any) -> int:
    for attr in ("highest_address", "end", "highestAddress"):
        v = getattr(func, attr, None)
        if isinstance(v, int) and v >= int(getattr(func, "start", 0)):
            return int(v)

    try:
        addrs = list(iter_function_instruction_addresses(func))
        if addrs:
            return max(addrs) + 1
    except Exception as e:
        log_debug(f"iter_function_instruction_addresses failed: {e}")
    return int(getattr(func, "start", 0))


def iter_functions(bv: Any) -> List[Any]:
    funcs = list(getattr(bv, "functions", []) or [])
    try:
        funcs.sort(key=lambda f: int(getattr(f, "start", 0)))
    except Exception as e:
        log_debug(f"Function sort failed: {e}")
    return funcs


def get_instruction_len(bv: Any, ea: int) -> int:
    ea = int(ea)
    for name in ("get_instruction_length", "getInstructionLength"):
        meth = getattr(bv, name, None)
        if callable(meth):
            try:
                l = int(meth(ea))
                if l > 0:
                    return l
            except Exception as e:
                log_debug(f"get_instruction_len {name} failed at 0x{ea:x}: {e}")
                continue

    text = get_disassembly_line(bv, ea)
    if text:
        return 1
    return 0


def get_instruction_text_tokens(bv: Any, ea: int) -> Tuple[List[Any], int]:
    ea = int(ea)
    meth = getattr(bv, "get_instruction_text", None)
    if callable(meth):
        try:
            res = meth(ea)
            if isinstance(res, tuple) and len(res) == 2:
                toks, l = res
                return list(toks or []), int(l or 0)
        except Exception as e:
            log_debug(f"get_instruction_text failed at 0x{ea:x}: {e}")
    return [], 0


def render_tokens(tokens: Sequence[Any]) -> str:
    out = []
    for t in tokens:
        txt = getattr(t, "text", None)
        if txt is None:
            txt = str(t)
        out.append(str(txt))
    return "".join(out).strip()


def get_disassembly_line(bv: Any, ea: int) -> str:
    ea = int(ea)
    for name in ("get_disassembly", "getDisassembly"):
        meth = getattr(bv, name, None)
        if callable(meth):
            try:
                text = meth(ea)
                if text:
                    return str(text)
            except Exception as e:
                log_debug(f"get_disassembly_line {name} failed at 0x{ea:x}: {e}")
                continue
    toks, _ = get_instruction_text_tokens(bv, ea)
    return render_tokens(toks)


def iter_function_instruction_addresses(func: Any, max_instructions: int = 100000) -> Iterable[int]:
    count = 0
    for bb in list(getattr(func, "basic_blocks", []) or []):
        start = int(getattr(bb, "start", 0))
        end = int(getattr(bb, "end", start))
        ea = start
        while ea < end and count < max_instructions:
            yield ea
            count += 1
            # Fall back to 1-byte stepping when instruction length is unknown.
            ilen = 1
            view = getattr(func, "view", None)
            if view is not None:
                l = get_instruction_len(view, ea)
                if l > 0:
                    ilen = l
            ea += max(1, ilen)


def get_symbol_at(bv: Any, ea: int) -> Any:
    ea = int(ea)
    for name in ("get_symbol_at", "getSymbolAt"):
        meth = getattr(bv, name, None)
        if callable(meth):
            try:
                sym = meth(ea)
                if sym is not None:
                    return sym
            except Exception as e:
                log_debug(f"get_symbol_at {name} failed at 0x{ea:x}: {e}")
                continue
    return None


def symbol_name(sym: Any) -> str:
    if sym is None:
        return ""
    return str(
        getattr(sym, "full_name", None)
        or getattr(sym, "short_name", None)
        or getattr(sym, "name", None)
        or ""
    )


def get_name_at(bv: Any, ea: int) -> str:
    sym = get_symbol_at(bv, ea)
    if sym is not None:
        name = symbol_name(sym)
        if name:
            return name

    func = get_function_at(bv, ea)
    if func is not None:
        return get_function_name(func)
    return ""


def iter_symbols(bv: Any) -> List[Any]:
    symbols: List[Any] = []
    get_symbols = getattr(bv, "get_symbols", None)
    if callable(get_symbols):
        try:
            symbols = list(get_symbols())
        except Exception as e:
            log_debug(f"get_symbols() failed: {e}")
            symbols = []

    if not symbols:
        raw = getattr(bv, "symbols", None)
        if isinstance(raw, dict):
            for _, val in raw.items():
                if isinstance(val, list):
                    symbols.extend(val)
                else:
                    symbols.append(val)
        elif raw is not None:
            try:
                symbols = list(raw)
            except Exception as e:
                log_debug(f"iter bv.symbols failed: {e}")
                symbols = []

    return symbols


def iter_symbols_by_name(bv: Any, name: str) -> List[Any]:
    get_by_name = getattr(bv, "get_symbols_by_name", None)
    if callable(get_by_name):
        try:
            return list(get_by_name(name))
        except Exception as e:
            log_debug(f"get_symbols_by_name({name!r}) failed: {e}")
    return [s for s in iter_symbols(bv) if symbol_name(s) == name]


def symbol_type_name(sym: Any) -> str:
    t = getattr(sym, "type", None)
    if t is None:
        return ""
    n = getattr(t, "name", None)
    if n:
        return str(n)
    return str(t)


def is_import_symbol(sym: Any) -> bool:
    tname = symbol_type_name(sym).lower()
    return "import" in tname or "external" in tname


def is_export_symbol(sym: Any) -> bool:
    tname = symbol_type_name(sym).lower()
    return "export" in tname


def symbol_address(sym: Any) -> Optional[int]:
    for attr in ("address", "addr", "raw_name_addr"):
        v = getattr(sym, attr, None)
        if isinstance(v, int):
            return int(v)
    return None


def _build_user_symbol(bn: Any, sym_type: Any, ea: int, new_name: str) -> Any:
    symbol_cls = getattr(bn, "Symbol", None)
    if symbol_cls is None:
        return None
    try:
        return symbol_cls(sym_type, int(ea), new_name)
    except TypeError:
        # Some versions accept optional short/full names.
        try:
            return symbol_cls(sym_type, int(ea), new_name, new_name)
        except Exception as e:
            log_debug(f"Symbol constructor failed at 0x{ea:x}: {e}")
            return None


def rename_symbol_at(bv: Any, ea: int, new_name: str) -> bool:
    bn = get_bn_module()
    ea = int(ea)
    sym = get_symbol_at(bv, ea)
    sym_type = None
    if sym is not None:
        sym_type = getattr(sym, "type", None)
    if sym_type is None:
        st = getattr(bn, "SymbolType", None)
        sym_type = getattr(st, "FunctionSymbol", None) if st is not None else None

    new_sym = _build_user_symbol(bn, sym_type, ea, new_name)
    if new_sym is None:
        return False

    for name in ("define_user_symbol", "defineUserSymbol"):
        meth = getattr(bv, name, None)
        if callable(meth):
            try:
                meth(new_sym)
                return True
            except Exception as e:
                log_debug(f"rename_symbol_at {name} failed at 0x{ea:x}: {e}")
                continue
    return False


def get_comment_at(bv: Any, ea: int) -> str:
    ea = int(ea)
    for name in ("get_comment_at", "getCommentAt"):
        meth = getattr(bv, name, None)
        if callable(meth):
            try:
                c = meth(ea)
                if c:
                    return str(c)
            except Exception as e:
                log_debug(f"get_comment_at {name} failed at 0x{ea:x}: {e}")
                continue
    return ""


def set_comment_at(bv: Any, ea: int, comment: str) -> bool:
    ea = int(ea)
    for name in ("set_comment_at", "setCommentAt"):
        meth = getattr(bv, name, None)
        if callable(meth):
            try:
                meth(ea, comment)
                return True
            except Exception as e:
                log_debug(f"set_comment_at {name} failed at 0x{ea:x}: {e}")
                continue
    return False


def parse_type_string(bv: Any, type_src: str) -> tuple[Any, str]:
    """Parse C type text and return (type_obj, parsed_name)."""
    parse_fn = getattr(bv, "parse_type_string", None)
    if callable(parse_fn):
        try:
            res = parse_fn(type_src)
            if isinstance(res, tuple) and len(res) >= 2:
                return res[0], str(res[1] or "")
            # Some versions return object with type/name attributes.
            t = getattr(res, "type", None)
            n = getattr(res, "name", "")
            if t is not None:
                return t, str(n or "")
        except Exception as e:
            log_debug(f"bv.parse_type_string failed for {type_src!r}: {e}")

    bn = get_bn_module()
    parse_global = getattr(bn, "parse_type_string", None)
    if callable(parse_global):
        try:
            res = parse_global(type_src, getattr(bv, "platform", None))
            if isinstance(res, tuple) and len(res) >= 2:
                return res[0], str(res[1] or "")
        except Exception as e:
            log_debug(f"bn.parse_type_string failed for {type_src!r}: {e}")

    raise ToolError(f"Failed to parse type string: {type_src}")


def define_user_type(bv: Any, name: str, t: Any) -> bool:
    for meth_name in ("define_user_type", "defineUserType"):
        meth = getattr(bv, meth_name, None)
        if callable(meth):
            try:
                meth(name, t)
                return True
            except Exception as e:
                log_debug(f"define_user_type {meth_name}({name!r}) failed: {e}")
                continue
    return False


def update_analysis_and_wait(bv: Any) -> None:
    for name in ("update_analysis_and_wait", "updateAnalysisAndWait"):
        meth = getattr(bv, name, None)
        if callable(meth):
            try:
                meth()
                return
            except Exception as e:
                log_debug(f"update_analysis_and_wait {name} failed: {e}")
                continue


def navigate(ea: int) -> bool:
    ok = navigate_to(int(ea))
    if ok:
        set_current_address(int(ea))
    return ok


def py_signature_accepts(func: Any, argc: int) -> bool:
    try:
        sig = inspect.signature(func)
    except Exception:
        return False
    params = list(sig.parameters.values())
    required = [
        p for p in params
        if p.default is inspect._empty
        and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    return len(required) <= argc <= len(params)
