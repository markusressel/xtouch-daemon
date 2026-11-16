"""
The conditions of candidates and composed states: state names, `present`, `present(<id>)`, `and`, `or`, `not` and
parentheses.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

RESERVED = frozenset({"and", "or", "not", "if", "present", "none", "mode"})
"""Words that can't be ids: the keywords, and what would collide with entity IDs in Home Assistant."""

_TOKEN = re.compile(r"\s*(?:(?P<name>[a-z0-9_]+)|(?P<symbol>[()]))")


class ExpressionError(ValueError):
    """A condition that can't be read: what is wrong, and where (the index in the text)."""

    def __init__(self, text: str, position: int, message: str):
        super().__init__(f'"{text}": {message}')
        self.text = text
        self.position = position
        self.message = message

    def caret(self) -> str:
        """The text with a caret under the place, for the command line."""
        return f"{self.text}\n{' ' * self.position}^ {self.message}"


@dataclass(frozen=True)
class Name:
    """A state or mode: true while it is on."""

    name: str
    position: int


@dataclass(frozen=True)
class Present:
    """True while a channel or pool is present: `target`, or with None the one of the candidate."""

    target: str | None
    position: int


@dataclass(frozen=True)
class Not:
    operand: Expr


@dataclass(frozen=True)
class And:
    operands: tuple[Expr, ...]


@dataclass(frozen=True)
class Or:
    operands: tuple[Expr, ...]


type Expr = Name | Present | Not | And | Or


@dataclass(frozen=True)
class Condition:
    """A parsed condition, with its text."""

    text: str
    expr: Expr

    def holds(self, states: Mapping[str, bool], present: Callable[[str | None], bool]) -> bool:
        """
        Whether it is true. `states` has a value for every state and mode it names; `present` tells whether a channel
        or pool is present (None: the candidate's own).
        """
        return _evaluate(self.expr, states, present)

    @property
    def states(self) -> frozenset[str]:
        """The states and modes it names."""
        return frozenset(node.name for node in _nodes(self.expr) if isinstance(node, Name))

    @property
    def presence(self) -> frozenset[str | None]:
        """The channels and pools whose presence it asks about (None: the candidate's own)."""
        return frozenset(node.target for node in _nodes(self.expr) if isinstance(node, Present))

    def explain(self, states: Mapping[str, bool], present: Callable[[str | None], bool]) -> str:
        """What it asks about and their values now, e.g. "gaming is off, present: no"."""
        parts = [f"{name} is {'on' if states[name] else 'off'}" for name in sorted(self.states)]
        parts += [
            f"{'present' if target is None else f'present({target})'}: {'yes' if present(target) else 'no'}"
            for target in sorted(self.presence, key=lambda target: target or "")
        ]
        return ", ".join(parts)


def parse(text: str) -> Condition:
    """The condition of the text; ExpressionError says what is wrong where."""
    return Condition(text, _Parser(text).parse())


def _evaluate(expr: Expr, states: Mapping[str, bool], present: Callable[[str | None], bool]) -> bool:
    match expr:
        case Name(name=name):
            return states[name]
        case Present(target=target):
            return present(target)
        case Not(operand=operand):
            return not _evaluate(operand, states, present)
        case And(operands=operands):
            return all(_evaluate(operand, states, present) for operand in operands)
        case _:
            return any(_evaluate(operand, states, present) for operand in expr.operands)


def _nodes(expr: Expr) -> list[Expr]:
    match expr:
        case Not(operand=operand):
            return [expr, *_nodes(operand)]
        case And(operands=operands) | Or(operands=operands):
            return [expr, *(node for operand in operands for node in _nodes(operand))]
        case _:
            return [expr]


class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.tokens: list[tuple[str, int]] = []
        position = 0
        while position < len(text):
            match = _TOKEN.match(text, position)
            if match is None or match.end() == position:
                if text[position:].strip() == "":
                    break
                offset = position + len(text[position:]) - len(text[position:].lstrip())
                raise ExpressionError(text, offset, f"unexpected {text[offset]!r}")
            token = match.group("name") or match.group("symbol")
            self.tokens.append((token, match.start("name") if match.group("name") else match.start("symbol")))
            position = match.end()
        self.index = 0

    def parse(self) -> Expr:
        if not self.tokens:
            raise ExpressionError(self.text, 0, "empty condition")
        expr = self._or()
        if self.index < len(self.tokens):
            token, position = self.tokens[self.index]
            raise ExpressionError(self.text, position, f"unexpected {token!r}")
        return expr

    def _peek(self) -> str | None:
        return self.tokens[self.index][0] if self.index < len(self.tokens) else None

    def _take(self) -> tuple[str, int]:
        if self.index >= len(self.tokens):
            raise ExpressionError(self.text, len(self.text), "the condition ends too early")
        token = self.tokens[self.index]
        self.index += 1
        return token

    def _or(self) -> Expr:
        operands = [self._and()]
        while self._peek() == "or":
            self._take()
            operands.append(self._and())
        return operands[0] if len(operands) == 1 else Or(tuple(operands))

    def _and(self) -> Expr:
        operands = [self._not()]
        while self._peek() == "and":
            self._take()
            operands.append(self._not())
        return operands[0] if len(operands) == 1 else And(tuple(operands))

    def _not(self) -> Expr:
        if self._peek() == "not":
            self._take()
            return Not(self._not())
        return self._atom()

    def _atom(self) -> Expr:
        token, position = self._take()
        if token == "(":
            expr = self._or()
            self._expect(")")
            return expr
        if token == "present":
            if self._peek() != "(":
                return Present(None, position)
            self._take()
            target, target_position = self._take()
            if target in RESERVED or target in "()":
                raise ExpressionError(self.text, target_position, "present(...) takes a channel or pool")
            self._expect(")")
            return Present(target, position)
        if token in RESERVED or token == ")":
            raise ExpressionError(self.text, position, f"unexpected {token!r}")
        return Name(token, position)

    def _expect(self, symbol: str) -> None:
        token, position = self._take()
        if token != symbol:
            raise ExpressionError(self.text, position, f"expected {symbol!r}, not {token!r}")
