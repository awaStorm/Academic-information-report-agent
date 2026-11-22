/**
 * frontend/src/components/common/ConfigEditor.tsx - 信源卡片编辑器
 * 网站卡片：编辑名字/URL/选择器 + DOM 候选重选 + 样例人工确认 + 测试抓取验证后保存。
 * 公众号/容器：编辑名字/备注/公众号名。
 */
import React, { useState } from "react";
import { X, Play, Save, Loader2, CheckCircle2, AlertTriangle, RefreshCw, ListFilter } from "lucide-react";
import { sourceCardsApi, SourceCard as Card, DomCandidate } from "../../api/sourceCards";
import { toast } from "./Toast";

interface PreviewResult {
  success: boolean;
  count?: number;
  samples?: Array<{ title: string; link: string; date: string }>;
  message?: string;
  error?: string;
}

interface Props {
  card: Card;
  onClose: () => void;
  onSaved: () => void;
}

const ConfigEditor: React.FC<Props> = ({ card, onClose, onSaved }) => {
  const cfg = card.config || {};
  const isWebsite = card.type === "website";
  const candidates: DomCandidate[] = cfg._candidates || [];
  const [name, setName] = useState(card.name);
  const [note, setNote] = useState(card.note || "");
  const [account, setAccount] = useState(String(cfg.account || card.name));
  const [url, setUrl] = useState(String(cfg.url || ""));
  const [listSelector, setListSelector] = useState(String(cfg.list_selector || ""));
  const [titleSel, setTitleSel] = useState(String(cfg.fields?.title || ""));
  const [linkSel, setLinkSel] = useState(String(cfg.fields?.link || ""));
  const [dateSel, setDateSel] = useState(String(cfg.fields?.date || ""));
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [reselecting, setReselecting] = useState<number | null>(null);

  const config = () => ({ url, list_selector: listSelector,
    fields: { title: titleSel, link: linkSel, date: dateSel } });
  const invalidate = () => { setPreview(null); setConfirmed(false); };

  const handleTest = async () => {
    if (!url.trim() || !listSelector.trim()) {
      toast.warning("URL 和列表选择器为必填项");
      return;
    }
    setTesting(true);
    setPreview(null);
    setConfirmed(false);
    try {
      const res = await sourceCardsApi.testConfig(config());
      setPreview(res);
      if (res.success) toast.success(res.message || "配置有效，请核对下方样例");
      else toast.error(res.error || "测试失败");
    } catch (e) {
      toast.error(`测试失败: ${(e as Error).message}`);
    } finally {
      setTesting(false);
    }
  };

  const handleReselect = async (c: DomCandidate) => {
    setReselecting(c.index);
    setPreview(null);
    setConfirmed(false);
    try {
      const res = await sourceCardsApi.reselect(card.id, c.index, name.trim() || undefined);
      if (res.success) {
        setUrl(String(cfg.url || ""));
        setListSelector(c.selector);
        setTitleSel(c.fields?.title || "");
        setLinkSel(c.fields?.link || "");
        setDateSel(c.fields?.date || "");
        setPreview(res.preview ? { success: true, ...res.preview, samples: res.preview.samples?.map(s => ({ ...s, link: "", date: "" })) } : null);
        toast.success(res.message || `已切换到候选 ${c.index}`);
        onSaved();
      } else {
        toast.error(res.error || "重选失败");
      }
    } catch (e) {
      toast.error(`重选失败: ${(e as Error).message}`);
    } finally {
      setReselecting(null);
    }
  };

  const handleSaveWebsite = async () => {
    if (!preview?.success) {
      toast.warning("请先点「测试抓取」并确认命中数据");
      return;
    }
    if (!confirmed) {
      toast.warning("请勾选「样例确认无误」后再保存");
      return;
    }
    setSaving(true);
    try {
      const res = await sourceCardsApi.updateConfig(card.id, { name: name.trim() || card.name, config: config(), note });
      if (res.success) {
        toast.success(res.message || "配置已验证并保存");
        onSaved();
        onClose();
      } else {
        toast.error(res.error || "保存失败");
      }
    } catch (e) {
      toast.error(`保存失败: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  const handleSaveMeta = async () => {
    if (!name.trim()) {
      toast.warning("卡片名称不能为空");
      return;
    }
    setSaving(true);
    try {
      const res = card.type === "wechat"
        ? await sourceCardsApi.edit(card.id, { name: name.trim(), note, account: account.trim() })
        : await sourceCardsApi.edit(card.id, { name: name.trim(), note });
      if (res.success) {
        toast.success("卡片信息已更新");
        onSaved();
        onClose();
      } else {
        toast.error(res.error || "保存失败");
      }
    } catch (e) {
      toast.error(`保存失败: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-overlay-in" onClick={onClose}>
      <div className="w-full max-w-3xl max-h-[92vh] overflow-y-auto rounded-2xl border border-violet-500/20 bg-[#13131F] p-5 shadow-2xl animate-modal-in"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-bold text-white">{isWebsite ? "编辑网站信源卡片" : "编辑卡片信息"}</h3>
            <p className="text-xs text-gray-500 mt-1">
              {isWebsite ? "核对样例并确认结构，测试通过后才可保存" : "修改卡片的显示名称与备注"}
            </p>
          </div>
          <button className="text-gray-500 hover:text-gray-300" onClick={onClose} aria-label="关闭"><X size={18} /></button>
        </div>

        <div className="space-y-3">
          <div>
            <label className="text-xs text-gray-400 mb-1 block">卡片名称</label>
            <input className="input-field w-full" value={name} onChange={(e) => { setName(e.target.value); if (isWebsite) invalidate(); }} placeholder="给这张卡片起个名字" />
          </div>
          {!isWebsite && card.type === "wechat" && (
            <div>
              <label className="text-xs text-gray-400 mb-1 block">公众号名称（检查目标）</label>
              <input className="input-field w-full" value={account} onChange={(e) => setAccount(e.target.value)} placeholder="公众号全名" />
            </div>
          )}
          <div>
            <label className="text-xs text-gray-400 mb-1 block">备注 / 推荐理由</label>
            <textarea rows={2} className="input-field w-full resize-y" value={note} onChange={(e) => setNote(e.target.value)} placeholder="这张卡片为什么值得关注" />
          </div>

          {isWebsite && (
            <>
              <div className="pt-2 border-t border-white/5">
                <label className="text-xs text-gray-400 mb-1 block">入口 URL</label>
                <input className="input-field w-full" value={url} onChange={(e) => { setUrl(e.target.value); invalidate(); }} placeholder="https://example.com/news" />
              </div>
              <div>
                <label className="text-xs text-gray-400 mb-1 block">列表项 CSS 选择器（选中每一条通知，不是外层容器）</label>
                <input className="input-field w-full font-mono text-xs" value={listSelector} onChange={(e) => { setListSelector(e.target.value); invalidate(); }} placeholder=".news-list > li" />
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="text-xs text-gray-400 mb-1 block">标题选择器</label>
                  <input className="input-field w-full font-mono text-xs" value={titleSel} onChange={(e) => { setTitleSel(e.target.value); invalidate(); }} placeholder="a.title" />
                </div>
                <div>
                  <label className="text-xs text-gray-400 mb-1 block">链接选择器</label>
                  <input className="input-field w-full font-mono text-xs" value={linkSel} onChange={(e) => { setLinkSel(e.target.value); invalidate(); }} placeholder="a.title" />
                </div>
                <div>
                  <label className="text-xs text-gray-400 mb-1 block">日期选择器（可选）</label>
                  <input className="input-field w-full font-mono text-xs" value={dateSel} onChange={(e) => { setDateSel(e.target.value); invalidate(); }} placeholder="span.date" />
                </div>
              </div>

              {candidates.length > 0 && (
                <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
                  <div className="flex items-center gap-2 mb-2 text-xs text-gray-400">
                    <ListFilter size={14} className="text-accent-light" />
                    发现时检测到 {candidates.length} 个候选结构，可人工重选：
                    {cfg._selected !== undefined && <span className="text-violet-400">当前为候选 {cfg._selected}</span>}
                  </div>
                  <div className="space-y-1.5 max-h-40 overflow-y-auto">
                    {candidates.map((c) => (
                      <button key={c.index}
                        className={`w-full text-left px-2.5 py-2 rounded-md border text-xs transition-colors flex items-start gap-2
                          ${cfg._selected === c.index ? "border-violet-500/50 bg-violet-500/10" : "border-white/5 hover:border-violet-500/30 bg-white/[0.02]"}`}
                        onClick={() => handleReselect(c)} disabled={reselecting !== null}>
                        {reselecting === c.index ? <Loader2 size={13} className="animate-spin mt-0.5 flex-shrink-0" /> : <RefreshCw size={13} className="text-gray-500 mt-0.5 flex-shrink-0" />}
                        <span className="min-w-0">
                          <span className="text-gray-300">候选 {c.index} · {c.item_count} 条</span>
                          <span className="block text-gray-500 truncate mt-0.5">{c.samples[0] || c.selector}</span>
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        <div className="flex gap-2 mt-4">
          {isWebsite ? (
            <button className="btn-secondary text-sm flex items-center gap-2" onClick={handleTest} disabled={testing}>
              {testing ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
              {testing ? "抓取测试中..." : "测试抓取"}
            </button>
          ) : null}
          <button className="btn-primary text-sm flex items-center gap-2"
            onClick={isWebsite ? handleSaveWebsite : handleSaveMeta}
            disabled={saving || (isWebsite && (!preview?.success || !confirmed))}>
            {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
            {isWebsite ? "确认并保存" : "保存信息"}
          </button>
        </div>

        {isWebsite && preview && (
          <div className={`mt-4 rounded-lg border p-3 ${preview.success ? "border-green-500/30 bg-green-500/5" : "border-red-500/30 bg-red-500/5"}`}>
            <div className={`flex items-center gap-2 text-sm font-medium ${preview.success ? "text-green-400" : "text-red-400"}`}>
              {preview.success ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
              {preview.success ? preview.message : preview.error}
            </div>
            {preview.samples && preview.samples.length > 0 && (
              <>
                <ul className="mt-2 space-y-1 text-xs text-gray-400">
                  {preview.samples.map((s, i) => (
                    <li key={i} className="truncate">· {s.title}{s.date ? `  [${s.date}]` : ""}</li>
                  ))}
                </ul>
                {preview.success && (
                  <label className="flex items-center gap-2 mt-3 text-xs text-gray-300 cursor-pointer">
                    <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)}
                      className="accent-violet-500 cursor-pointer" />
                    以上样例确实是该站点的通知/赛事列表，确认无误
                  </label>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default ConfigEditor;
