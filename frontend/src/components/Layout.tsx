/**
 * frontend/src/components/Layout.tsx - 应用布局
 * 侧边栏导航 + 主内容区
 */
import React from "react";
import { NavLink, Outlet } from "react-router-dom";
import {
  Settings,
  LayoutDashboard,
  Heart,
  FileText,
  BotMessageSquare,
  Trophy,
} from "lucide-react";

const navItems = [
  { to: "/dashboard", label: "情报仪表盘", icon: LayoutDashboard },
  { to: "/preferences", label: "偏好设置", icon: Heart },
  { to: "/reports", label: "情报报告", icon: FileText },
  { to: "/ctf", label: "CTF 时间表", icon: Trophy },
  { to: "/agents/xidian/chat", label: "Agent 对话", icon: BotMessageSquare },
  { to: "/config", label: "配置面板", icon: Settings },
];

const Layout: React.FC = () => {
  return (
    <div className="flex h-screen bg-dark-bg text-gray-300">
      {/* 侧边栏 */}
      <aside className="w-56 bg-dark-card border-r border-white/5 flex flex-col flex-shrink-0">
        {/* Logo */}
        <div className="p-5 border-b border-white/5">
          <h1 className="text-base font-bold text-white">西电校园情报助手</h1>
          <p className="text-xs text-gray-500 mt-1">v2.0 · FastAPI</p>
        </div>

        {/* 导航 */}
        <nav className="flex-1 px-3 py-4 space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 ${
                  isActive
                    ? "bg-accent-primary/10 text-accent-light border border-accent-primary/30"
                    : "text-gray-500 hover:text-gray-300 hover:bg-white/5 border border-transparent"
                }`
              }
            >
              {({ isActive }) => (
                <>
                  <item.icon size={18} className={isActive ? "text-accent-light" : "text-gray-500"} />
                  <span>{item.label}</span>
                </>
              )}
            </NavLink>
          ))}
        </nav>

        {/* 底部状态 */}
        <div className="p-4 border-t border-white/5">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.4)]" />
            <span className="text-xs text-gray-500">后端已连接</span>
          </div>
        </div>
      </aside>

      {/* 主内容区 — 通过 Outlet 渲染子路由 */}
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-5xl mx-auto p-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
};

export default Layout;
