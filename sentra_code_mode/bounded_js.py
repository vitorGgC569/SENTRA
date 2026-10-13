"""Built-in bounded JS-subset interpreter (stdlib only, no eval/exec/subprocess).

INTERIM ENGINE — explicitly NOT the A08 solution. A08 is satisfied only by
engine 'quickjs-wasm' with the pinned guest artifact (guest/ABI.md v1).
This interpreter exists so development/composition can proceed without the
guest binary; every receipt produced through it carries a08_satisfied=false.

Documented subset (deterministic, no host I/O, no imports):
  - literals: numbers, double/single-quoted strings, true/false/null,
    arrays [..], objects {k: v}
  - var/let/const declarations, assignment (=, +=, -=, *=, /=, %=)
  - arithmetic + - * / % **, unary - !, comparisons, && ||, ternary ?:
  - if/else, while, for(init; cond; incr), function name(a,..){..}, return
  - call_tool("name", {...}) as the ONLY host bridge (validated by caller)
  - final value: last expression statement or explicit `return`

Every statement and every loop iteration consumes fuel. Values are bounded by
count and encoded size (memory_bytes). Tool calls are counted and their
argument bytes bounded. No Date/Math.random/network/timers/imports/eval.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from . import CodeModeBudgetExceeded, CodeModeCancelled

_TOKEN = re.compile(r"""
    (?P<ws>\s+|//[^\n]*|/\*.*?\*/)
  | (?P<num>\d+(?:\.\d+)?)
  | (?P<str>"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')
  | (?P<name>[A-Za-z_$][A-Za-z0-9_$]*)
  | (?P<op>\*\*|===|!==|==|!=|<=|>=|&&|\|\||\+=|-=|\*=|/=|%=|[+\-*/%<>=!?:;,()\{\}\[\].])
""", re.X | re.S)

_KEYWORDS = {"var", "let", "const", "if", "else", "while", "for", "function",
             "return", "true", "false", "null"}


class _JSReturn(Exception):
    def __init__(self, value):
        self.value = value


class BoundedJSRunner:
    """Stateless interpreter; one instance per execution (holds budgets)."""

    def __init__(self, *, fuel: int, memory_bytes: int, max_tool_calls: int,
                 max_arg_bytes: int, max_result_bytes: int,
                 call_tool: Callable[[str, Any], Any] | None = None, cancel_event=None):
        self.fuel_left = fuel
        self.fuel_total = fuel
        self.memory_bytes = memory_bytes
        self.values_size = 0
        self.max_tool_calls = max_tool_calls
        self.max_arg_bytes = max_arg_bytes
        self.max_result_bytes = max_result_bytes
        self.tool_calls = 0
        self.call_tool_bridge = call_tool
        self.depth = 0
        self.cancel_event = cancel_event

    # -- public ----------------------------------------------------------
    def run(self, source: str) -> tuple[Any, dict[str, int]]:
        tokens = self._lex(source)
        program = _Parser(tokens).program()
        env: dict[str, Any] = {}
        consts: set[str] = set()
        result = None
        for stmt in program:
            self._burn(1)
            try:
                value = self._exec(stmt, env, consts)
            except _JSReturn as done:
                result = done.value
                break
            if value is not _VOID:
                result = value
        raw = json.dumps(result, ensure_ascii=False, allow_nan=False,
                         separators=(",", ":")).encode("utf-8")
        if len(raw) > self.max_result_bytes:
            raise CodeModeBudgetExceeded("result exceeds max_result_bytes")
        usage = {"fuel_used": self.fuel_total - self.fuel_left,
                 "tool_calls": self.tool_calls,
                 "result_bytes": len(raw)}
        return result, usage

    # -- budgets ---------------------------------------------------------
    def _burn(self, n: int) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise CodeModeCancelled("interim execution cancelled")
        self.fuel_left -= n
        if self.fuel_left < 0:
            raise CodeModeBudgetExceeded("fuel exhausted")

    def _account(self, value: Any) -> None:
        try:
            size = len(json.dumps(value, ensure_ascii=False, allow_nan=False,
                                  separators=(",", ":")).encode("utf-8"))
        except (TypeError, ValueError):
            raise CodeModeBudgetExceeded("unserializable value")
        self.values_size += size
        if self.values_size > self.memory_bytes:
            raise CodeModeBudgetExceeded("memory budget exceeded")

    # -- lexer -----------------------------------------------------------
    def _lex(self, source: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        pos = 0
        while pos < len(source):
            match = _TOKEN.match(source, pos)
            if not match:
                raise SyntaxError(f"unexpected character at offset {pos}")
            pos = match.end()
            kind = match.lastgroup or "ws"
            text = match.group()
            if kind == "ws":
                continue
            out.append((kind, text))
        return out

    # -- execution -------------------------------------------------------
    def _exec(self, node, env, consts):
        self._burn(1)
        kind = node[0]
        if kind == "expr":
            return self._eval(node[1], env)
        if kind == "declare":
            _, decl, name, init = node
            if name in consts:
                raise SyntaxError("const redeclaration: " + name)
            value = self._eval(init, env) if init is not None else None
            self._account(value)
            if decl == "const":
                consts.add(name)
            env[name] = value
            return _VOID
        if kind == "assign":
            _, name, op, expr = node
            if name in consts:
                raise SyntaxError("const assignment: " + name)
            value = self._eval(expr, env)
            current = env.get(name, 0)
            if op == "=":
                env[name] = value
            elif op == "+=":
                env[name] = self._add(current, value)
            elif op == "-=":
                env[name] = current - value
            elif op == "*=":
                env[name] = current * value
            elif op == "/=":
                env[name] = current / value if value else self._div0()
            elif op == "%=":
                env[name] = current % value if value else self._div0()
            self._account(env[name])
            return _VOID
        if kind == "if":
            _, cond, then, otherwise = node
            branch = then if self._truthy(self._eval(cond, env)) else otherwise
            result = _VOID
            for stmt in branch or []:
                self._burn(1)
                value = self._exec(stmt, env, consts)
                if value is not _VOID:
                    result = value
            return result
        if kind == "while":
            _, cond, body = node
            result = _VOID
            while self._truthy(self._eval(cond, env)):
                self._burn(2)
                for stmt in body:
                    self._burn(1)
                    value = self._exec(stmt, env, consts)
                    if value is not _VOID:
                        result = value
            return result
        if kind == "for":
            _, init, cond, incr, body = node
            if init is not None:
                self._exec(init, env, consts)
            result = _VOID
            while True:
                self._burn(2)
                if cond is not None and not self._truthy(self._eval(cond, env)):
                    break
                for stmt in body:
                    self._burn(1)
                    value = self._exec(stmt, env, consts)
                    if value is not _VOID:
                        result = value
                if incr is not None:
                    self._exec(incr, env, consts)
            return result
        if kind == "function":
            _, name, params, body = node
            closure: dict[str, Any] = dict(env)
            fn = ("__fn__", params, body, closure)
            closure[name] = fn
            env[name] = fn
            return _VOID
        if kind == "return":
            raise _JSReturn(self._eval(node[1], env) if node[1] is not None else None)
        raise SyntaxError("unknown statement: " + kind)

    def _eval(self, node, env):
        self._burn(1)
        kind = node[0]
        if kind == "lit":
            return node[1]
        if kind == "name":
            if node[1] not in env:
                raise NameError("undefined variable: " + node[1])
            return env[node[1]]
        if kind == "array":
            items = [self._eval(item, env) for item in node[1]]
            self._account(items)
            return items
        if kind == "object":
            obj = {key: self._eval(val, env) for key, val in node[1]}
            self._account(obj)
            return obj
        if kind == "index":
            base = self._eval(node[1], env)
            key = self._eval(node[2], env)
            if isinstance(base, list) and isinstance(key, (int, float)):
                return base[int(key)]
            if isinstance(base, dict):
                return base.get(str(key))
            if isinstance(base, str) and isinstance(key, (int, float)):
                return base[int(key)]
            raise TypeError("unindexable value")
        if kind == "unary":
            _, op, operand = node
            value = self._eval(operand, env)
            if op == "-":
                return -value
            if op == "!":
                return not self._truthy(value)
            raise SyntaxError("unknown unary: " + op)
        if kind == "binary":
            _, op, left, right = node
            if op == "&&":
                return self._eval(right, env) if self._truthy(self._eval(left, env)) else False
            if op == "||":
                return self._eval(left, env) if self._truthy(self._eval(left, env)) else self._eval(right, env)
            lhs = self._eval(left, env)
            rhs = self._eval(right, env)
            return self._apply(op, lhs, rhs)
        if kind == "ternary":
            _, cond, then, otherwise = node
            return self._eval(then, env) if self._truthy(self._eval(cond, env)) else self._eval(otherwise, env)
        if kind == "call":
            _, callee, args = node
            values = [self._eval(arg, env) for arg in args]
            if callee == "call_tool":
                return self._host_call(values)
            target = env.get(callee)
            if not (isinstance(target, tuple) and target and target[0] == "__fn__"):
                raise TypeError("uncallable: " + callee)
            _, params, body, closure = target
            if len(values) != len(params):
                raise TypeError("arity mismatch: " + callee)
            if self.depth >= 32:
                raise CodeModeBudgetExceeded("call depth exceeded")
            frame = dict(closure)
            frame.update(zip(params, values))
            self.depth += 1
            try:
                for stmt in body:
                    self._burn(1)
                    self._exec(stmt, frame, set())
            except _JSReturn as done:
                return done.value
            finally:
                self.depth -= 1
            return None
        raise SyntaxError("unknown expression: " + kind)

    def _apply(self, op, lhs, rhs):
        if op == "+":
            return self._add(lhs, rhs)
        if op == "-":
            return lhs - rhs
        if op == "*":
            return lhs * rhs
        if op == "/":
            return lhs / rhs if rhs else self._div0()
        if op == "%":
            return lhs % rhs if rhs else self._div0()
        if op == "**":
            if isinstance(lhs, (int, float)) and isinstance(rhs, (int, float)) and abs(rhs) <= 64:
                return lhs ** rhs
            raise CodeModeBudgetExceeded("exponent outside bound")
        if op in ("==", "==="):
            return lhs == rhs
        if op in ("!=", "!=="):
            return lhs != rhs
        if op == "<":
            return lhs < rhs
        if op == "<=":
            return lhs <= rhs
        if op == ">":
            return lhs > rhs
        if op == ">=":
            return lhs >= rhs
        raise SyntaxError("unknown operator: " + op)

    @staticmethod
    def _add(lhs, rhs):
        if isinstance(lhs, str) or isinstance(rhs, str):
            result = str(lhs) + str(rhs)
            if len(result.encode("utf-8")) > 64 * 1024:
                raise CodeModeBudgetExceeded("string concatenation outside bound")
            return result
        return lhs + rhs

    @staticmethod
    def _div0():
        raise CodeModeBudgetExceeded("division by zero")

    @staticmethod
    def _truthy(value) -> bool:
        if value in (None, False, 0, "", [], {}):
            return False
        return True

    def _host_call(self, values):
        if self.call_tool_bridge is None:
            raise PermissionError("tool calls require a host bridge")
        if len(values) != 2 or not isinstance(values[0], str):
            raise TypeError('call_tool(name, args) requires a string name and object args')
        name, args = values
        raw = json.dumps(args, ensure_ascii=False, allow_nan=False,
                         separators=(",", ":")).encode("utf-8")
        if len(raw) > self.max_arg_bytes:
            raise CodeModeBudgetExceeded("tool arguments exceed max_arg_bytes")
        if self.tool_calls >= self.max_tool_calls:
            raise CodeModeBudgetExceeded("max_tool_calls exceeded")
        self.tool_calls += 1
        self._burn(50)
        result = self.call_tool_bridge(name, args)
        self._account(result)
        return result


class _Void:
    pass


_VOID = _Void()


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def program(self):
        stmts = []
        while self.pos < len(self.tokens):
            stmts.append(self.statement())
            self._eat(";")
        return stmts

    def statement(self):
        if self._peek_name() in ("var", "let", "const"):
            decl = self._next()[1]
            name = self._expect_name("declaration name")
            init = None
            if self._eat("="):
                init = self.expression()
            return ("declare", decl, name, init)
        if self._peek_name() == "if":
            self._next()
            self._expect("(")
            cond = self.expression()
            self._expect(")")
            then = self._block_or_single()
            otherwise = None
            if self._peek_name() == "else":
                self._next()
                otherwise = self._block_or_single()
            return ("if", cond, then, otherwise)
        if self._peek_name() == "while":
            self._next()
            self._expect("(")
            cond = self.expression()
            self._expect(")")
            return ("while", cond, self._block_or_single())
        if self._peek_name() == "for":
            self._next()
            self._expect("(")
            init = None
            if not self._check(";"):
                init = self._for_init()
            self._expect(";")
            cond = None
            if not self._check(";"):
                cond = self.expression()
            self._expect(";")
            incr = None
            if not self._check(")"):
                incr = self._for_incr()
            self._expect(")")
            return ("for", init, cond, incr, self._block_or_single())
        if self._peek_name() == "function":
            self._next()
            name = self._expect_name("function name")
            self._expect("(")
            params = []
            while not self._check(")"):
                params.append(self._expect_name("parameter"))
                if not self._eat(","):
                    break
            self._expect(")")
            return ("function", name, params, self._block())
        if self._peek_name() == "return":
            self._next()
            if self._check(";") or self._check("}") or self.pos >= len(self.tokens):
                return ("return", None)
            return ("return", self.expression())
        # assignment vs expression statement
        if (self._peek_kind() == "name" and self.pos + 1 < len(self.tokens)
                and self.tokens[self.pos + 1][1] in ("=", "+=", "-=", "*=", "/=", "%=")):
            name = self._next()[1]
            op = self._next()[1]
            return ("assign", name, op, self.expression())
        return ("expr", self.expression())

    def _for_init(self):
        if self._peek_name() in ("var", "let", "const"):
            decl = self._next()[1]
            name = self._expect_name("declaration name")
            init = None
            if self._eat("="):
                init = self.expression()
            return ("declare", decl, name, init)
        if (self._peek_kind() == "name" and self.pos + 1 < len(self.tokens)
                and self.tokens[self.pos + 1][1] in ("=", "+=", "-=", "*=", "/=", "%=")):
            name = self._next()[1]
            op = self._next()[1]
            return ("assign", name, op, self.expression())
        return ("expr", self.expression())

    def _for_incr(self):
        if (self._peek_kind() == "name" and self.pos + 1 < len(self.tokens)
                and self.tokens[self.pos + 1][1] in ("=", "+=", "-=", "*=", "/=", "%=")):
            name = self._next()[1]
            op = self._next()[1]
            return ("assign", name, op, self.expression())
        return ("expr", self.expression())

    def _block_or_single(self):
        if self._check("{"):
            return self._block()
        return [self.statement()]

    def _block(self):
        self._expect("{")
        stmts = []
        while not self._check("}"):
            stmts.append(self.statement())
            self._eat(";")
        self._expect("}")
        return stmts

    # -- expressions (precedence climb) ----------------------------------
    def expression(self):
        return self._ternary()

    def _ternary(self):
        node = self._or()
        if self._eat("?"):
            then = self.expression()
            self._expect(":")
            return ("ternary", node, then, self.expression())
        return node

    def _or(self):
        node = self._and()
        while self._eat("||"):
            node = ("binary", "||", node, self._and())
        return node

    def _and(self):
        node = self._equality()
        while self._eat("&&"):
            node = ("binary", "&&", node, self._equality())
        return node

    def _equality(self):
        node = self._relational()
        while self._peek() in ("==", "===", "!=", "!=="):
            node = ("binary", self._next()[1], node, self._relational())
        return node

    def _relational(self):
        node = self._additive()
        while self._peek() in ("<", "<=", ">", ">="):
            node = ("binary", self._next()[1], node, self._additive())
        return node

    def _additive(self):
        node = self._multiplicative()
        while self._peek() in ("+", "-"):
            node = ("binary", self._next()[1], node, self._multiplicative())
        return node

    def _multiplicative(self):
        node = self._power()
        while self._peek() in ("*", "/", "%"):
            node = ("binary", self._next()[1], node, self._power())
        return node

    def _power(self):
        node = self._unary()
        if self._eat("**"):
            node = ("binary", "**", node, self._unary())
        return node

    def _unary(self):
        if self._peek() in ("-", "!"):
            return ("unary", self._next()[1], self._unary())
        return self._postfix()

    def _postfix(self):
        node = self._primary()
        while self._eat("["):
            node = ("index", node, self.expression())
            self._expect("]")
        while self._eat("."):
            node = ("index", node, ("lit", self._expect_name("property")))
        return node

    def _primary(self):
        kind, text = self._next()
        if kind == "num":
            return ("lit", float(text) if "." in text else int(text))
        if kind == "str":
            quote = text[0]
            body = text[1:-1]
            body = body.replace("\\n", "\n").replace("\\t", "\t")
            body = body.replace("\\" + quote, quote).replace("\\\\", "\\")
            return ("lit", body)
        if kind == "name":
            if text == "true":
                return ("lit", True)
            if text == "false":
                return ("lit", False)
            if text == "null":
                return ("lit", None)
            if text in ("eval", "Function", "require", "import"):
                raise SyntaxError("host import refused: " + text)
            if self._check("("):
                self._next()
                args = []
                while not self._check(")"):
                    args.append(self.expression())
                    if not self._eat(","):
                        break
                self._expect(")")
                return ("call", text, args)
            return ("name", text)
        if text == "(":
            node = self.expression()
            self._expect(")")
            return node
        if text == "[":
            items = []
            while not self._check("]"):
                items.append(self.expression())
                if not self._eat(","):
                    break
            self._expect("]")
            return ("array", items)
        if text == "{":
            pairs = []
            while not self._check("}"):
                key_tok = self._next()
                key = key_tok[1]
                if key_tok[0] == "str":
                    key = self._primary_str(key)
                elif key_tok[0] != "name":
                    raise SyntaxError("invalid object key")
                self._expect(":")
                pairs.append((key, self.expression()))
                if not self._eat(","):
                    break
            self._expect("}")
            return ("object", pairs)
        raise SyntaxError("unexpected token: " + text)

    @staticmethod
    def _primary_str(text):
        quote = text[0]
        return text[1:-1].replace("\\" + quote, quote).replace("\\\\", "\\")

    # -- cursor helpers --------------------------------------------------
    def _peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos][1]
        return ""

    def _peek_kind(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos][0]
        return ""

    def _peek_name(self):
        if self.pos < len(self.tokens) and self.tokens[self.pos][0] == "name":
            return self.tokens[self.pos][1]
        return ""

    def _next(self):
        if self.pos >= len(self.tokens):
            raise SyntaxError("unexpected end of source")
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _check(self, text):
        return self._peek() == text

    def _eat(self, text):
        if self._check(text):
            self.pos += 1
            return True
        return False

    def _expect(self, text):
        if not self._eat(text):
            raise SyntaxError("expected: " + text)

    def _expect_name(self, label):
        kind, text = self._next()
        if kind != "name" or text in _KEYWORDS and label not in ("parameter",):
            if text in ("eval", "Function", "require", "import"):
                raise SyntaxError("host import refused: " + text)
            if kind != "name":
                raise SyntaxError("expected " + label)
        return text
