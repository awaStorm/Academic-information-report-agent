/**
 * frontend/src/pages/ConfigPage.tsx - 配置面板页面
 */
import React, { useState, useEffect } from "react";
import { Save, TestTube, Clock, Cpu, Send, Plus, X, Radio } from "lucide-react";
import { configApi, ConfigData } from "../api/config";

const defaultConfig: ConfigData = {
  llm_api_key: "",
  llm_base_url: "",
  llm_model: "",
  temperature: 0.1,
  max_tokens: 20000,
  wecom_webhook: "",
  serverchan_key: "",
  enable_wecom: true,
  enable_console_report: true,
  fetch_count: 5,
  delay_range: [5, 8],
  wechat_targets: [],
  scheduler_enabled: false,
  run_times: ["08:00"],
  failure_alert_threshold: 3,
  dashboard_page_size: 20,
};

const ConfigPage: React.FC = () => {
  const [config, setConfig] = useState<ConfigData>(defaultConfig);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [newTarget, setNewTarget] = useState("");

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    loadConfig();
  }, []);

  const loadConfig = async () => {
    try {
      const res = await configApi.get();
      if (res.success) setConfig(res.data);
    } catch (e) {
      setMessage(`加载失败: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setMessage("");
    try {
      const res = await configApi.update(config);
      setMessage(res.message || "保存成功");
    } catch (e) {
      setMessage(`保存失败: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  const handleTestWecom = async () => {
    try {
      const res = await configApi.testWecom();
      setMessage(res.message || (res.success ? "测试成功" : "测试失败"));
    } catch (e) {
      setMessage(`测试失败: ${(e as Error).message}`);
    }
  };

  const handleAddTarget = () => {
    const name = newTarget.trim().replace(/[,，]/g, "");
    if (!name) return;
    if (config.wechat_targets.includes(name)) {
      setMessage(`"${name}" 已在列表中`);
      return;
    }
    setConfig({ ...config, wechat_targets: [...config.wechat_targets, name] });
    setNewTarget("");
    setMessage("");
  };

  const handleRemoveTarget = (name: string) => {
    setConfig({ ...config, wechat_targets: config.wechat_targets.filter((t) => t !== name) });
    setMessage("");
  };

  if (loading) return <div className="text-gray-500">加载中...</div>;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-white">配置面板</h2>
        <p className="text-sm text-gray-500 mt-1">管理系统配置与推送渠道</p>
      </div>

      <div className="grid grid-cols-2 gap-6">
        {/* 左栏：模型 + 采集 */}
        <div className="space-y-4">
          <h3 className="text-sm font-semibold text-gray-400 flex items-center gap-2">
            <Cpu size={16} /> LLM 模型配置
          </h3>
          <input
            type="password"
            placeholder="API Key (sk-...)"
            className="input-field w-full"
            value={config.llm_api_key}
            onChange={(e) => setConfig({ ...config, llm_api_key: e.target.value })}
          />
          <input
            type="text"
            placeholder="Base URL"
            className="input-field w-full"
            value={config.llm_base_url}
            onChange={(e) => setConfig({ ...config, llm_base_url: e.target.value })}
          />
          <input
            type="text"
            placeholder="模型名称"
            className="input-field w-full"
            value={config.llm_model}
            onChange={(e) => setConfig({ ...config, llm_model: e.target.value })}
          />
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Temperature</label>
              <input type="number" step={0.1} min={0} max={2}
                className="input-field w-full" value={config.temperature}
                onChange={(e) => setConfig({ ...config, temperature: parseFloat(e.target.value) })} />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Max Tokens</label>
              <input type="number" className="input-field w-full" value={config.max_tokens}
                onChange={(e) => setConfig({ ...config, max_tokens: parseInt(e.target.value) })} />
            </div>
          </div>

          <h3 className="text-sm font-semibold text-gray-400 flex items-center gap-2 pt-2">
            <Cpu size={16} /> 采集参数
          </h3>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">每次抓取</label>
              <input type="number" className="input-field w-full" value={config.fetch_count}
                onChange={(e) => setConfig({ ...config, fetch_count: parseInt(e.target.value) })} />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">最小间隔(s)</label>
              <input type="number" className="input-field w-full" value={config.delay_range[0]}
                onChange={(e) => setConfig({ ...config, delay_range: [parseInt(e.target.value), config.delay_range[1]] })} />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">最大间隔(s)</label>
              <input type="number" className="input-field w-full" value={config.delay_range[1]}
                onChange={(e) => setConfig({ ...config, delay_range: [config.delay_range[0], parseInt(e.target.value)] })} />
            </div>
          </div>

          {/* 公众号管理 */}
          <h3 className="text-sm font-semibold text-gray-400 flex items-center gap-2 pt-2">
            <Radio size={16} /> 公众号管理
          </h3>
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="输入公众号名称后点击添加"
              className="input-field flex-1"
              value={newTarget}
              onChange={(e) => setNewTarget(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleAddTarget(); }}
            />
            <button className="btn-primary text-xs px-3 whitespace-nowrap" onClick={handleAddTarget}>
              <Plus size={14} className="inline mr-1" />添加
            </button>
          </div>
          {config.wechat_targets.length === 0 ? (
            <div className="text-xs text-gray-600 py-2">暂无公众号，请在上方输入名称后点击添加</div>
          ) : (
            <div className="flex flex-wrap gap-1.5 mt-1">
              {config.wechat_targets.map((target) => (
                <span key={target} className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded bg-dark-card border border-white/10 text-gray-300">
                  {target}
                  <button
                    className="text-gray-600 hover:text-red-400 transition-colors"
                    onClick={() => handleRemoveTarget(target)}
                    title={`移除 ${target}`}
                  >
                    <X size={12} />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>

        {/* 右栏：推送 + 定时 */}
        <div className="space-y-4">
          <h3 className="text-sm font-semibold text-gray-400 flex items-center gap-2">
            <Send size={16} /> 推送渠道
          </h3>
          <input type="password" placeholder="企业微信 Webhook" className="input-field w-full"
            value={config.wecom_webhook}
            onChange={(e) => setConfig({ ...config, wecom_webhook: e.target.value })} />
          <input type="password" placeholder="Server酱 SendKey" className="input-field w-full"
            value={config.serverchan_key}
            onChange={(e) => setConfig({ ...config, serverchan_key: e.target.value })} />
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input type="checkbox" checked={config.enable_wecom}
              onChange={(e) => setConfig({ ...config, enable_wecom: e.target.checked })}
              className="accent-accent-primary" />
            启用企业微信推送
          </label>
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input type="checkbox" checked={config.enable_console_report}
              onChange={(e) => setConfig({ ...config, enable_console_report: e.target.checked })}
              className="accent-accent-primary" />
            启用控制台报告
          </label>
          <button className="btn-secondary text-xs" onClick={handleTestWecom}>测试企业微信</button>

          <h3 className="text-sm font-semibold text-gray-400 flex items-center gap-2 pt-2">
            <Clock size={16} /> 定时任务
          </h3>
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input type="checkbox" checked={config.scheduler_enabled}
              onChange={(e) => setConfig({ ...config, scheduler_enabled: e.target.checked })}
              className="accent-accent-primary" />
            开启每日定时推送
          </label>
          <input type="text" placeholder="运行时间 (逗号分隔)" className="input-field w-full"
            value={config.run_times.join(",")}
            onChange={(e) => setConfig({ ...config, run_times: e.target.value.split(",").map(s => s.trim()).filter(Boolean) })} />
        </div>
      </div>

      {/* 保存按钮 */}
      <div className="flex justify-center pt-4">
        <button className="btn-primary px-8 py-3 text-base" onClick={handleSave} disabled={saving}>
          <Save size={16} className="inline mr-2" />
          {saving ? "保存中..." : "保存所有配置"}
        </button>
      </div>

      {message && (
        <div className="text-xs text-gray-400 bg-dark-card border border-white/5 rounded-lg p-3 font-mono whitespace-pre-wrap">
          {message}
        </div>
      )}
    </div>
  );
};

export default ConfigPage;
