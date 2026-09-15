/**
 * Markdown 渲染与 XSS 清洗测试（specs/008-chat-conversations research R6）。
 */
import { describe, expect, it } from 'vitest'

import { renderMarkdown } from '../markdown'

describe('renderMarkdown', () => {
  it('渲染基础语法', () => {
    const html = renderMarkdown('# 标题\n\n**加粗** 与 `code`')
    expect(html).toContain('<h1>标题</h1>')
    expect(html).toContain('<strong>加粗</strong>')
    expect(html).toContain('<code>code</code>')
  })

  it('渲染代码块与表格', () => {
    const html = renderMarkdown(
      '```js\nconsole.log("hi")\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |',
    )
    expect(html).toContain('<pre><code')
    expect(html).toContain('<table>')
  })

  it('剥离 script 注入（XSS）', () => {
    const html = renderMarkdown('<script>alert(1)</script>')
    expect(html).not.toContain('<script>')
  })

  it('剥离事件属性注入', () => {
    const html = renderMarkdown('[链接](javascript:alert(1))')
    // markdown-it 拒绝 javascript: href（降级为纯文本），DOMPurify 兜底剥离
    expect(html).not.toContain('<a href="javascript:')
  })

  it('空输入返回空串', () => {
    expect(renderMarkdown('')).toBe('')
  })
})
