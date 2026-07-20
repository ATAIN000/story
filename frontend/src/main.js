import { createApp } from 'vue'
import App from './App.vue'
import { initTheme } from './composables/useTheme'
import './styles/theme.css'

// mount 前定主题：localStorage 记忆 / prefers-color-scheme 初始检测（D7）
initTheme()

createApp(App).mount('#app')
