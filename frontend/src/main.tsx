import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { wsManager } from './api/websocket'

// 应用级 WebSocket：启动即连接，换页/组件卸载不断开，断线自动重连
wsManager.connect()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
