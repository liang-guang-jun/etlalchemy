export {
  addComment,
  createThread,
  discardComment,
  discardThread,
  editComment,
  fetchTarget,
  fetchTargets,
  fetchThread,
  fetchThreads,
  reopenThread,
  resolveThread,
  type TargetReference,
  type ThreadQuery,
} from './api/fetchers';
export { commentKeys } from './api/keys';
export {
  useOpenThreadCount,
  useTarget,
  useTargets,
  useThread,
  useThreadDetails,
  useThreads,
} from './api/queries';
export {
  commentCreateSchema,
  commentCreatedSchema,
  commentEditSchema,
  commentSchema,
  threadCreateSchema,
  threadCreatedSchema,
  threadDetailSchema,
  threadSchema,
  type Comment,
  type CommentCreate,
  type CommentCreated,
  type CommentEdit,
  type Thread,
  type ThreadCreate,
  type ThreadCreated,
  type ThreadDetail,
} from './api/schema';
export {
  describedTarget,
  TARGET_NOUNS,
  targetHref,
  targetTitle,
  type CommentTarget,
  type CommentTargetType,
  type TargetDescription,
} from './model/target';
export { buildCommentTree, indentFor, MAX_INDENT_DEPTH, type CommentNode } from './model/tree';
