/**
 * Markdown 渲染与 XSS 清洗（specs/008-chat-conversations/research.md R6）。
 *
 * html:false 禁用原始 HTML + DOMPurify 二次清洗，双重防护。
 */
import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

/** 渲染 Markdown 文本为安全的 HTML（供 v-html 使用）。 */
export function renderMarkdown(source: string): string {
  const raw = md.render(source ?? '')
  return DOMPurify.sanitize(raw)
}
