import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import PlaceholderCard from '../PlaceholderCard.vue'

describe('PlaceholderCard（FR-013/FR-014 占位页规范）', () => {
  const wrapper = mount(PlaceholderCard, {
    props: {
      title: '聊天',
      description: '与配置好的 Agent 进行对话',
      currentStage: '先把工程骨架、布局与导航跑通',
    },
  })

  it('渲染页面标题与一句简短说明', () => {
    expect(wrapper.find('.page__title').text()).toBe('聊天')
    expect(wrapper.find('.page__desc').text()).toBe('与配置好的 Agent 进行对话')
  })

  it('写明"本模块将在后续阶段开发"', () => {
    expect(wrapper.find('.card__title').text()).toContain('本模块将在后续阶段开发')
  })

  it('告知当前阶段先完成什么', () => {
    expect(wrapper.find('.card__stage').text()).toContain(
      '当前阶段先完成：先把工程骨架、布局与导航跑通',
    )
  })

  it('不含虚构的统计数字、对话和列表（无 list/table 结构）', () => {
    expect(wrapper.find('ul').exists()).toBe(false)
    expect(wrapper.find('ol').exists()).toBe(false)
    expect(wrapper.find('table').exists()).toBe(false)
  })
})
