/**
 * ChatComposer 冒烟测试：锁定「对话 Agent 下拉框真实渲染」的回归
 * （曾因使用未注册的 <a-select> 全局标签导致下拉框不渲染）。
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('@/stores/agents', () => ({
  useAgentsStore: () => ({
    items: [
      { id: 1, name: '默认助手', is_default: true },
      { id: 2, name: '文言助手', is_default: false },
    ],
    fetchAgents: vi.fn(),
  }),
}))

const selectAgent = vi.fn()
vi.mock('@/stores/chat', () => ({
  useChatStore: () => ({
    phase: 'idle',
    currentId: null,
    currentConversation: null,
    effectiveAgentId: 1,
    pendingAgentId: 1,
    selectAgent,
    send: vi.fn(),
    stopGeneration: vi.fn(),
  }),
}))

import ChatComposer from '../ChatComposer.vue'

describe('ChatComposer', () => {
  it('渲染 Agent 下拉框并显示当前生效 Agent', () => {
    const wrapper = mount(ChatComposer, {
      global: {
        stubs: { Transition: false, TransitionGroup: false },
      },
    })
    expect(wrapper.text()).toContain('对话 Agent')
    // Select 真实渲染（antd 结构）而非未知自定义元素
    expect(wrapper.find('.ant-select').exists()).toBe(true)
    // 显示当前生效 Agent 的名称（effectiveAgentId=1 → 默认助手）
    expect(wrapper.text()).toContain('默认助手')
  })

  it('切换下拉选项调用 store.selectAgent', async () => {
    const wrapper = mount(ChatComposer, {
      global: {
        stubs: { Transition: false, TransitionGroup: false },
      },
    })
    const select = wrapper.findComponent({ name: 'ASelect' })
    expect(select.exists()).toBe(true)
    await select.vm.$emit('update:value', 2)
    // 通过 change 事件路径验证
    ;(select.vm as unknown as { $emit: (e: string, v: number) => void }).$emit('change', 2)
    await wrapper.vm.$nextTick()
    expect(selectAgent).toHaveBeenCalledWith(2)
  })
})
