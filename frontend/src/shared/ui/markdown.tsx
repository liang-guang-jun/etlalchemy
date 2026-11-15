import { useMemo, type ComponentPropsWithoutRef, type ReactNode } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import { Link } from 'react-router';
import remarkGfm from 'remark-gfm';

import { cn } from '@/shared/lib/cn';
import { remarkUrnLinks } from '@/shared/lib/remark-urn-links';

/** Props react-markdown hands to the `a` component. */
type AnchorProps = ComponentPropsWithoutRef<'a'>;

/** Styling shared by the in-app and the external link. */
const LINK_CLASS = 'text-brand-ink underline underline-offset-2 hover:opacity-80';

/**
 * Builds the anchor renderer.
 *
 * A URN link carries its URN in the title, so a caller that knows the name of
 * the object replaces the short id the plugin wrote; anything else keeps the
 * text the markdown gave.
 *
 * @param names Object names keyed by the URN of the link.
 * @returns The renderer of the `a` component.
 */
function anchor(names?: ReadonlyMap<string, string>) {
  return function Anchor({ href, children, title }: AnchorProps): ReactNode {
    const text = (title === undefined ? undefined : names?.get(title)) ?? children;
    // A URN resolves to an in-app path; a plain link keeps the external handling.
    if (href !== undefined && href.startsWith('/')) {
      return (
        <Link to={href} title={title ?? undefined} className={LINK_CLASS}>
          {text}
        </Link>
      );
    }
    return (
      <a href={href} className={LINK_CLASS} target="_blank" rel="noreferrer">
        {text}
      </a>
    );
  };
}

const COMPONENTS: Components = {
  p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
  h1: ({ children }) => <h3 className="mt-6 mb-3 text-lg font-bold first:mt-0">{children}</h3>,
  h2: ({ children }) => (
    <h4 className="mt-5 mb-2 text-base font-semibold first:mt-0">{children}</h4>
  ),
  h3: ({ children }) => (
    <h5 className="mt-4 mb-1.5 text-sm font-semibold first:mt-0">{children}</h5>
  ),
  h4: ({ children }) => (
    <h6 className="mt-4 mb-1.5 text-xs font-semibold tracking-wide uppercase first:mt-0">
      {children}
    </h6>
  ),
  ul: ({ children }) => <ul className="mb-3 list-disc space-y-1 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="mb-3 list-decimal space-y-1 pl-5">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed marker:text-text-disabled">{children}</li>,
  a: anchor(),
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  del: ({ children }) => <del className="text-text-secondary line-through">{children}</del>,
  code: ({ children }) => (
    <code className="rounded-sm bg-bg-canvas px-1 py-0.5 font-mono text-[0.85em] text-text-primary">
      {children}
    </code>
  ),
  pre: ({ children }) => (
    <pre className="mb-3 overflow-x-auto rounded-md border border-border-base bg-bg-canvas p-3 font-mono text-xs">
      {children}
    </pre>
  ),
  blockquote: ({ children }) => (
    <blockquote className="mb-3 border-l-2 border-brand pl-4 text-text-secondary italic [&>p:last-child]:mb-0">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-4 border-border-base" />,
  table: ({ children }) => (
    <div className="mb-3 overflow-x-auto">
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border-b border-border-base px-2 py-1 text-left font-semibold">{children}</th>
  ),
  td: ({ children }) => (
    <td className="border-b border-border-base px-2 py-1 align-top">{children}</td>
  ),
  img: ({ src, alt }) => <img src={src} alt={alt ?? ''} className="max-w-full rounded-md" />,
  input: ({ checked }) => (
    <input type="checkbox" checked={checked ?? false} readOnly className="mr-1 align-middle" />
  ),
};

export interface MarkdownProps {
  /** Markdown source. */
  children: string;
  className?: string;
  /** Object names to render as the text of a URN link, keyed by the URN. */
  urnLabels?: ReadonlyMap<string, string>;
}

/**
 * Renders GitHub-flavoured markdown with the workspace typography.
 *
 * @param props Component props.
 * @returns The rendered document.
 */
export function Markdown({ children, className, urnLabels }: MarkdownProps): ReactNode {
  const components = useMemo<Components>(
    () => (urnLabels === undefined ? COMPONENTS : { ...COMPONENTS, a: anchor(urnLabels) }),
    [urnLabels],
  );

  return (
    <div
      className={cn(
        'text-sm leading-relaxed text-text-primary [&_pre_code]:bg-transparent [&_pre_code]:p-0',
        className,
      )}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkUrnLinks]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
