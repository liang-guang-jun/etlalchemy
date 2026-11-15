"""Ports the comment application uses to reach other bounded contexts."""

from etlalchemy.comment.ports.authorization import CommentAuthorizationPort, SessionUser
from etlalchemy.comment.ports.target_lookup import TargetLookupPort

__all__ = ["CommentAuthorizationPort", "SessionUser", "TargetLookupPort"]
