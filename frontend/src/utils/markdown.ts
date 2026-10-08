import { marked } from 'marked';
import DOMPurify from 'dompurify';
import katex from 'katex';
import 'katex/dist/katex.min.css';

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

export const renderMarkdown = (text: string): string => {
  if (!text) return '';
  const textWithMath = renderMath(text);
  const rawHtml = marked.parse(textWithMath) as string;
  return DOMPurify.sanitize(rawHtml, {
    USE_PROFILES: { html: true, svg: true, svgFilters: true },
    ADD_ATTR: ['aria-hidden', 'role'],
  });
};