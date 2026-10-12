import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { api, type AdminRoutingSettings } from "@/api/client";
import {
  LabeledControl,
  SettingsLoading,
  SettingsPanel,
  SettingsSurface,
  SettingsTabShell,
} from "@/components/settings/SettingsPanel";
import {
  allPresetChannelModels,
  CAPABILITY_LABELS,
  CAPABILITY_ORDER,
  clampDefaultToPreset,
  defaultPresetDefaults,
  detectDefaultRemaps,
  PRESET_MODELS,
  type ModelCapability,
} from "@/lib/tokenfreeRecommendedModels";
import { cn } from "@/lib/utils";

const TOKENFREE_CHANNEL_ID = "tokenfree";
const TOKENFREE_BASE_URL = "https://www.tokenfree.com/v1";
const TOKENFREE_CONSOLE_URL = "https://www.tokenfree.com/channels";

const DEFAULT_KEYS = ["text_model", "image_model", "video_model", "audio_model"] as const;

function buildReadiness(data: AdminRoutingSettings | null, hasKey: boolean) {
  const defaults = data?.default_models;
  return [
    { id: "secret", label: "API Key", ready: hasKey },
    { id: "text", label: "文本模型", ready: Boolean(defaults?.text_model) },
    { id: "image", label: "图像模型", ready: Boolean(defaults?.image_model) },
    { id: "video", label: "视频模型", ready: Boolean(defaults?.video_model) },
    { id: "audio", label: "配音模型", ready: Boolean(defaults?.audio_model) },
  ] as const;
}

function normalizeDefaults(raw: AdminRoutingSettings["default_models"] | undefined) {
  const base = defaultPresetDefaults();
  return {
    text_model: clampDefaultToPreset("text", raw?.text_model || base.text_model),
    image_model: clampDefaultToPreset("image", raw?.image_model || base.image_model),
    video_model: clampDefaultToPreset("video", raw?.video_model || base.video_model),
    audio_model: clampDefaultToPreset("audio", raw?.audio_model || base.audio_model),
  };
}

// 开源版模型配置：固定 TokenFree + 四类预设下拉
export function RoutingSettingsPanel() {
  const [data, setData] = useState<AdminRoutingSettings | null>(null);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [defaultRemaps, setDefaultRemaps] = useState<
    Array<{ capability: ModelCapability; from: string; to: string }>
  >([]);

  const channel = data?.system_channels.find((item) => item.id === TOKENFREE_CHANNEL_ID) ?? data?.system_channels[0];
  const hasSavedKey = Boolean(channel?.has_api_key);
  const hasKey = hasSavedKey || Boolean(apiKeyInput.trim());

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api<AdminRoutingSettings>("/api/admin/settings/routing");
      setDefaultRemaps(detectDefaultRemaps(res.default_models));
      setData({
        ...res,
        default_models: normalizeDefaults(res.default_models),
        system_channels: res.system_channels.map((item) =>
          item.id === TOKENFREE_CHANNEL_ID
            ? { ...item, models: allPresetChannelModels() }
            : item,
        ),
      });
      setApiKeyInput("");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "加载模型配置失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const readiness = buildReadiness(data, hasKey);

  function setDefaultModel(key: (typeof DEFAULT_KEYS)[number], value: string) {
    const cap = key.replace("_model", "") as ModelCapability;
    const next = clampDefaultToPreset(cap, value);
    setData((prev) =>
      prev
        ? {
            ...prev,
            default_models: { ...prev.default_models, [key]: next },
          }
        : prev,
    );
  }

  async function handleSave() {
    if (!data) return;
    setSaving(true);
    try {
      const defaults = normalizeDefaults(data.default_models);
      const res = await api<{ settings: AdminRoutingSettings }>("/api/admin/settings/routing", {
        method: "PATCH",
        body: JSON.stringify({
          system_channels: [
            {
              id: TOKENFREE_CHANNEL_ID,
              name: "TokenFree New API",
              base_url: TOKENFREE_BASE_URL,
              api_key: apiKeyInput.trim() || undefined,
              api_format: "openai",
              protocol: "auto",
              models: allPresetChannelModels(),
              enabled: true,
              sort_order: 0,
            },
          ],
          default_models: defaults,
        }),
      });
      setData({
        ...res.settings,
        default_models: normalizeDefaults(res.settings.default_models),
      });
      setDefaultRemaps([]);
      setApiKeyInput("");
      toast.success("模型配置已保存");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  if (loading && !data) {
    return <SettingsLoading label="加载模型配置…" />;
  }

  return (
    <SettingsTabShell onSave={() => void handleSave()} saving={saving} saveLabel="保存">
      <SettingsSurface className="settings-readiness-bar">
        <div className="settings-readiness-title">配置就绪</div>
        <div className="settings-readiness-row">
          {readiness.map((item) => (
            <div key={item.id} className={cn("settings-readiness-item", item.ready && "is-ready")}>
              <span className={cn("settings-readiness-dot", item.ready ? "is-on" : "is-off")} />
              <span>{item.label}</span>
              <em>{item.ready ? "已配置" : "未就绪"}</em>
            </div>
          ))}
        </div>
      </SettingsSurface>

      {(data?.validation_errors.length ?? 0) > 0 ? (
        <SettingsSurface className="border-[#fde2e2] bg-[#fef0f0]">
          <div className="text-xs font-medium text-[#f56c6c]">配置校验</div>
          <ul className="mt-1 space-y-0.5 text-xs text-[#f56c6c]">
            {data?.validation_errors.map((item) => (
              <li key={item}>· {item}</li>
            ))}
          </ul>
        </SettingsSurface>
      ) : null}

      {defaultRemaps.length > 0 ? (
        <SettingsSurface className="border-[#faecd8] bg-[#fdf6ec]">
          <div className="text-xs font-medium text-[#e6a23c]">默认模型已映射到预设</div>
          <ul className="mt-1 space-y-0.5 text-xs text-[#b88230]">
            {defaultRemaps.map((item) => (
              <li key={`${item.capability}-${item.from}`}>
                · {CAPABILITY_LABELS[item.capability]}：
                <code className="mx-1">{item.from}</code>→
                <code className="mx-1">{item.to}</code>
              </li>
            ))}
          </ul>
          <p className="mt-1 text-xs text-[#909399]">保存后将写入上述预设 id；若需保留历史模型请先改下拉再保存。</p>
        </SettingsSurface>
      ) : null}

      <SettingsPanel
        title="TokenFree New API"
        description="上游已锁定。填写 API Key 后，从下方四个预设下拉选择站点默认模型并保存。"
      >
        <div className="settings-field-grid">
          <LabeledControl label="接口地址" className="settings-field-span-full">
            <input className="settings-input" value={TOKENFREE_BASE_URL} readOnly />
            <p className="mt-1 text-xs text-[#909399]">
              控制台：
              <a className="ml-1 text-[#409eff] hover:underline" href={TOKENFREE_CONSOLE_URL} target="_blank" rel="noreferrer">
                {TOKENFREE_CONSOLE_URL}
              </a>
            </p>
          </LabeledControl>
          <LabeledControl
            label="API Key"
            hint={hasSavedKey ? "已保存，留空不修改" : "未配置"}
            className="settings-field-span-full"
          >
            <div className="settings-secret-row">
              <input
                className="settings-input is-secret"
                type="password"
                placeholder={hasSavedKey ? "已保存，留空则不修改" : "粘贴 TokenFree API Key"}
                value={apiKeyInput}
                onChange={(e) => setApiKeyInput(e.target.value)}
              />
              {apiKeyInput ? (
                <button
                  type="button"
                  className="admin-btn admin-btn-secondary settings-mini-btn"
                  onClick={() => setApiKeyInput("")}
                >
                  清除
                </button>
              ) : null}
            </div>
          </LabeledControl>
        </div>
      </SettingsPanel>

      <SettingsPanel
        title="默认模型"
        description="用户端可使用全部预设；此处仅设置站点默认。配音目前仅一项。"
      >
        <div className="settings-field-grid settings-field-grid--2">
          {CAPABILITY_ORDER.map((cap) => {
            const key = `${cap}_model` as (typeof DEFAULT_KEYS)[number];
            const options = PRESET_MODELS[cap];
            return (
              <LabeledControl key={key} label={CAPABILITY_LABELS[cap]}>
                <select
                  className="settings-select"
                  value={data?.default_models[key] ?? options[0]?.id ?? ""}
                  onChange={(e) => setDefaultModel(key, e.target.value)}
                >
                  {options.map((row) => (
                    <option key={row.id} value={row.id}>
                      {row.label}
                    </option>
                  ))}
                </select>
              </LabeledControl>
            );
          })}
        </div>
      </SettingsPanel>
    </SettingsTabShell>
  );
}
