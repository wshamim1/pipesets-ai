"""Calculator — built-in tool `calculator`."""

from typing import Any, Dict, Optional

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="calculator",
    name="Calculator",
    icon="🧮",
    category="Code & Compute",
    description="Evaluates safe math expressions: arithmetic, sqrt, sin, log, etc.",
    default_config={},
    order=20,
    parameters=params({"expression": {"type": "string", "description": "Arithmetic expression, e.g. (12.5 * 4) / 3 ** 2"}}),
    input_param="expression",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import ast, math, operator as op
    # Safe expression evaluator — no exec, no builtins
    _OPS = {
        ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul,
        ast.Div: op.truediv, ast.Pow: op.pow, ast.USub: op.neg,
        ast.Mod: op.mod, ast.FloorDiv: op.floordiv,
    }
    _SAFE_FUNCS = {
        "sqrt": math.sqrt, "abs": abs, "round": round,
        "log": math.log, "log10": math.log10, "log2": math.log2,
        "sin": math.sin, "cos": math.cos, "tan": math.tan,
        "pi": math.pi, "e": math.e, "ceil": math.ceil, "floor": math.floor,
    }
    def _eval(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.BinOp):
            return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            return _OPS[type(node.op)](_eval(node.operand))
        if isinstance(node, ast.Call):
            fn_name = node.func.id if isinstance(node.func, ast.Name) else ""
            fn = _SAFE_FUNCS.get(fn_name)
            if fn is None:
                raise ValueError(f"Function '{fn_name}' is not allowed")
            return fn(*[_eval(a) for a in node.args])
        if isinstance(node, ast.Name):
            if node.id in _SAFE_FUNCS:
                return _SAFE_FUNCS[node.id]
            raise ValueError(f"Name '{node.id}' is not allowed")
        raise ValueError(f"Unsupported expression type: {type(node)}")
    try:
        tree = ast.parse(inp.strip(), mode="eval")
        result = _eval(tree.body)
        return f"{inp.strip()} = {result}"
    except Exception as e:
        return f"[Calculator] Error: {e}"
