/**
 * frontend/src/pages/ConfigPage.tsx - 配置面板页面
 */
import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Save, Clock, Cpu, Send, Radio, GraduationCap, ExternalLink, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { configApi, ConfigData } from "../api/config";

// 侧边栏栏目（与 Layout.tsx 的 navItems 对应）；配置面板不可隐藏，避免被锁在门外
const NAV_ITEMS = [
  { to: "/dashboard", label: "情报仪表盘" },
  { to: "/preferences", label: "偏好设置" },
  { to: "/reports", label: "情报报告" },
  { to: "/ctf", label: "CTF 时间表" },
  { to: "/calendar", label: "事件日历" },
  { to: "/source-cards", label: "信源雷达" },
  { to: "/agents/xidian/chat", label: "Agent 对话" },
];

const defaultConfig: ConfigData = {
  profile: {
    school_name: "",
    assistant_display_name: "校园情报助手",
    probe_query: "",
    report_title: "校园情报提醒",
    identity_prompt: "你是【校园情报 Agent】，负责校园资讯的采集、筛选与推送。{school_context}",
  },
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
  hidden_nav: [],
  multimodal_enabled: false,
  multimodal_api_key: "",
  multimodal_base_url: "",
  multimodal_model: "",
  max_images: 3,
};

const ConfigPage: React.FC = () => {
  const [config, setConfig] = useState<ConfigData>(defaultConfig);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const navigate = useNavigate();

  const toggleNav = (to: string) => {
    const hidden = new Set(config.hidden_nav || []);
    hidden.has(to) ? hidden.delete(to) : hidden.add(to);
    setConfig({ ...config, hidden_nav: Array.from(hidden) });
  };

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
      // targets 由信源雷达统一管理，配置面板只读展示，保存时不回传，避免覆盖雷达写回的目标
      const { wechat_targets: _ignored, ...payload } = config;
      void _ignored;
      const res = await configApi.update(payload);
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

  if (loading) return <div className="text-gray-500">加载中...</div>;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-white">配置面板</h2>
        <p className="text-sm text-gray-500 mt-1">管理系统配置与推送渠道</p>
      </div>

      <div className="bg-dark-card/60 border border-white/5 rounded-xl p-4 space-y-3">
        <h3 className="text-sm font-semibold text-accent-primary flex items-center gap-2">
          <GraduationCap size={16} /> 身份与展示（面向任意学校）
        </h3>
        <p className="text-[11px] text-gray-500 leading-relaxed">
          留空即通用模式，不绑定任何学校。学校名会注入 Agent 提示词与检索探活；显示名用于侧边栏与推送标题。
        </p>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">学校名称（留空=通用）</label>
            <input type="text" placeholder="如：XX 大学（留空则面向所有学校）"
              className="input-field w-full" value={config.profile.school_name}
              onChange={(e) => setConfig({ ...config, profile: { ...config.profile, school_name: e.target.value } })} />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">助手显示名</label>
            <input type="text" className="input-field w-full" value={config.profile.assistant_display_name}
              onChange={(e) => setConfig({ ...config, profile: { ...config.profile, assistant_display_name: e.target.value } })} />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">检索探活关键词（留空=用学校名）</label>
            <input type="text" placeholder="留空自动使用学校名"
              className="input-field w-full" value={config.profile.probe_query}
              onChange={(e) => setConfig({ ...config, profile: { ...config.profile, probe_query: e.target.value } })} />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">简报/推送标题前缀</label>
            <input type="text" className="input-field w-full" value={config.profile.report_title}
              onChange={(e) => setConfig({ ...config, profile: { ...config.profile, report_title: e.target.value } })} />
          </div>
        </div>
        <div>
          <label className="text-xs text-gray-500 mb-1 block">身份提示词模板（{"{school_context}"} 会替换为学校说明）</label>
          <textarea rows={2} className="input-field w-full resize-y" value={config.profile.identity_prompt}
            onChange={(e) => setConfig({ ...config, profile: { ...config.profile, identity_prompt: e.target.value } })} />
        </div>
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

          {/* 多模态识图配置 */}
          <h3 className="text-sm font-semibold text-gray-400 flex items-center gap-2 pt-2">
            <Cpu size={16} /> 多模态识图（可选）
          </h3>
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input type="checkbox" checked={config.multimodal_enabled}
              onChange={(e) => setConfig({ ...config, multimodal_enabled: e.target.checked })}
              className="accent-accent-primary" />
            启用多模态识图（从通知图片提取文字/日期/二维码）
          </label>
          <p className="text-[11px] text-gray-600 leading-relaxed">
            未开启或调用失败时自动降级为纯文本分析，不影响主流程。若当前模型不支持视觉，可在此填写独立的视觉模型 API。<br />
            注意：① 配置保存后需<strong>重启后端</strong>生效；② 每条含图情报都会单独串行调用一次视觉模型（单条最多识别下方设置的张数），含图情报较多时整轮分析耗时会明显增加；③ 图片过大或接口不支持该模型时该条自动跳过识图，仅以纯文本分析。
          </p>
          {config.multimodal_enabled && (
            <div className="space-y-2 bg-dark-card/50 border border-white/5 rounded-lg p-3">
              <input type="password" placeholder="多模态 API Key（留空复用 LLM Key）"
                className="input-field w-full" value={config.multimodal_api_key}
                onChange={(e) => setConfig({ ...config, multimodal_api_key: e.target.value })} />
              <input type="text" placeholder="多模态 Base URL（留空复用 LLM Base URL）"
                className="input-field w-full" value={config.multimodal_base_url}
                onChange={(e) => setConfig({ ...config, multimodal_base_url: e.target.value })} />
              <input type="text" placeholder="多模态模型名（如 deepseek-vl / qwen-vl-max）"
                className="input-field w-full" value={config.multimodal_model}
                onChange={(e) => setConfig({ ...config, multimodal_model: e.target.value })} />
              <div>
                <label className="text-xs text-gray-500 mb-1 block">每条最多识图张数</label>
                <input type="number" min={1} max={10} className="input-field w-full" value={config.max_images}
                  onChange={(e) => setConfig({ ...config, max_images: parseInt(e.target.value) })} />
              </div>
            </div>
          )}

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

          {/* 公众号监控目标（只读镜像，唯一入口在信源雷达） */}
          <div className="flex items-center justify-between pt-2">
            <h3 className="text-sm font-semibold text-gray-400 flex items-center gap-2">
              <Radio size={16} /> 公众号监控目标
            </h3>
            <button className="btn-secondary text-[11px] px-2 py-1 flex items-center gap-1"
              onClick={() => navigate("/source-cards")}>
              去信源雷达管理 <ExternalLink size={12} />
            </button>
          </div>
          <p className="text-[11px] text-gray-600 leading-relaxed">
            此处只读展示当前微信内核的检查目标。增删公众号请在「信源雷达」手动新建公众号卡片（支持直接填公众号名称），
            或让 AI 生成后加入清单/容器，目标会自动同步到这里。
          </p>
          {config.wechat_targets.length === 0 ? (
            <div className="text-xs text-gray-600 py-2">暂无公众号监控目标</div>
          ) : (
            <div className="flex flex-wrap gap-1.5 mt-1">
              {config.wechat_targets.map((target) => (
                <span key={target} className="text-xs px-2 py-1 rounded bg-dark-card border border-white/10 text-gray-300">
                  {target}
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

          {/* 侧边栏栏目显隐（按钮制） */}
          <h3 className="text-sm font-semibold text-gray-400 flex items-center gap-2 pt-2">
            <PanelLeftClose size={16} /> 侧边栏栏目
          </h3>
          <p className="text-[11px] text-gray-600 leading-relaxed">
            点击按钮撤下/恢复栏目（撤下后侧边栏不再显示，页面仍可访问；配置面板不可撤下）。保存后生效。
          </p>
          <div className="flex flex-wrap gap-1.5">
            {NAV_ITEMS.map((item) => {
              const hidden = (config.hidden_nav || []).includes(item.to);
              return (
                <button key={item.to} onClick={() => toggleNav(item.to)}
                  className={`inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded border transition-colors ${
                    hidden
                      ? "text-gray-600 border-white/5 bg-white/[0.02] line-through"
                      : "text-gray-300 border-white/10 bg-white/5 hover:border-accent-primary/40"
                  }`}>
                  {hidden ? <PanelLeftClose size={11} /> : <PanelLeftOpen size={11} />}
                  {item.label}
                </button>
              );
            })}
          </div>
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
