/**
 * AskUserPanel 组件测试（specs/013-ask-user-tool，US2/US3；013 回写后面板内嵌于输入区）。
 *
 * 覆盖四类回答场景的提交 payload、空回答拦截、"其他"输入框联动。
 * 面板为普通内嵌组件（无 teleport）：直接用 wrapper 查询。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import { useChatStore } from '@/stores/chat'
import AskUserPanel from '../AskUserPanel.vue'

vi.mock('@/stores/chat', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/stores/chat')>()
  return {
    ...original,
    useChatStore: vi.fn(),
  }
})

const submitAskAnswer = vi.fn().mockResolvedValue(undefined)

interface PendingAskShape {
  callId: string
  question: string
  options: string[]
  multiSelect: boolean
  submitting: boolean
}

function makeStore(pendingAsk: PendingAskShape | null) {
  // 组件只消费 pendingAsk 与 submitAskAnswer；类型放宽以隔离真实 store 依赖
  return { pendingAsk, submitAskAnswer } as unknown as ReturnType<typeof useChatStore>
}

async function mountPanel(pendingAsk: PendingAskShape | null) {
  vi.mocked(useChatStore).mockReturnValue(makeStore(pendingAsk))
  const wrapper = mount(AskUserPanel)
  await vi.dynamicImportSettled()
  await wrapper.vm.$nextTick()
  return wrapper
}

async function typeInto(
  input: { element: Element } | ReturnType<ReturnType<typeof mount>['find']>,
  value: string,
): Promise<void> {
  const el = (input as { element: Element }).element as HTMLTextAreaElement
  el.value = value
  el.dispatchEvent(new Event('input', { bubbles: true }))
  await vi.dynamicImportSettled()
}

describe('AskUserPanel（询问面板）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    submitAskAnswer.mockClear()
  })

  it('开放式：输入文本后可提交，payload 为 text', async () => {
    const wrapper = await mountPanel({
      callId: 't1', question: '用于什么场合？', options: [], multiSelect: false, submitting: false,
    })

    expect(wrapper.text()).toContain('用于什么场合？')
    const textarea = wrapper.find('textarea')
    expect(textarea.exists()).toBe(true)
    await typeInto(textarea, '求职面试')

    const button = wrapper.find('button.ant-btn-primary')
    expect(button.attributes('disabled')).toBeUndefined() // 有输入可提交
    await button.trigger('click')
    expect(submitAskAnswer).toHaveBeenCalledWith([], '求职面试')
  })

  it('开放式：空输入禁止提交', async () => {
    const wrapper = await mountPanel({
      callId: 't1', question: '?', options: [], multiSelect: false, submitting: false,
    })

    const button = wrapper.find('button.ant-btn-primary')
    expect(button.attributes('disabled')).toBeDefined() // 空回答禁用（FR-008）
    await button.trigger('click')
    expect(submitAskAnswer).not.toHaveBeenCalled()
  })

  it('选项式单选：选一项提交 payload 含该项；末尾有"其他"', async () => {
    const wrapper = await mountPanel({
      callId: 't2', question: '选一个', options: ['方案A', '方案B'], multiSelect: false, submitting: false,
    })

    expect(wrapper.text()).toContain('其他，我手动输入')
    const radios = wrapper.findAll('input[type="radio"]')
    expect(radios.length).toBe(3) // 2 选项 + 其他
    await radios[0]!.setValue()
    const button = wrapper.find('button.ant-btn-primary')
    await button.trigger('click')
    expect(submitAskAnswer).toHaveBeenCalledWith(['方案A'], null)
  })

  it('选项式多选：可勾选多项后提交', async () => {
    const wrapper = await mountPanel({
      callId: 't3', question: '选多个', options: ['方案A', '方案C'], multiSelect: true, submitting: false,
    })

    const checkboxes = wrapper.findAll('input[type="checkbox"]')
    expect(checkboxes.length).toBe(3)
    await checkboxes[0]!.setValue()
    await checkboxes[1]!.setValue()
    const button = wrapper.find('button.ant-btn-primary')
    await button.trigger('click')
    expect(submitAskAnswer).toHaveBeenCalledWith(['方案A', '方案C'], null)
  })

  it('选中"其他"后出现输入框，提交 payload 为 text', async () => {
    const wrapper = await mountPanel({
      callId: 't4', question: '?', options: ['方案A'], multiSelect: false, submitting: false,
    })

    expect(wrapper.find('.ask-other-input').exists()).toBe(false) // 未选其他时无输入框
    const radios = wrapper.findAll('input[type="radio"]')
    await radios[radios.length - 1]!.setValue() // 选"其他"
    await wrapper.vm.$nextTick()
    const otherInput = wrapper.find('input.ask-other-input') // ant Input 根元素即 input，class 落在其上
    expect(otherInput.exists()).toBe(true)

    const button = wrapper.find('button.ant-btn-primary')
    expect(button.attributes('disabled')).toBeDefined() // 选了其他但没输入 → 不可提交
    await typeInto(otherInput, '自定义回答')
    expect(button.attributes('disabled')).toBeUndefined()
    await button.trigger('click')
    expect(submitAskAnswer).toHaveBeenCalledWith([], '自定义回答')
  })

  it('无 pendingAsk 时不渲染面板', async () => {
    const wrapper = await mountPanel(null)
    expect(wrapper.find('.ask-panel').exists()).toBe(false)
  })
})
