/**
 * frontend/src/pages/PreferencesPage.tsx - 偏好设置页面
 */
import React, { useState, useEffect } from "react";
import { Save } from "lucide-react";
import { preferencesApi } from "../api/preferences";

const ALL_CATEGORIES = [
  "讲座活动", "竞赛信息", "考试安排", "放假通知",
  "课程调整", "社团活动", "体育赛事", "其他动态",
];

const PreferencesPage: React.FC = () => {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    loadPreferences();
  }, []);

  const loadPreferences = async () => {
    try {
      const res = await preferencesApi.get();
      if (res.success && res.data) {
        setSelected(new Set(res.data.categories || []));
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const toggleCategory = (cat: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat); else next.add(cat);
      return next;
    });
  };

  const handleSave = async () => {
    setSaving(true);
    setMessage("");
    try {
      const res = await preferencesApi.update(Array.from(selected));
      setMessage(`偏好已保存: ${Array.from(selected).join(", ") || "全部类别"}`);
    } catch (e) {
      setMessage(`保存失败: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="text-gray-500">加载中...</div>;

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h2 className="text-xl font-bold text-white">偏好设置</h2>
        <p className="text-sm text-gray-500 mt-1">选择感兴趣的类别，将在情报分析时获得更高优先级</p>
      </div>

      {/* 2×4 网格 */}
      <div className="grid grid-cols-2 gap-3">
        {ALL_CATEGORIES.map((cat) => (
          <button
            key={cat}
            onClick={() => toggleCategory(cat)}
            className={`text-left px-4 py-3 rounded-lg border text-sm font-medium transition-all duration-200 ${
              selected.has(cat)
                ? "bg-accent-primary/10 border-accent-primary/40 text-accent-light"
                : "bg-white/5 border-white/10 text-gray-400 hover:border-white/20"
            }`}
          >
            <span className={`w-4 h-4 rounded border mr-2 inline-flex items-center justify-center text-xs ${
              selected.has(cat) ? "bg-accent-primary border-accent-primary text-white" : "border-white/20"
            }`}>
              {selected.has(cat) ? "✓" : ""}
            </span>
            {cat}
          </button>
        ))}
      </div>

      {/* 保存按钮 */}
      <div className="flex justify-center pt-4">
        <button className="btn-primary px-8 py-3" onClick={handleSave} disabled={saving}>
          <Save size={16} className="inline mr-2" />
          {saving ? "保存中..." : "保存偏好"}
        </button>
      </div>

      {message && (
        <div className="text-xs text-gray-400 bg-dark-card border border-white/5 rounded-lg p-3">
          {message}
        </div>
      )}
    </div>
  );
};

export default PreferencesPage;
