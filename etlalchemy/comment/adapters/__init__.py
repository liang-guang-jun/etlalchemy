"""Adapters of the comment bounded context."""

from etlalchemy.comment.adapters.iam import IamCommentAuthorizationAdapter
from etlalchemy.comment.adapters.target_lookup import CompositeTargetLookup

__all__ = ["CompositeTargetLookup", "IamCommentAuthorizationAdapter"]
