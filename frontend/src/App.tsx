/**
 * frontend/src/App.tsx - 应用入口
 */
import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import ConfigPage from "./pages/ConfigPage";
import DashboardPage from "./pages/DashboardPage";
import PreferencesPage from "./pages/PreferencesPage";
import ReportsPage from "./pages/ReportsPage";
import AgentChatPage from "./pages/AgentChatPage";

const App: React.FC = () => {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/config" element={<ConfigPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/preferences" element={<PreferencesPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/agents/:agentName/chat" element={<AgentChatPage />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
};

export default App;
