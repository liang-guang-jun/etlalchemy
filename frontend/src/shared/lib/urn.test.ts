import { describe, expect, it } from 'vitest';

import { remarkUrnLinks } from './remark-urn-links';
import { parseUrn, urnsIn } from './urn';

const CATALOG = '3b4213fe-22f9-40b3-a0b3-243d6fd6be31';
const SCHEMA = '524cea4f-2a21-4230-9728-0a427c97c1ac';
const TABLE = '96420819-4423-4a71-abb2-cc1432e02b6a';

/** Shape of the mdast nodes the plugin builds. */
interface Node {
  type: string;
  value?: string;
  url?: string;
  children?: Node[];
}

describe('parseUrn', () => {
  it('links a catalog, a schema and a table', () => {
    expect(parseUrn(`urn:catalog/${CATALOG}`)?.href).toBe(`/catalog/${CATALOG}`);
    expect(parseUrn(`urn:catalog/${CATALOG}/schema/${SCHEMA}`)?.href).toBe(
      `/catalog/${CATALOG}/schemas/${SCHEMA}`,
    );
    expect(parseUrn(`urn:catalog/${CATALOG}/schema/${SCHEMA}/table/${TABLE}`)?.href).toBe(
      `/catalog/${CATALOG}/schemas/${SCHEMA}/tables/${TABLE}`,
    );
  });

  it('links a column and accepts both keywords', () => {
    const base = `urn:catalog/${CATALOG}/schema/${SCHEMA}/table/${TABLE}`;

    expect(parseUrn(`${base}/column/amount`)?.href).toBe(
      `/catalog/${CATALOG}/schemas/${SCHEMA}/tables/${TABLE}/columns/amount`,
    );
    expect(parseUrn(`${base}/field/amount`)?.href).toBe(
      `/catalog/${CATALOG}/schemas/${SCHEMA}/tables/${TABLE}/columns/amount`,
    );
    // The column segment is a name, so the link needs no lookup.
    expect(parseUrn(`${base}/field/amount`)?.label).toBe('amount');
    expect(parseUrn(`${base}/field/amount`)?.reference).toBeNull();
  });

  it('exposes the object a lookup describes', () => {
    expect(parseUrn(`urn:catalog/${CATALOG}`)?.reference).toEqual({
      type: 'catalog',
      id: CATALOG,
    });
    expect(parseUrn(`urn:catalog/${CATALOG}/schema/${SCHEMA}/table/${TABLE}`)?.reference).toEqual({
      type: 'table',
      id: TABLE,
    });
    expect(parseUrn('urn:vocabulary/dom-1/term/term-2')?.reference).toEqual({
      type: 'term',
      id: 'term-2',
    });
    // An entity is part of the model page and is named, not described.
    expect(parseUrn('urn:semantic/m-1/entity/orders')?.reference).toBeNull();
  });

  it('links a term and a domain', () => {
    expect(parseUrn('urn:vocabulary/dom-1')?.href).toBe('/vocabulary/dom-1');
    expect(parseUrn('urn:vocabulary/dom-1/term/term-2')?.href).toBe(
      '/vocabulary/dom-1/terms/term-2',
    );
  });

  it('opens the model on the selected entity', () => {
    expect(parseUrn('urn:semantic/m-1')?.href).toBe('/semantic/m-1');
    expect(parseUrn('urn:semantic/m-1/entity/orders')?.href).toBe('/semantic/m-1?entity=orders');
  });

  it('drops the punctuation of the sentence', () => {
    expect(parseUrn(`urn:catalog/${CATALOG}.`)?.urn).toBe(`urn:catalog/${CATALOG}`);
    // A Chinese sentence closes the URN with a full-width bracket.
    expect(parseUrn(`urn:catalog/${CATALOG}）`)?.urn).toBe(`urn:catalog/${CATALOG}`);
  });

  it('rejects a malformed URN', () => {
    expect(parseUrn('urn:catalog')).toBeNull();
    expect(parseUrn(`urn:catalog/${CATALOG}/table/${TABLE}`)).toBeNull();
    expect(parseUrn('urn:catalog/x/schema/y/schema/z')).toBeNull();
    expect(parseUrn('urn:unknown/x')).toBeNull();
  });
});

describe('urnsIn', () => {
  it('collects the distinct URNs of a text', () => {
    const text = `See urn:catalog/${CATALOG} and urn:catalog/${CATALOG}, then urn:unknown/x.`;

    expect(urnsIn(text).map((target) => target.urn)).toEqual([`urn:catalog/${CATALOG}`]);
  });

  it('answers nothing for text without a URN', () => {
    expect(urnsIn('nothing to link here')).toEqual([]);
  });
});

describe('remarkUrnLinks', () => {
  /** Applies the plugin to a heading node holding the given text. */
  function transform(text: string): Node {
    const tree: Node = {
      type: 'root',
      children: [{ type: 'paragraph', children: [{ type: 'text', value: text }] }],
    };
    remarkUrnLinks()(tree);
    return tree;
  }

  it('replaces a URN with a link node', () => {
    // The sentence punctuation stays in the text around the link.
    const tree = transform(`Look at urn:catalog/${CATALOG}.`);

    const paragraph = tree.children?.[0];
    expect(paragraph?.children?.map((node) => node.type)).toEqual(['text', 'link', 'text']);
    expect(paragraph?.children?.[0]?.value).toBe('Look at ');
    expect(paragraph?.children?.[1]?.url).toBe(`/catalog/${CATALOG}`);
    expect(paragraph?.children?.[1]?.children?.[0]?.value).toBe(`${CATALOG.slice(0, 8)}…`);
    expect(paragraph?.children?.[2]?.value).toBe('.');
  });

  it('keeps the full-width bracket of a Chinese sentence', () => {
    const tree = transform(`（urn:catalog/${CATALOG}）`);

    const children = tree.children?.[0]?.children ?? [];
    expect(children.map((node) => node.type)).toEqual(['text', 'link', 'text']);
    expect(children[1]?.url).toBe(`/catalog/${CATALOG}`);
    expect(children[2]?.value).toBe('）');
  });

  it('links a URN the model wrapped in backticks', () => {
    const tree: Node = {
      type: 'root',
      children: [
        { type: 'paragraph', children: [{ type: 'inlineCode', value: `urn:catalog/${CATALOG}` }] },
      ],
    };

    remarkUrnLinks()(tree);

    expect(tree.children?.[0]?.children?.[0]).toMatchObject({
      type: 'link',
      url: `/catalog/${CATALOG}`,
    });
  });

  it('leaves inline code that is not a URN alone', () => {
    const tree: Node = {
      type: 'root',
      children: [{ type: 'paragraph', children: [{ type: 'inlineCode', value: 'select 1' }] }],
    };

    remarkUrnLinks()(tree);

    expect(tree.children?.[0]?.children?.[0]?.type).toBe('inlineCode');
  });

  it('leaves code alone', () => {
    const tree: Node = {
      type: 'root',
      children: [{ type: 'code', value: 'urn:catalog/x' }],
    };

    remarkUrnLinks()(tree);

    expect(tree.children?.[0]?.value).toBe('urn:catalog/x');
  });

  it('keeps text without a URN untouched', () => {
    const tree = transform('nothing to link here');

    expect(tree.children?.[0]?.children?.[0]?.type).toBe('text');
  });
});
