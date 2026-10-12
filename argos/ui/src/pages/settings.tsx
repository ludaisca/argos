import { useEffect, useState } from "react";
import {
  CopyIcon,
  MoonIcon,
  SaveIcon,
  StethoscopeIcon,
  SunIcon,
  TestTubeDiagonalIcon,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardDescription,
  CardHeader,
  CardPanel,
  CardTitle,
} from "@/components/ui/card";
import { Field, FieldDescription, FieldItem, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useArgos } from "@/lib/store";
import type { DoctorResult } from "@/lib/types";

export function SettingsPage({
  theme,
  setTheme,
}: {
  theme: "dark" | "light";
  setTheme: (theme: "dark" | "light") => void;
}) {
  const { settings, meta, saveSettings, testLlm, runDoctor } = useArgos();
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [interval, setIntervalHours] = useState(12);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [testOk, setTestOk] = useState(false);
  const [testing, setTesting] = useState(false);
  const [doctor, setDoctor] = useState<DoctorResult | null>(null);
  const [doctoring, setDoctoring] = useState(false);

  useEffect(() => {
    if (!settings) return;
    setBaseUrl(settings.llm_base_url);
    setModel(settings.llm_model);
    setIntervalHours(settings.interval_hours);
  }, [settings]);

  const onSaveLlm = async () => {
    await saveSettings({
      ...(apiKey.trim() ? { llm_api_key: apiKey.trim() } : {}),
      llm_base_url: baseUrl.trim(),
      llm_model: model.trim(),
    });
    setApiKey("");
  };

  const onTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testLlm();
      setTestOk(result.ok);
      setTestResult(
        result.ok
          ? `El modelo ${result.model} respondió: ${result.reply}`
          : `Error (${result.model}): ${result.error}`,
      );
    } catch (error) {
      setTestOk(false);
      setTestResult(`Error: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setTesting(false);
    }
  };

  const onDoctor = async () => {
    setDoctoring(true);
    try {
      setDoctor(await runDoctor());
    } finally {
      setDoctoring(false);
    }
  };

  const copy = (value: string) => {
    void navigator.clipboard.writeText(value);
  };

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="font-semibold text-2xl tracking-tight">Ajustes</h1>
        <p className="text-sm text-muted-foreground">
          Proveedor del LLM, cadencia, apariencia y chequeos de sesiones.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Proveedor LLM</CardTitle>
            <CardDescription>
              Cualquier API compatible con OpenAI (DeepSeek, OpenAI, Groq, Gemini compat, Ollama…).
            </CardDescription>
            <CardAction>
              {settings?.llm_key_set ? (
                <Badge variant="success">{settings.llm_key_masked}</Badge>
              ) : (
                <Badge variant="error">sin key</Badge>
              )}
            </CardAction>
          </CardHeader>
          <CardPanel className="flex flex-col gap-4">
            <Field>
              <FieldLabel>API key</FieldLabel>
              <FieldItem>
                <Input
                  type="password"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  placeholder="escribí una nueva para cambiarla"
                />
              </FieldItem>
              <FieldDescription>
                Se guarda en <span className="font-mono">{meta?.home}/config.yaml</span>. Las
                variables de entorno tienen prioridad.
              </FieldDescription>
            </Field>
            <Field>
              <FieldLabel>Base URL</FieldLabel>
              <FieldItem>
                <Input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />
              </FieldItem>
            </Field>
            <Field>
              <FieldLabel>Modelo</FieldLabel>
              <FieldItem>
                <Input value={model} onChange={(event) => setModel(event.target.value)} />
              </FieldItem>
            </Field>
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => void onSaveLlm()}>
                <SaveIcon /> Guardar
              </Button>
              <Button variant="secondary" onClick={() => void onTest()} disabled={testing}>
                <TestTubeDiagonalIcon /> Probar LLM
              </Button>
            </div>
            {testResult ? (
              <div
                className={`rounded-lg border px-3 py-2 text-sm ${
                  testOk ? "border-success/40 bg-success/10" : "border-error/40 bg-error/10"
                }`}
              >
                {testResult}
              </div>
            ) : null}
          </CardPanel>
        </Card>

        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Cadencia y apariencia</CardTitle>
            </CardHeader>
            <CardPanel className="flex flex-col gap-4">
              <Field>
                <FieldLabel>Intervalo del daemon (horas)</FieldLabel>
                <FieldItem className="flex gap-2">
                  <Input
                    type="number"
                    min={1}
                    value={interval}
                    onChange={(event) =>
                      setIntervalHours(Number(event.target.value) || 12)
                    }
                    className="w-28"
                  />
                  <Button
                    variant="outline"
                    onClick={() => void saveSettings({ interval_hours: interval })}
                  >
                    <SaveIcon /> Guardar
                  </Button>
                </FieldItem>
              </Field>
              <label className="flex items-center justify-between gap-3 text-sm">
                <span className="flex items-center gap-2">
                  {theme === "dark" ? <MoonIcon className="size-4" /> : <SunIcon className="size-4" />}
                  Tema oscuro
                </span>
                <Switch
                  checked={theme === "dark"}
                  onCheckedChange={(checked) => setTheme(checked ? "dark" : "light")}
                />
              </label>
            </CardPanel>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Sesiones (doctor)</CardTitle>
              <CardDescription>Verifica que las sesiones de IG/FB sigan válidas.</CardDescription>
              <CardAction>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => void onDoctor()}
                  disabled={doctoring}
                >
                  <StethoscopeIcon /> Chequear
                </Button>
              </CardAction>
            </CardHeader>
            <CardPanel className="flex flex-col gap-2">
              {doctor ? (
                <>
                  <p className="text-xs text-muted-foreground">
                    navegador: {doctor.browser.detail}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(doctor.platforms).map(([name, info]) => (
                      <Badge
                        key={name}
                        variant={info.status === "ok" ? "success" : "warning"}
                        title={info.detail}
                      >
                        {name}: {info.status}
                      </Badge>
                    ))}
                  </div>
                </>
              ) : (
                <p className="text-sm text-muted-foreground">
                  Todavía no chequeaste. El doctor abre el navegador un momento por plataforma.
                </p>
              )}
            </CardPanel>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Rutas</CardTitle>
              <CardDescription>Todo el estado vive en el volumen de Argos.</CardDescription>
            </CardHeader>
            <CardPanel className="flex flex-col gap-2">
              {[
                { label: "home", value: meta?.home },
                { label: "corridas", value: meta?.runs_dir },
                { label: "trabajos", value: meta?.jobs_dir },
              ].map((item) =>
                item.value ? (
                  <div key={item.label} className="flex items-center justify-between gap-2">
                    <span className="font-mono text-xs">
                      {item.label}: {item.value}
                    </span>
                    <Button size="icon" variant="ghost" onClick={() => copy(item.value as string)}>
                      <CopyIcon />
                    </Button>
                  </div>
                ) : null,
              )}
            </CardPanel>
          </Card>
        </div>
      </div>
    </div>
  );
}
