/**
 * 模型表单校验规则（与契约 ModelUpsertRequest 对齐，前端先拦一道）。
 *
 * 契约主定义：specs/002-model-management/contracts/api-contract.md
 * 后端 Pydantic 仍是最终校验方；本模块保证字段旁提示与后端语义一致。
 */
import type { Rule } from 'ant-design-vue/es/form'

/** 服务地址校验：http(s) 合法 URL，且不得误填到 /chat/completions */
export function validateBaseUrl(value: string): string | null {
  const v = (value ?? '').trim()
  if (!v) return '请填写服务地址'
  const schemeIndex = v.indexOf('://')
  if (!/^https?:\/\//.test(v) || schemeIndex < 0) {
    return '服务地址必须以 http:// 或 https:// 开头'
  }
  const hostPart = v.slice(schemeIndex + 3)
  if (!/^([^/\s]+\.[^/\s]+|localhost(:\d+)?)/i.test(hostPart)) {
    return '服务地址格式不正确，请填写完整地址'
  }
  if (v.replace(/\/+$/, '').toLowerCase().endsWith('/chat/completions')) {
    return '无需填写到 /chat/completions，只填 API Base URL（一般以 /v1 结尾）'
  }
  return null
}

/** 跨字段校验：最大输出长度 ≤ 上下文长度（两者均需为正整数） */
export function validateMaxOutput(
  maxOutput: number | null,
  contextLength: number | null,
): string | null {
  if (maxOutput === null || maxOutput === undefined) return '请填写最大输出长度'
  if (!Number.isInteger(maxOutput) || maxOutput <= 0) return '必须为正整数'
  if (contextLength !== null && contextLength !== undefined && maxOutput > contextLength) {
    return '最大输出长度不能超过上下文长度'
  }
  return null
}

/** 价格校验：允许留空（未配置）与 0（免费），不允许负数 */
export function validatePrice(value: number | null): string | null {
  if (value === null || value === undefined) return null
  if (Number.isNaN(value)) return '请填写数字'
  if (value < 0) return '价格不能为负数'
  return null
}

/** 正整数必填（上下文长度等） */
export function validatePositiveInt(value: number | null): string | null {
  if (value === null || value === undefined) return '必填'
  if (!Number.isInteger(value) || value <= 0) return '必须为正整数'
  return null
}

/**
 * 构建完整表单规则。
 * 跨字段依赖通过取值函数注入（base_url 自身格式、max_output 对比 context_length）。
 */
export function buildFormRules(
  getBaseUrl: () => string,
  getContextLength: () => number | null,
): Record<string, Rule[]> {
  return {
    display_name: [
      { required: true, whitespace: true, message: '请填写显示名称' },
      { max: 100, message: '不超过 100 个字符' },
    ],
    model_identifier: [
      { required: true, whitespace: true, message: '请填写模型标识' },
      { max: 200, message: '不超过 200 个字符' },
    ],
    base_url: [
      { required: true, message: '请填写服务地址' },
      {
        validator: () => {
          const err = validateBaseUrl(getBaseUrl())
          return err ? Promise.reject(err) : Promise.resolve()
        },
      },
    ],
    context_length: [
      { required: true, message: '请填写上下文长度' },
      {
        validator: (_rule: Rule, value: number | null) => {
          const err = validatePositiveInt(value)
          return err ? Promise.reject(err) : Promise.resolve()
        },
      },
    ],
    max_output_tokens: [
      { required: true, message: '请填写最大输出长度' },
      {
        validator: (_rule: Rule, value: number | null) => {
          const err = validateMaxOutput(value, getContextLength())
          return err ? Promise.reject(err) : Promise.resolve()
        },
      },
    ],
    temperature: [
      { required: true, message: '请填写温度' },
      { type: 'number', min: 0, max: 2, message: '温度范围为 0 – 2' },
    ],
    input_price: [priceRule()],
    output_price: [priceRule()],
    cached_input_price: [priceRule()],
  }
}

function priceRule(): Rule {
  return {
    validator: (_rule: Rule, value: number | null) => {
      const err = validatePrice(value)
      return err ? Promise.reject(err) : Promise.resolve()
    },
  }
}
