/**
 * 模块元数据（导航菜单与路由的共享单一来源）。
 * 菜单显示顺序与文案严格对应 spec FR-010：
 * 聊天 / Agent 管理 / 模型管理 / 工具管理 / MCP 管理 / Skills 管理 / 运行记录 / Agent 评测
 */
import type { FunctionalComponent } from 'vue'
import type { RouteLocationRaw } from 'vue-router'
import {
  MessageOutlined,
  RobotOutlined,
  DatabaseOutlined,
  ToolOutlined,
  ApiOutlined,
  ThunderboltOutlined,
  HistoryOutlined,
  LineChartOutlined,
} from '@ant-design/icons-vue'

export interface ModuleMeta {
  /** 路由路径（不含前导斜杠，挂在布局子路由下） */
  path: string
  /** 菜单与页面标题 */
  title: string
  /** 页面顶部的一句简短说明 */
  description: string
  /** 图标 */
  icon: FunctionalComponent
  /** 占位页告知"当前阶段先完成什么" */
  currentStage: string
  /** 完整路由地址（菜单跳转用） */
  to: RouteLocationRaw
}

function meta(
  path: string,
  title: string,
  description: string,
  icon: FunctionalComponent,
  currentStage: string,
): ModuleMeta {
  return { path, title, description, icon, currentStage, to: `/${path}` }
}

export const MODULES: ModuleMeta[] = [
  meta('chat', '聊天', '与配置好的 Agent 进行对话', MessageOutlined, '先把工程骨架、布局与导航跑通'),
  meta('agents', 'Agent 管理', '创建与维护可用的 Agent', RobotOutlined, '先完成工程初始化与本导航布局'),
  meta('models', '模型管理', '登记和管理可调用的模型', DatabaseOutlined, '先完成工程初始化与本导航布局'),
  meta('tools', '工具管理', '维护 Agent 可使用的工具', ToolOutlined, '先完成工程初始化与本导航布局'),
  meta('mcp', 'MCP 管理', '接入与管理 MCP 服务', ApiOutlined, '先完成工程初始化与本导航布局'),
  meta('skills', 'Skills 管理', '管理 Agent 的技能包', ThunderboltOutlined, '先完成工程初始化与本导航布局'),
  meta('runs', '运行记录', '回看每次任务的执行过程', HistoryOutlined, '先完成工程初始化与本导航布局'),
  meta('evaluations', 'Agent 评测', '评估 Agent 的表现与质量', LineChartOutlined, '先完成工程初始化与本导航布局'),
]
