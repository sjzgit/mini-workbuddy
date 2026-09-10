// 引入顺序（固定）：设计令牌 → 网络字体 → 全局样式 → antd reset
import '@/styles/tokens.scss'
import '@fontsource-variable/dm-sans'
import '@fontsource-variable/outfit'
import '@fontsource-variable/fira-code'
import '@/styles/main.scss'
import 'ant-design-vue/dist/reset.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'

const app = createApp(App)

app.use(createPinia())
app.use(router)

app.mount('#app')
