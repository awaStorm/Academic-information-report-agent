/**
 * frontend/src/pages/ReportsPage.tsx - 情报报告页面
 */
import React, { useState, useEffect } from "react";
import { RefreshCw, FileText } from "lucide-react";
import { reportsApi } from "../api/reports";
import ReactMarkdown from "react-markdown";

const ReportsPage: React.FC = () => {
  const [files, setFiles] = useState<string[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [content, setContent] = useState<string>("");
  const [loading, setLoading] = useState(false);

  const loadFiles = async () => {
    try {
      const res = await reportsApi.list();
      if (res.success) {
        setFiles(res.data || []);
        if (res.data && res.data.length > 0 && !selected) {
          setSelected(res.data[0]);
        }
      }
    } catch (e) {
      console.error(e);
    }
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { loadFiles(); }, []);

  useEffect(() => {
    if (selected) loadContent();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  const loadContent = async () => {
    if (!selected) return;
    setLoading(true);
    try {
      const res = await reportsApi.get(selected);
      if (res.success && res.data) {
        setContent(res.data.content);
      }
    } catch (e) {
      setContent(`加载失败: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-white">情报报告</h2>
        <p className="text-sm text-gray-500 mt-1">查看 AI 生成的每日情报分析报告</p>
      </div>

      <div className="grid grid-cols-4 gap-6">
        {/* 左侧文件列表 */}
        <div className="col-span-1">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs text-gray-500">报告列表</span>
            <button className="text-gray-500 hover:text-gray-300" onClick={loadFiles}>
              <RefreshCw size={14} />
            </button>
          </div>
          <div className="space-y-1">
            {files.length === 0 ? (
              <div className="text-xs text-gray-600">暂无报告</div>
            ) : (
              files.map((f) => (
                <button
                  key={f}
                  onClick={() => setSelected(f)}
                  className={`w-full text-left px-3 py-2 rounded-lg text-xs transition-all duration-200 ${
                    selected === f
                      ? "bg-accent-primary/10 text-accent-light border border-accent-primary/30"
                      : "text-gray-500 hover:bg-white/5 border border-transparent"
                  }`}
                >
                  <FileText size={12} className="inline mr-1" />
                  {f}
                </button>
              ))
            )}
          </div>
        </div>

        {/* 右侧报告内容 */}
        <div className="col-span-3">
          <div className="card !p-6 min-h-[500px] overflow-y-auto">
            {loading ? (
              <div className="text-gray-500 text-sm">加载中...</div>
            ) : (
              <div className="prose prose-invert prose-sm max-w-none">
                <ReactMarkdown>{content}</ReactMarkdown>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default ReportsPage;
