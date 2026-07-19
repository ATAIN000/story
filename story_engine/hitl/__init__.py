"""HITL 子包（Module 7.1/7.2）— 作者介入路由 + 训练数据管道

P5.7：InterventionRouter 前 3 类（intent / character / evaluation）；
P5.8：structural / textual；P5.9：TrainingPipeline（Module 7.2 简化版）。
"""
from .intervention import HumanInput, InterventionResult, InterventionRouter
from .training_pipeline import TrainingPipeline

__all__ = [
    "HumanInput", "InterventionResult", "InterventionRouter",
    "TrainingPipeline",
]
