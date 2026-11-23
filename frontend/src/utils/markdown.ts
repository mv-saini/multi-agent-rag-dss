import { marked } from 'marked';
import DOMPurify from 'dompurify';
import katex from 'katex';
import 'katex/dist/katex.min.css';
import type { CitationSource } from '@/types/app';

marked.use({
  tokenizer: {
    code(src) { return undefined; }
  }
});

marked.setOptions({
  gfm: true,
  breaks: true,
});

export const renderMath = (text: string): string => {
  let output = text;

  // Display math: $$ ... $$
  output = output.replace(/\$\$([\s\S]+?)\$\$/g, (_, expression: string) => {
    try {
      return katex.renderToString(expression.trim(), { displayMode: true, throwOnError: false });
    } catch {
      return `$$${expression}$$`;
    }
  });

  // Inline math: $ ... $
  output = output.replace(/(?<!\\)\$([^$\n]+?)\$/g, (_, expression: string) => {
    try {
      return katex.renderToString(expression.trim(), { displayMode: false, throwOnError: false });
    } catch {
      return `$${expression}$`;
    }
  });

  return output;
};

const renderCitationTokens = (
  text: string,
  sources: Record<string, CitationSource>,
): string => {
  // Remove any incomplete citation markers
  let output = text
    .replace(/\uE200cite\uE202[\s\S]*?\uE201/g, '')
    .replace(/\uE200[^\uE201]*$/g, '');

  // Replace validated citation tokens with HTML buttons
  return output.replace(
    /\[\[CITE:([A-Za-z0-9_-]+)\]\]/g,
    (_match, sourceId: string) => {
      const source = sources[sourceId];
      if (!source) return '';
      const label = source.label;
      return `<button type="button" class="citation-ref" data-citation-id="${sourceId}" aria-label="Show citation ${label}">[${label}]</button>`;
    },
  );
};

export const renderMarkdown = (
  text: string,
  citationSources: Record<string, CitationSource> = {},
): string => {
  if (!text) return '';
  const textWithMath = renderMath(renderCitationTokens(text, citationSources));
  const rawHtml = marked.parse(textWithMath) as string;
  return DOMPurify.sanitize(rawHtml, {
    USE_PROFILES: { html: true, svg: true, svgFilters: true },
    ADD_ATTR: ['aria-hidden', 'aria-label', 'role', 'data-citation-id'],
  });
};
