"""
IDA 和 Binary Ninja 共享的提示词生成动作处理器。

每个处理器接收一个上下文字典，包含：ea、func_ea、func_name、selected_text。
返回要放入输入区域的提示文本。

宿主动作（IDA 的微码优化器、BN 的 smart-patch）位于
各自的 ``<host>/ui/actions.py`` 模块中。
"""

from __future__ import annotations

from typing import Any


def _func_label(ctx: dict[str, Any]) -> tuple[str, int]:
    """从上下文中返回 (显示名称, 有效地址)。"""
    name = ctx["func_name"] or f"sub_{ctx['ea']:x}"
    ea = ctx["func_ea"] or ctx["ea"]
    return name, ea


def handle_send_to(ctx: dict[str, Any]) -> str:
    sel = ctx["selected_text"]
    if sel:
        return sel
    name = ctx["func_name"]
    ea = ctx["ea"]
    if name:
        return f"分析位于 0x{ea:x} 的函数 {name}"
    return f"分析位于 0x{ea:x} 的代码"


def handle_explain(ctx: dict[str, Any]) -> str:
    name, ea = _func_label(ctx)
    return f"解释位于 0x{ea:x} 的函数 {name}。对其进行反编译并提供详细分析。"


def handle_rename(ctx: dict[str, Any]) -> str:
    name, ea = _func_label(ctx)
    return (
        f"分析位于 0x{ea:x} 的函数 {name}。"
        "根据其行为，为该函数及其局部变量建议更好的名称，"
        "并应用重命名。"
    )


def handle_deobfuscate(ctx: dict[str, Any], *, optimizer_term: str = "IL") -> str:
    name, ea = _func_label(ctx)
    return (
        f"对位于 0x{ea:x} 的函数 {name} 进行反混淆处理。"
        "识别混淆模式（不透明谓词、垃圾代码、"
        "控制流平坦化、加密字符串）并解释它们。"
        f"如有可能，应用 {optimizer_term} 优化以清理输出。"
    )


def handle_vuln_audit(ctx: dict[str, Any]) -> str:
    name, ea = _func_label(ctx)
    return (
        f"请对位于 0x{ea:x} 的函数 {name} 进行安全漏洞审计。 "
        "重点检查以下风险：缓冲区溢出、格式化字符串漏洞、整数溢出、 "
        "Use-After-Free、命令注入、权限漏洞以及其他安全问题。 "
        "请列出发现的每个漏洞，并说明其严重程度及具体的代码证据。"
    )


def handle_suggest_types(ctx: dict[str, Any]) -> str:
    name, ea = _func_label(ctx)
    return (
        f"分析位于 0x{ea:x} 的函数 {name} 并推断类型。"
        "检查指针解引用模式以建议结构体，"
        "识别枚举类常量，并提出合适的参数类型。"
        "应用这些类型修改。"
    )


def handle_annotate(ctx: dict[str, Any]) -> str:
    name, ea = _func_label(ctx)
    return (
        f"为位于 0x{ea:x} 的函数 {name} 添加注释。"
        "添加函数级注释总结其用途，"
        "并在关键基本块中添加内联注释解释其逻辑。"
    )


def handle_clean(ctx: dict[str, Any], *, ir_term: str = "IL") -> str:
    name, ea = _func_label(ctx)
    return (
        f"清理位于 0x{ea:x} 的函数 {name} 的 {ir_term}。"
        f"读取 {ir_term}，识别垃圾或混淆指令，"
        "必要时用 NOP 填充或修补，然后重新反编译验证。"
    )


def handle_xref_analysis(ctx: dict[str, Any]) -> str:
    name, ea = _func_label(ctx)
    return (
        f"对位于 0x{ea:x} 的函数 {name} 执行深度交叉引用分析。"
        "追踪所有调用者与被调用者，识别数据引用，"
        "并绘制该函数周围的调用关系图。"
    )
