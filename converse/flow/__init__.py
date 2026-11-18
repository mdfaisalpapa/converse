"""Flow processing and rule-based execution engine package.

Strict Architectural Rule:
Do not import `frappe` here.
"""

from converse.flow.base import BaseFlowNode, NodeExecutionContext, NodeResult
from converse.flow.engine import FlowExecutionResult, FlowExecutor
from converse.flow.evaluator import SafeConditionEvaluator, interpolate_template
from converse.flow.registry import NodeRegistry, register_node
from converse.flow.schema import (
    ExecutionStatus,
    FlowDefinition,
    FlowNodeType,
    NodeDefinition,
    TransitionDefinition,
    VariableDefinition,
)

__all__ = [
    "BaseFlowNode",
    "NodeExecutionContext",
    "NodeResult",
    "FlowExecutor",
    "FlowExecutionResult",
    "SafeConditionEvaluator",
    "interpolate_template",
    "NodeRegistry",
    "register_node",
    "FlowDefinition",
    "NodeDefinition",
    "TransitionDefinition",
    "VariableDefinition",
    "ExecutionStatus",
    "FlowNodeType",
]
