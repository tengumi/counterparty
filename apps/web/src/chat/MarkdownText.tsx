/**
 * Renders an assistant message part written in Markdown.
 *
 * The live model answers in Markdown (`## …`, `**…**`, `- …`) and peppers the
 * prose with raw `[evidence:report:<id>:/path]` tokens. Shown verbatim that is
 * unreadable source. This turns it into the plain typographic block of the
 * mockup (07 §5 `m.answer`): prose, dash bullets, light emphasis, and every
 * evidence token collapsed to a small numbered chip that opens the basis.
 * Raw HTML stays disabled, so model output cannot inject markup.
 */

import { cloneElement, isValidElement, useContext } from 'react';
import type { ReactElement, ReactNode } from 'react';
import Markdown from 'react-markdown';
import type { Components } from 'react-markdown';
import type { TextMessagePartComponent } from '@assistant-ui/react';
import { EvidenceRefContext } from './evidenceContext';
import styles from '../screens/s2/conversation/Conversation.module.css';

const TOKEN = /\s*\[evidence:(report:[0-9a-fA-F-]+:\/[^\]\s]+)\]/g;
// A private-use wrapper the Markdown parser carries through untouched: a plain
// space would be trimmed at a line edge and orphan the digit.
const WRAP = '';
const SENTINEL = /(\d+)/;

/** Swaps evidence tokens for sentinels and returns the ref behind each one. */
function extractRefs(text: string): { text: string; refs: string[] } {
  const refs: string[] = [];
  const replaced = text.replace(TOKEN, (_match, ref: string) => `${WRAP}${refs.push(ref) - 1}${WRAP}`);
  return { text: replaced, refs };
}

interface ChipEnv {
  readonly refs: string[];
  readonly numbers: Map<string, number>;
  readonly onOpen: ((ref: string) => void) | null;
}

/** Walks rendered children and replaces sentinels with numbered chips. */
function withChips(node: ReactNode, env: ChipEnv): ReactNode {
  if (typeof node === 'string') {
    if (!node.includes(WRAP)) return node;
    return node.split(SENTINEL).map((part, index) => {
      if (index % 2 === 0) return part;
      const ref = env.refs[Number(part)];
      if (ref === undefined) return null;
      const n = env.numbers.get(ref) ?? 0;
      return env.onOpen === null ? (
        <sup className={styles.evidenceMark} key={index}>
          {n}
        </sup>
      ) : (
        <button
          aria-label={`Основание ${n}`}
          className={styles.evidence}
          key={index}
          onClick={() => env.onOpen?.(ref)}
          type="button"
        >
          {n}
        </button>
      );
    });
  }
  if (Array.isArray(node)) return node.map((child) => withChips(child, env));
  if (isValidElement(node)) {
    const element = node as ReactElement<{ children?: ReactNode }>;
    if (element.props.children === undefined) return node;
    return cloneElement(element, { children: withChips(element.props.children, env) });
  }
  return node;
}

export function MarkdownContent({ text }: { text: string }) {
  const onOpen = useContext(EvidenceRefContext);
  const { text: prepared, refs } = extractRefs(text);
  const numbers = new Map<string, number>();
  for (const ref of refs) if (!numbers.has(ref)) numbers.set(ref, numbers.size + 1);
  const env: ChipEnv = { refs, numbers, onOpen };
  const chip = (children: ReactNode) => withChips(children, env);

  const components: Components = {
    h1: ({ children }) => <p className={styles.mdHeading}>{chip(children)}</p>,
    h2: ({ children }) => <p className={styles.mdHeading}>{chip(children)}</p>,
    h3: ({ children }) => <p className={styles.mdHeading}>{chip(children)}</p>,
    h4: ({ children }) => <p className={styles.mdHeading}>{chip(children)}</p>,
    h5: ({ children }) => <p className={styles.mdHeading}>{chip(children)}</p>,
    h6: ({ children }) => <p className={styles.mdHeading}>{chip(children)}</p>,
    p: ({ children }) => <p className={styles.mdParagraph}>{chip(children)}</p>,
    ul: ({ children }) => <ul className={styles.mdList}>{children}</ul>,
    ol: ({ children }) => <ol className={styles.mdOrderedList}>{children}</ol>,
    li: ({ children }) => <li className={styles.mdItem}>{chip(children)}</li>,
    a: ({ href, children }) => (
      <a href={href} rel="noreferrer noopener" target="_blank">
        {children}
      </a>
    ),
    code: ({ children }) => <code className={styles.mdCode}>{children}</code>,
    hr: () => null,
  };

  return (
    <div className={styles.markdown}>
      <Markdown components={components} skipHtml={true}>
        {prepared}
      </Markdown>
    </div>
  );
}

/** Adapter for `MessagePrimitive.Parts` `components={{ Text }}`. */
export const MarkdownText: TextMessagePartComponent = ({ text }) => <MarkdownContent text={text} />;
