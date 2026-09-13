/**
 * frontend/src/pages/DashboardPage.tsx - 情报仪表盘页面
 */
import React, { useState, useEffect } from "react";
import { RefreshCw } from "lucide-react";
import { dashboardApi, DashboardRecord, DashboardStats } from "../api/dashboard";

const categoryColors: Record<string, string> = {
  "讲座活动": "text-purple-400 bg-purple-400/10",
  "竞赛信息": "text-cyan-400 bg-cyan-400/10",
  "考试安排": "text-amber-400 bg-amber-400/10",
  "放假通知": "text-red-400 bg-red-400/10",
  "课程调整": "text-green-400 bg-green-400/10",
  "社团活动": "text-pink-400 bg-pink-400/10",
  "体育赛事": "text-blue-400 bg-blue-400/10",
  "其他动态": "text-gray-400 bg-gray-400/10",
};

const DashboardPage: React.FC = () => {
  const [records, setRecords] = useState<DashboardRecord[]>([]);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [startDate, setStartDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 7);
    return d.toISOString().slice(0, 10);
  });
  const [endDate, setEndDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [platform, setPlatform] = useState("all");
  const [loading, setLoading] = useState(false);

  const loadData = async () => {
    setLoading(true);
    try {
      const [recordsRes, statsRes] = await Promise.all([
        dashboardApi.getRecords({ start_date: startDate, end_date: endDate, platform }),
        dashboardApi.getStats(),
      ]);
      if (recordsRes.success) setRecords(recordsRes.data);
      if (statsRes.success) setStats(statsRes.data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  // 仅在挂载时加载一次，筛选条件变化后通过"刷新"按钮手动触发
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { loadData(); }, []);

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-white">情报仪表盘</h2>

      {/* 统计卡片 */}
      {stats && (
        <div className="grid grid-cols-4 gap-4">
          {[
            { label: "今日推送", value: stats.today, color: "text-accent-light" },
            { label: "本周推送", value: stats.week, color: "text-cyan-400" },
            { label: "微信情报", value: stats.wechat, color: "text-green-400" },
            { label: "超星通知", value: stats.chaoxing, color: "text-amber-400" },
          ].map((stat) => (
            <div key={stat.label} className="card text-center">
              <div className={`text-2xl font-bold ${stat.color}`}>{stat.value}</div>
              <div className="text-xs text-gray-500 mt-1">{stat.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* 筛选栏 */}
      <div className="flex items-end gap-3">
        <div>
          <label className="text-xs text-gray-500 mb-1 block">开始日期</label>
          <input type="date" className="input-field" value={startDate}
            onChange={(e) => setStartDate(e.target.value)} />
        </div>
        <div>
          <label className="text-xs text-gray-500 mb-1 block">结束日期</label>
          <input type="date" className="input-field" value={endDate}
            onChange={(e) => setEndDate(e.target.value)} />
        </div>
        <div>
          <label className="text-xs text-gray-500 mb-1 block">平台</label>
          <select className="input-field" value={platform}
            onChange={(e) => setPlatform(e.target.value)}>
            <option value="all">全部</option>
            <option value="wechat">微信</option>
            <option value="chaoxing">超星</option>
          </select>
        </div>
        <button className="btn-primary" onClick={loadData} disabled={loading}>
          <RefreshCw size={14} className={`inline mr-1 ${loading ? "animate-spin" : ""}`} />
          刷新
        </button>
        <span className="text-xs text-gray-500 ml-auto">共 {records.length} 条记录</span>
      </div>

      {/* 记录列表 */}
      <div className="space-y-2 max-h-[500px] overflow-y-auto pr-2">
        {records.length === 0 ? (
          <div className="text-center text-gray-600 py-10">暂无推送记录</div>
        ) : (
          records.map((record, idx) => (
            <div key={idx} className="card !p-4">
              <div className="flex justify-between items-center mb-2">
                <span className="text-sm font-semibold text-white">{record.title}</span>
                <span className="text-xs text-gray-500">{record.push_time}</span>
              </div>
              <div className="flex gap-2 mb-2">
                <span className={`text-xs px-2 py-0.5 rounded ${record.platform === "wechat" ? "text-green-400 bg-green-400/10" : "text-blue-400 bg-blue-400/10"}`}>
                  {record.platform === "wechat" ? "WeChat" : "ChaoXing"}
                </span>
                <span className={`text-xs px-2 py-0.5 rounded ${categoryColors[record.category] || "text-gray-400 bg-gray-400/10"}`}>
                  {record.category}
                </span>
                <div className={`w-2 h-2 rounded-full mt-1 ${
                  record.status === "pushed" ? "bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.4)]" :
                  record.status === "failed" ? "bg-red-500 shadow-[0_0_6px_rgba(239,68,68,0.4)]" :
                  "bg-amber-500 shadow-[0_0_6px_rgba(245,158,11,0.4)]"
                }`} title={
                  record.status === "pushed" ? "已推送" :
                  record.status === "failed" ? "推送失败" :
                  "等待推送"
                } />
              </div>
              <p className="text-xs text-gray-500 line-clamp-2">{record.brief}</p>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

export default DashboardPage;
