import { SaveOutlined } from '../icons';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Button as UIButton, Card, CardContent, CardHeader, CardTitle, Input, Switch, Textarea, notify } from '@/components/ui';
import { api, TENANT_ID } from '../api/client';
import type { EnterpriseAuthUser } from '../auth';
import AccountApiKeyDialog from '../components/AccountApiKeyDialog';
import { ConfirmDialog } from '../components/ConfirmDialog';
import type { UIConfigRead } from '../types';
import { KeyRound, RotateCcw, ShieldCheck } from 'lucide-react';

type CompressionMode = 'acp' | 'legacy';

type UiConfigForm = {
  show_thinking_trace: boolean;
  show_skill_trace: boolean;
  show_tool_trace: boolean;
  reflection_max_rounds: string;
  agent_loop_max_actions: string;
  sandbox_enabled: boolean;
  harness_storage_path: string;
  sandbox_network_mode: 'all' | 'allowlist' | 'deny';
  sandbox_allowed_domains: string;
  context_compression_mode: CompressionMode;
  acp_model_context_limit: string;
  acp_nudge_max_pct: string;
  acp_nudge_emergency_pct: string;
  acp_nudge_min_pct: string;
};

const DEFAULT_UI_CONFIG: UiConfigForm = {
  show_thinking_trace: true,
  show_skill_trace: true,
  show_tool_trace: true,
  reflection_max_rounds: '1',
  agent_loop_max_actions: '32',
  sandbox_enabled: false,
  harness_storage_path: '',
  sandbox_network_mode: 'all',
  sandbox_allowed_domains: '',
  context_compression_mode: 'legacy',
  acp_model_context_limit: '128000',
  acp_nudge_max_pct: '0.70',
  acp_nudge_emergency_pct: '0.85',
  acp_nudge_min_pct: '0.45',
};

function formatDateOnly(value: string): string {
  const normalized = /(?:z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? value.slice(0, 10) : date.toISOString().slice(0, 10);
}

export default function RuntimeSettingsPage({ currentUser }: { currentUser: EnterpriseAuthUser }) {
  const [form, setForm] = useState<UiConfigForm>(DEFAULT_UI_CONFIG);
  const [loading, setLoading] = useState(false);
  const [updatedAt, setUpdatedAt] = useState('');
  const [setupMessage, setSetupMessage] = useState('');
  const [effectiveStoragePath, setEffectiveStoragePath] = useState('');
  const [apiKeyOpen, setApiKeyOpen] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [acpEnabled, setAcpEnabled] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const savedModeRef = useRef<CompressionMode>('legacy');
  const [sandboxStatus, setSandboxStatus] = useState<Pick<UIConfigRead, 'sandbox_status' | 'sandbox_status_message' | 'sandbox_status_remediation'>>({});
  const update = (patch: Partial<UiConfigForm>) => setForm((prev) => ({ ...prev, ...patch }));

  useEffect(() => {
    api.get<UIConfigRead>(`/api/enterprise/ui-config?tenant_id=${TENANT_ID}`)
      .then((row) => {
        const compressionMode: CompressionMode = row.context_compression_mode === 'acp' ? 'acp' : 'legacy';
        setForm({
          show_thinking_trace: row.show_thinking_trace,
          show_skill_trace: row.show_skill_trace,
          show_tool_trace: row.show_tool_trace,
          reflection_max_rounds: String(row.reflection_max_rounds),
          agent_loop_max_actions: String(row.agent_loop_max_actions),
          sandbox_enabled: row.sandbox_enabled,
          harness_storage_path: row.harness_storage_path || '',
          sandbox_network_mode: row.sandbox_network_mode || 'all',
          sandbox_allowed_domains: (row.sandbox_allowed_domains || []).join('\n'),
          context_compression_mode: compressionMode,
          acp_model_context_limit: String(row.acp_model_context_limit ?? 128000),
          acp_nudge_max_pct: String(row.acp_nudge_max_pct ?? 0.7),
          acp_nudge_emergency_pct: String(row.acp_nudge_emergency_pct ?? 0.85),
          acp_nudge_min_pct: String(row.acp_nudge_min_pct ?? 0.45),
        });
        savedModeRef.current = compressionMode;
        setAcpEnabled(row.acp_enabled);
        setUpdatedAt(row.updated_at);
        setEffectiveStoragePath(row.effective_harness_storage_path || '');
        setSetupMessage(row.sandbox_setup_instructions || '');
        setSandboxStatus({ sandbox_status: row.sandbox_status, sandbox_status_message: row.sandbox_status_message, sandbox_status_remediation: row.sandbox_status_remediation });
      })
      .catch((error) => notify.error(error.message));
  }, []);

  function parseNumericForm(form: UiConfigForm) {
    return {
      reflectionMaxRounds: Number(form.reflection_max_rounds),
      agentLoopMaxActions: Number(form.agent_loop_max_actions),
      acpModelContextLimit: Number(form.acp_model_context_limit),
      acpNudgeMaxPct: Number(form.acp_nudge_max_pct),
      acpNudgeEmergencyPct: Number(form.acp_nudge_emergency_pct),
      acpNudgeMinPct: Number(form.acp_nudge_min_pct),
    };
  }

  async function save() {
    const values = parseNumericForm(form);
    if (Object.values(values).some(Number.isNaN)) {
      notify.error('反思轮数、单轮最大动作数与 ACP 阈值必须是数字');
      return;
    }
    if (form.context_compression_mode !== savedModeRef.current) {
      setConfirmOpen(true);
      return;
    }
    await submitSave(values);
  }

  async function submitSave(values: ReturnType<typeof parseNumericForm>) {
    setLoading(true);
    try {
      const row = await api.put<UIConfigRead>('/api/enterprise/ui-config', {
        tenant_id: TENANT_ID,
        show_thinking_trace: form.show_thinking_trace,
        show_skill_trace: form.show_skill_trace,
        show_tool_trace: form.show_tool_trace,
        reflection_max_rounds: values.reflectionMaxRounds,
        agent_loop_max_actions: values.agentLoopMaxActions,
        sandbox_enabled: form.sandbox_enabled,
        harness_storage_path: form.harness_storage_path.trim(),
        sandbox_network_mode: form.sandbox_network_mode,
        sandbox_allowed_domains: form.sandbox_allowed_domains.split(/[\n,]/).map((item) => item.trim()).filter(Boolean),
        context_compression_mode: form.context_compression_mode,
        acp_model_context_limit: values.acpModelContextLimit,
        acp_nudge_max_pct: values.acpNudgeMaxPct,
        acp_nudge_emergency_pct: values.acpNudgeEmergencyPct,
        acp_nudge_min_pct: values.acpNudgeMinPct,
      });
      savedModeRef.current = form.context_compression_mode;
      setUpdatedAt(row.updated_at);
      setEffectiveStoragePath(row.effective_harness_storage_path || '');
      if (row.restart_scheduled) {
        setRestarting(true);
        notify.success('沙盒设置已保存，StaffDeck 正在重启');
        await waitForApplicationRestart();
        window.location.reload();
        return;
      }
      notify.success('运行设置已保存');
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '保存失败');
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <div className="page-title">
        <div><h3>运行设置</h3><p className="text-[12px] text-muted-foreground">统一影响当前租户下所有数字员工的执行行为。</p></div>
        <UIButton disabled={loading || restarting} onClick={() => void save()}>
          {restarting ? <RotateCcw className="size-[15px] animate-spin" /> : <SaveOutlined />}
          {restarting ? '等待应用重启' : '保存设置'}
        </UIButton>
      </div>
      <Card className="editor-card settings-card">
        <CardHeader><CardTitle>执行记录与 Agent Loop</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-[16px]">
          <LabeledField label="上下文压缩机制" hint="标准压缩按固定阈值自动生成摘要；智能可恢复压缩由模型自主决定压缩时机与内容，压缩块可恢复、可检索。代价：压缩依赖模型主动触发，若未及时触发，长对话可能触及请求长度上限被裁剪；恢复与检索同样由模型发起。">
            <select className="h-[36px] rounded-md border border-input bg-background px-[10px] text-[13px]" value={form.context_compression_mode} onChange={(e) => update({ context_compression_mode: e.target.value as CompressionMode })}>
              <option value="legacy">标准压缩</option>
              <option value="acp" disabled={!acpEnabled}>智能可恢复压缩{!acpEnabled ? '（未启用）' : ''}</option>
            </select>
          </LabeledField>
          {form.context_compression_mode === 'acp' && (
            <>
              {!acpEnabled && <p className="text-[11px] leading-[16px] text-muted-foreground">ACP 功能未启用，以下阈值将在启用后生效。</p>}
              <LabeledField label="上下文上限（token）" hint="模型上下文窗口上限，上下文占用达到阈值比例时触发压缩决策。"><Input type="number" min={1000} max={10000000} step={1000} disabled={!acpEnabled} value={form.acp_model_context_limit} onChange={(e) => update({ acp_model_context_limit: e.target.value })} /></LabeledField>
              <LabeledField label="常规压缩触发阈值" hint="上下文占用达到上限的该比例时，提示模型考虑压缩。"><Input type="number" min={0.01} max={0.99} step={0.01} disabled={!acpEnabled} value={form.acp_nudge_max_pct} onChange={(e) => update({ acp_nudge_max_pct: e.target.value })} /></LabeledField>
              <LabeledField label="紧急压缩触发阈值" hint="上下文占用达到上限的该比例时，升级为紧急压缩提示。"><Input type="number" min={0.01} max={0.99} step={0.01} disabled={!acpEnabled} value={form.acp_nudge_emergency_pct} onChange={(e) => update({ acp_nudge_emergency_pct: e.target.value })} /></LabeledField>
              <LabeledField label="最低压缩触发阈值" hint="上下文占用低于上限的该比例时，不再提示压缩。"><Input type="number" min={0.01} max={0.99} step={0.01} disabled={!acpEnabled} value={form.acp_nudge_min_pct} onChange={(e) => update({ acp_nudge_min_pct: e.target.value })} /></LabeledField>
            </>
          )}
          <SwitchRow label="展示思考状态" checked={form.show_thinking_trace} onChange={(next) => update({ show_thinking_trace: next })} />
          <SwitchRow label="展示执行技能" checked={form.show_skill_trace} onChange={(next) => update({ show_skill_trace: next })} />
          <SwitchRow label="展示工具调用" checked={form.show_tool_trace} onChange={(next) => update({ show_tool_trace: next })} />
          <LabeledField label="反思轮数" hint="设为 0 时关闭反思；每轮允许模型检查当前技能和工具结果。"><Input type="number" min={0} max={5} step={1} value={form.reflection_max_rounds} onChange={(e) => update({ reflection_max_rounds: e.target.value })} /></LabeledField>
          <LabeledField label="单轮最大动作数" hint="限制一次用户输入内连续决策和工具调用的次数，避免无限循环。"><Input type="number" min={1} max={100} step={1} value={form.agent_loop_max_actions} onChange={(e) => update({ agent_loop_max_actions: e.target.value })} /></LabeledField>
        </CardContent>
      </Card>
      <Card className="editor-card settings-card">
        <CardHeader><CardTitle className="flex items-center gap-[8px]"><ShieldCheck className="size-[16px]" />执行隔离与文件存储</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-[16px]">
          <SwitchRow label="启用 SRT 沙盒" checked={form.sandbox_enabled} onChange={(next) => update({ sandbox_enabled: next })} hint="仅管理员可修改。打开或关闭后保存将自动重启 StaffDeck。默认关闭。" />
          <div className={`whitespace-pre-line rounded-md border px-[12px] py-[10px] text-[12px] leading-[18px] ${sandboxStatus.sandbox_status === 'ready' ? 'border-emerald-200 bg-emerald-50 text-emerald-900' : sandboxStatus.sandbox_status === 'degraded' ? 'border-red-300 bg-red-50 text-red-900' : sandboxStatus.sandbox_status === 'disabled' ? 'border-slate-200 bg-slate-50 text-slate-700' : 'border-amber-200 bg-amber-50 text-amber-900'}`}>
            <div className="font-medium">沙盒状态：{sandboxStatus.sandbox_status === 'ready' ? '可用' : sandboxStatus.sandbox_status === 'degraded' ? '已降级为无沙盒（高风险）' : sandboxStatus.sandbox_status === 'disabled' ? '未启用' : '不可用'}</div>
            {sandboxStatus.sandbox_status_message && <div>{sandboxStatus.sandbox_status_message}</div>}
            {sandboxStatus.sandbox_status_remediation && <div>{sandboxStatus.sandbox_status_remediation}</div>}
          </div>
          {setupMessage && <div className="whitespace-pre-line rounded-md border border-amber-200 bg-amber-50 px-[12px] py-[10px] text-[12px] leading-[18px] text-amber-900">{setupMessage}</div>}
          {!form.sandbox_enabled && <LabeledField label="文件存储目录" hint={`沙盒关闭时，附件、任务文件与生成产物写入此目录。留空使用默认目录${effectiveStoragePath ? `：${effectiveStoragePath}` : ''}。`}><Input value={form.harness_storage_path} onChange={(e) => update({ harness_storage_path: e.target.value })} placeholder={effectiveStoragePath || '/data/staffdeck-files'} /></LabeledField>}
          {form.sandbox_enabled && <LabeledField label="网络访问" hint="统一影响所有 Harness/SRT 执行。默认联网按运行环境放行；白名单只允许列出的域名；全拒绝禁止外网。">
            <select className="h-[36px] rounded-md border border-input bg-background px-[10px] text-[13px]" value={form.sandbox_network_mode} onChange={(e) => update({ sandbox_network_mode: e.target.value as UiConfigForm['sandbox_network_mode'] })}>
              <option value="all">默认联网</option><option value="allowlist">白名单</option><option value="deny">全拒绝</option>
            </select>
          </LabeledField>}
          {form.sandbox_enabled && form.sandbox_network_mode === 'allowlist' && <LabeledField label="允许的域名" hint="每行一个域名，也支持 *.example.com。"><Textarea rows={4} value={form.sandbox_allowed_domains} onChange={(e) => update({ sandbox_allowed_domains: e.target.value })} placeholder="api.example.com\n*.internal.example.com" /></LabeledField>}
          <p className="text-[11px] leading-[16px] text-muted-foreground">关闭沙盒时，命令仍受 TaskFrame 工作区、运行时长和输出大小限制，但不再使用操作系统级 SRT 隔离。</p>
          {updatedAt && <span className="text-[12px] text-muted-foreground">最后更新：{formatDateOnly(updatedAt)}</span>}
        </CardContent>
      </Card>
      <Card className="editor-card settings-card">
        <CardHeader><CardTitle className="flex items-center gap-[8px]"><KeyRound className="size-[16px]" />API 全量密钥</CardTitle></CardHeader>
        <CardContent className="flex items-center justify-between gap-[20px]">
          <div><p className="text-[13px] font-medium text-[#2f3442]">管理员账号全量访问</p><p className="mt-[4px] text-[11px] leading-[17px] text-muted-foreground">用于 API 查询当前账号可访问的数字员工与资源。明文密钥只在创建或轮换时展示一次。</p></div>
          <UIButton variant="outline" onClick={() => setApiKeyOpen(true)}><KeyRound className="size-[15px]" />管理密钥</UIButton>
        </CardContent>
      </Card>
      <AccountApiKeyDialog account={currentUser} open={apiKeyOpen} onClose={() => setApiKeyOpen(false)} />
      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        destructive={false}
        confirmText="确认保存"
        title="切换上下文压缩机制？"
        description="该偏好将应用于当前租户的全部会话，旧上下文将按新机制处理。"
        onConfirm={() => {
          setConfirmOpen(false);
          void submitSave(parseNumericForm(form));
        }}
      />
    </>
  );
}

function LabeledField({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return <label className="flex flex-col gap-[6px]"><span className="text-[12px] font-medium text-[#464c5e]">{label}</span>{hint && <span className="text-[11px] leading-[16px] text-muted-foreground">{hint}</span>}{children}</label>;
}

function SwitchRow({ label, hint, checked, onChange }: { label: string; hint?: string; checked: boolean; onChange: (next: boolean) => void }) {
  return <label className="flex items-center justify-between gap-[16px]"><span><span className="block text-[12px] font-medium text-[#464c5e]">{label}</span>{hint && <span className="mt-[3px] block text-[11px] leading-[16px] text-muted-foreground">{hint}</span>}</span><Switch checked={checked} onCheckedChange={onChange} /></label>;
}

async function waitForApplicationRestart(): Promise<void> {
  await new Promise((resolve) => window.setTimeout(resolve, 1800));
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      await api.get('/api/health');
      return;
    } catch {
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
    }
  }
  throw new Error('StaffDeck 重启超时，请稍后手动刷新页面');
}
