/**
 * SSE 帧解析器测试（specs/008-chat-conversations contracts StreamEvent）。
 */
import { describe, expect, it } from 'vitest'

import { SseParser } from '../chat'

describe('SseParser', () => {
  it('解析单个完整帧', () => {
    const parser = new SseParser()
    const frames = parser.push('event: content_delta\ndata: {"text":"你好"}\n\n')
    expect(frames).toEqual([{ event: 'content_delta', data: '{"text":"你好"}' }])
  })

  it('跨块分片正确缓冲', () => {
    const parser = new SseParser()
    const first = parser.push('event: content_delta\ndata: {"text":"你')
    expect(first).toEqual([])
    const second = parser.push('好"}\n\n')
    expect(second).toHaveLength(1)
    const frame = second[0]
    if (frame === undefined) {
      throw new Error('expected a frame')
    }
    expect(JSON.parse(frame.data).text).toBe('你好')
  })

  it('多帧一次推送并忽略注释行', () => {
    const parser = new SseParser()
    const frames = parser.push(
      'event: reasoning_delta\ndata: {"text":"想"}\n\n' +
        'event: content_delta\ndata: {"text":"答"}\n\n' +
        ': ping\n\n' +
        'event: done\ndata: {"message":null,"stopped":true}\n\n',
    )
    expect(frames.map((f) => f.event)).toEqual([
      'reasoning_delta',
      'content_delta',
      'done',
    ])
  })

  it('仅注释推送返回空', () => {
    const parser = new SseParser()
    const frames = parser.push(': ping\n\n')
    expect(frames).toEqual([])
  })
})
