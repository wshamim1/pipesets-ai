"""Statistics — built-in tool `statistics_tool`."""

from typing import Any, Dict, Optional

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="statistics_tool",
    name="Statistics",
    icon="📈",
    category="Code & Compute",
    description="Count, mean, median, mode, min/max, standard deviation and quartiles of a list of numbers.",
    default_config={},
    order=70,
    parameters=params({"numbers": {"type": "array", "items": {"type": "number"}, "description": "The numbers"}}),
    to_input=lambda a: ", ".join(str(n) for n in a["numbers"]),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import re
    import statistics as st
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", inp.replace(",", " "))]
    if len(nums) < 1:
        return "[Statistics] Provide a list of numbers, e.g. '3, 7, 7, 19, 24'."
    s_nums = sorted(nums)
    q = st.quantiles(s_nums, n=4) if len(nums) >= 2 else [nums[0]] * 3
    out = {
        "count": len(nums), "sum": sum(nums), "mean": st.fmean(nums), "median": st.median(nums),
        "mode": st.multimode(nums)[0] if len(set(nums)) < len(nums) else None,
        "min": s_nums[0], "max": s_nums[-1], "range": s_nums[-1] - s_nums[0],
        "stdev": st.stdev(nums) if len(nums) > 1 else 0.0, "variance": st.variance(nums) if len(nums) > 1 else 0.0,
        "q1": q[0], "q3": q[2],
    }
    return "[Statistics]\n" + "\n".join(f"  {k:9}: {round(v, 6) if isinstance(v, float) else v}" for k, v in out.items())
