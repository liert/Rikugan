"""Mutation tracking for reversible tool calls."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..core.logging import log_debug


@dataclass
class MutationRecord:
    """Records a single mutation for undo capability."""

    tool_name: str
    arguments: Dict[str, Any]
    reverse_tool: str
    reverse_arguments: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    description: str = ""
    reversible: bool = True


def build_reverse_record(
    tool_name: str,
    arguments: Dict[str, Any],
    pre_state: Optional[Dict[str, Any]] = None,
) -> Optional[MutationRecord]:
    """Build a MutationRecord with reverse operation for a mutating tool call.

    Returns None if the tool is not reversible.
    """
    args = arguments
    pre = pre_state or {}

    if tool_name == "rename_function":
        old_name = args.get("old_name", "")
        new_name = args.get("new_name", "")
        return MutationRecord(
            tool_name=tool_name,
            arguments=args,
            reverse_tool="rename_function",
            reverse_arguments={"old_name": new_name, "new_name": old_name},
            description=f"Rename function {old_name} → {new_name}",
        )

    if tool_name in ("rename_variable", "rename_single_variable"):
        func = args.get("function_name", "")
        old_var = args.get("variable_name", "")
        new_var = args.get("new_name", "")
        return MutationRecord(
            tool_name=tool_name,
            arguments=args,
            reverse_tool=tool_name,
            reverse_arguments={
                "function_name": func,
                "variable_name": new_var,
                "new_name": old_var,
            },
            description=f"Rename variable {old_var} → {new_var} in {func}",
        )

    if tool_name == "set_comment":
        address = args.get("address", "")
        old_comment = pre.get("old_comment", "")
        if old_comment:
            return MutationRecord(
                tool_name=tool_name,
                arguments=args,
                reverse_tool="set_comment",
                reverse_arguments={"address": address, "comment": old_comment},
                description=f"Set comment at {address}",
            )
        else:
            return MutationRecord(
                tool_name=tool_name,
                arguments=args,
                reverse_tool="delete_comment",
                reverse_arguments={"address": address},
                description=f"Set comment at {address}",
            )

    if tool_name == "set_function_comment":
        func = args.get("function_name", "")
        old_comment = pre.get("old_comment", "")
        if old_comment:
            return MutationRecord(
                tool_name=tool_name,
                arguments=args,
                reverse_tool="set_function_comment",
                reverse_arguments={"function_name": func, "comment": old_comment},
                description=f"Set function comment on {func}",
            )
        else:
            return MutationRecord(
                tool_name=tool_name,
                arguments=args,
                reverse_tool="delete_function_comment",
                reverse_arguments={"function_name": func},
                description=f"Set function comment on {func}",
            )

    if tool_name == "rename_data":
        address = args.get("address", "")
        old_name = pre.get("old_name", "")
        new_name = args.get("new_name", "")
        if old_name:
            return MutationRecord(
                tool_name=tool_name,
                arguments=args,
                reverse_tool="rename_data",
                reverse_arguments={"address": address, "new_name": old_name},
                description=f"Rename data at {address} → {new_name}",
            )
        return MutationRecord(
            tool_name=tool_name,
            arguments=args,
            reverse_tool=tool_name,
            reverse_arguments=args,
            description=f"Rename data at {address} → {new_name}",
            reversible=False,
        )

    if tool_name == "set_function_prototype":
        target = args.get("name_or_address", "")
        old_proto = pre.get("old_prototype", "")
        if old_proto:
            return MutationRecord(
                tool_name=tool_name,
                arguments=args,
                reverse_tool="set_function_prototype",
                reverse_arguments={"name_or_address": target, "prototype": old_proto},
                description=f"Set prototype for {target}",
            )

    if tool_name == "retype_variable":
        func = args.get("function_name", "")
        var = args.get("variable_name", "")
        old_type = pre.get("old_type", "")
        if old_type:
            return MutationRecord(
                tool_name=tool_name,
                arguments=args,
                reverse_tool="retype_variable",
                reverse_arguments={
                    "function_name": func,
                    "variable_name": var,
                    "type_str": old_type,
                },
                description=f"Retype {var} in {func}",
            )

    # For tools we don't know how to reverse (execute_python, etc.)
    return MutationRecord(
        tool_name=tool_name,
        arguments=args,
        reverse_tool="",
        reverse_arguments={},
        description=f"Call {tool_name}",
        reversible=False,
    )


def capture_pre_state(
    tool_name: str,
    arguments: Dict[str, Any],
    tool_executor,
) -> Dict[str, Any]:
    """Capture pre-mutation state needed for undo.

    Calls getter tools where needed to record the current state
    before a mutation is applied.
    """
    pre: Dict[str, Any] = {}

    try:
        if tool_name == "set_comment":
            address = arguments.get("address", "")
            if address:
                pre["old_comment"] = tool_executor("get_comment", {"address": address})
        elif tool_name == "set_function_comment":
            func = arguments.get("function_name", "")
            if func:
                pre["old_comment"] = tool_executor("get_function_comment", {"function_name": func})
    except Exception as e:
        log_debug(f"capture_pre_state failed for {tool_name}: {e}")

    return pre
