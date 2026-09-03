"""Durable generation batch ORM export.

The model currently lives beside the task queue records because both tables
share one execution-control schema.  Importing it through this module keeps
batch repositories independent from the task model's module layout.
"""

from lib.db.models.task import GenerationBatchRecord

__all__ = ["GenerationBatchRecord"]
