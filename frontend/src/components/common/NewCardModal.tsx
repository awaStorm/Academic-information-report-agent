/**
 * frontend/src/components/common/NewCardModal.tsx - 手动新建信源卡片
 * 按已有卡片格式创建：网站（填 URL + 选择器，测试后验证）/ 公众号 / 微信容器。
 */
import React, { useState } from "react";
import { X, Play, Plus, Loader2, CheckCircle2, AlertTriangle } from "lucide-react";
import { sourceCardsApi, CardType } from "../../api/sourceCards";
import { toast } from "./Toast";

interface Props {
  onClose: () => void;
  onCreated: () => void;
}

const NewCardModal: React.FC<Props> = ({ onClose, onCreated }) => {
  const [type, setType] = useState<CardType>("website");
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [url, setUrl] = useState("");
  const [listSelector, setListSelector] = useState("");
  const [titleSel, setTitleSel] = useState("");
  const [linkSel, setLinkSel] = useState("");
  const [dateSel, setDateSel] = useState("");
  const [account, setAccount] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message?: string; samples?: Array<{ title: string }> } | null>(null);
  const [saving, setSaving] = useState(false);

  const config = () => type === "website"
    ? { url, list_selector: listSelector, fields: { title: titleSel, link: linkSel, date: dateSel }, pagination: { type: "none" } }
    : type === "wechat" ? { account: account || name } : { children: [] };

  const handleTest = async () => {
    if (!url.trim() || !listSelector.trim()) {
      toast.warning("URL 和列表选择器为必填项");
      return;
    }
    setTesting(true);
    setTestResult(null);
    try {
      const res = await sourceCardsApi.testConfig({ url, list_selector: listSelector, fields: { title: titleSel, link: linkSel, date: dateSel } });
      setTestResult(res);
      if (res.success) toast.success(res.message || "配置有效");
      else toast.error(res.error || "测试失败");
    } catch (e) {
      toast.error(`测试失败: ${(e as Error).message}`);
    } finally {
      setTesting(false);
    }
  };

  const handleCreate = async () => {
    if (!name.trim()) {
      toast.warning("请填写卡片名称");
      return;
    }
    if (type === "website" && !testResult?.success) {
      toast.warning("网站卡片需先测试抓取通过才能创建");
      return;
    }
    setSaving(true);
    try {
      const res = await sourceCardsApi.add({
        type, name: name.trim(), config: config(), note,
        verified: type === "website" ? true : false,
      });
      if (res.success) {
        toast.success(`已创建「${name.trim()}」卡片`);
        onCreated();
        onClose();
      } else {
        toast.error("创建失败");
      }
    } catch (e) {
      toast.error(`创建失败: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  // 系统内置类型（超星/微信内核）由应用自动创建，不提供手动新建
  const creatableTypes: CardType[] = ["website", "wechat", "wechat_group"];
  const typeLabels: Record<string, string> = {
    website: "网站大卡片", wechat: "公众号小卡片", wechat_group: "微信容器",
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-overlay-in" onClick={onClose}>
      <div className="w-full max-w-2xl max-h-[92vh] overflow-y-auto rounded-2xl border border-violet-500/20 bg-[#13131F] p-5 shadow-2xl animate-modal-in"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-bold text-white">手动新建信源卡片</h3>
            <p className="text-xs text-gray-500 mt-1">按已有卡片格式创建，网站卡片需测试抓取通过</p>
          </div>
          <button className="text-gray-500 hover:text-gray-300" onClick={onClose} aria-label="关闭"><X size={18} /></button>
        </div>

        <div className="flex gap-2 mb-4">
          {creatableTypes.map((t) => (
            <button key={t} onClick={() => { setType(t); setTestResult(null); }}
              className={`flex-1 px-3 py-2 rounded-lg border text-sm transition-colors
                ${type === t ? "border-violet-500/60 bg-violet-500/15 text-violet-300" : "border-white/10 text-gray-400 hover:border-violet-500/30"}`}>
              {typeLabels[t]}
            </button>
          ))}
        </div>

        <div className="space-y-3">
          <div>
            <label className="text-xs text-gray-400 mb-1 block">卡片名称</label>
            <input className="input-field w-full" value={name} onChange={(e) => setName(e.target.value)} placeholder="例如：XX大学通知网" />
          </div>
          {type === "wechat" && (
            <div>
              <label className="text-xs text-gray-400 mb-1 block">公众号名称（检查目标，留空同卡片名）</label>
              <input className="input-field w-full" value={account} onChange={(e) => setAccount(e.target.value)} placeholder="公众号全名" />
            </div>
          )}
          <div>
            <label className="text-xs text-gray-400 mb-1 block">备注 / 推荐理由（可选）</label>
            <textarea rows={2} className="input-field w-full resize-y" value={note} onChange={(e) => setNote(e.target.value)} placeholder="这张卡片的价值" />
          </div>

          {type === "website" && (
            <>
              <div className="pt-2 border-t border-white/5">
                <label className="text-xs text-gray-400 mb-1 block">入口 URL</label>
                <input className="input-field w-full" value={url} onChange={(e) => { setUrl(e.target.value); setTestResult(null); }} placeholder="https://example.com/news" />
              </div>
              <div>
                <label className="text-xs text-gray-400 mb-1 block">列表项 CSS 选择器</label>
                <input className="input-field w-full font-mono text-xs" value={listSelector} onChange={(e) => { setListSelector(e.target.value); setTestResult(null); }} placeholder=".news-list > li" />
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="text-xs text-gray-400 mb-1 block">标题选择器</label>
                  <input className="input-field w-full font-mono text-xs" value={titleSel} onChange={(e) => { setTitleSel(e.target.value); setTestResult(null); }} placeholder="a.title" />
                </div>
                <div>
                  <label className="text-xs text-gray-400 mb-1 block">链接选择器</label>
                  <input className="input-field w-full font-mono text-xs" value={linkSel} onChange={(e) => { setLinkSel(e.target.value); setTestResult(null); }} placeholder="a.title" />
                </div>
                <div>
                  <label className="text-xs text-gray-400 mb-1 block">日期选择器</label>
                  <input className="input-field w-full font-mono text-xs" value={dateSel} onChange={(e) => { setDateSel(e.target.value); setTestResult(null); }} placeholder="span.date" />
                </div>
              </div>
            </>
          )}
        </div>

        <div className="flex gap-2 mt-4">
          {type === "website" && (
            <button className="btn-secondary text-sm flex items-center gap-2" onClick={handleTest} disabled={testing}>
              {testing ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
              测试抓取
            </button>
          )}
          <button className="btn-primary text-sm flex items-center gap-2" onClick={handleCreate}
            disabled={saving || (type === "website" && !testResult?.success)}>
            {saving ? <Loader2 size={15} className="animate-spin" /> : <Plus size={15} />}
            创建卡片
          </button>
        </div>

        {testResult && (
          <div className={`mt-4 rounded-lg border p-3 ${testResult.success ? "border-green-500/30 bg-green-500/5" : "border-red-500/30 bg-red-500/5"}`}>
            <div className={`flex items-center gap-2 text-sm ${testResult.success ? "text-green-400" : "text-red-400"}`}>
              {testResult.success ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
              {testResult.success ? testResult.message : testResult.message}
            </div>
            {testResult.samples && (
              <ul className="mt-2 space-y-1 text-xs text-gray-400">
                {testResult.samples.map((s, i) => <li key={i} className="truncate">· {s.title}</li>)}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default NewCardModal;
