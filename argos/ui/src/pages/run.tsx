import { useMemo, useState } from "react";
import {
  ActivityIcon,
  Loader2Icon,
  PlayIcon,
  SquareIcon,
  Trash2Icon,
  ZapIcon,
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
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Field, FieldDescription, FieldItem, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectItem,
  SelectPopup,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsPanel, TabsTab } from "@/components/ui/tabs";
import { LogConsole } from "@/components/log-console";
import { useArgos } from "@/lib/store";

export function RunPage() {
  const {
    status,
    run,
    jobs,
    daemon,
    startRun,
    cancelRun,
    startDaemon,
    stopDaemon,
    deleteJob,
  } = useArgos();
  const [source, setSource] = useState("brief");
  const [jobFile, setJobFile] = useState("");
  const [interval, setIntervalHours] = useState(() => {
    const stored = Number(localStorage.getItem("argos_interval"));
    return stored > 0 ? stored : 12;
  });

  const pending = jobs?.pending ?? [];
  const running = run?.status === "running";
  const okCount = useMemo(
    () => (run?.result?.results ?? []).filter((item) => item.status === "ok").length,
    [run],
  );

  const onStart = () => {
    if (source === "job") {
      if (!jobFile) return;
      void startRun("job", jobFile);
    } else {
      void startRun("brief");
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="font-semibold text-2xl tracking-tight">Ejecutar</h1>
        <p className="text-sm text-muted-foreground">
          Corridas puntuales, cola de trabajos y modo continuo (daemon). La consola muestra la
          salida en vivo.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Corrida</CardTitle>
            <CardDescription>Una vez: planifica, recolecta y escribe el informe.</CardDescription>
            <CardAction>
              {run ? (
                <Badge
                  variant={
                    running
                      ? "warning"
                      : run.status === "ok"
                        ? "success"
                        : run.status === "stopped"
                          ? "outline"
                          : "error"
                  }
                >
                  {run.status}
                </Badge>
              ) : (
                <Badge variant="outline">sin corridas</Badge>
              )}
            </CardAction>
          </CardHeader>
          <CardPanel className="flex flex-col gap-4">
            <Tabs value={source} onValueChange={(value) => setSource(String(value))}>
              <TabsList>
                <TabsTab value="brief">Brief actual</TabsTab>
                <TabsTab value="job">Trabajo en cola ({pending.length})</TabsTab>
              </TabsList>
              <TabsPanel value="brief" className="pt-3">
                <p className="text-sm text-muted-foreground">
                  {status?.brief.objective
                    ? status.brief.objective.slice(0, 160)
                    : "No hay brief guardado todavía — creálo en Investigación."}
                </p>
              </TabsPanel>
              <TabsPanel value="job" className="pt-3">
                <Select value={jobFile} onValueChange={(value) => setJobFile(String(value))}>
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Elegí un trabajo pendiente…" />
                  </SelectTrigger>
                  <SelectPopup>
                    {pending.map((job) => (
                      <SelectItem key={job.file} value={job.file}>
                        {job.job ?? job.file}
                      </SelectItem>
                    ))}
                  </SelectPopup>
                </Select>
              </TabsPanel>
            </Tabs>
            <div className="flex flex-wrap gap-2">
              <Button onClick={onStart} disabled={running || (source === "job" && !jobFile)}>
                <PlayIcon /> {running ? "Corriendo…" : "Correr ahora"}
              </Button>
              <Button variant="destructive-outline" onClick={() => void cancelRun()} disabled={!running}>
                <SquareIcon /> Detener
              </Button>
              {run?.result?.run_name ? (
                <Badge variant="info" className="self-center">
                  {run.result.run_name}
                </Badge>
              ) : null}
              {run && !running ? (
                <Badge variant="outline" className="self-center">
                  {okCount}/{run.result?.results?.length ?? 0} objetivos ok
                </Badge>
              ) : null}
            </div>
          </CardPanel>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Daemon</CardTitle>
            <CardDescription>Modo continuo: repite el brief y atiende la cola.</CardDescription>
            <CardAction>
              <Badge variant={daemon?.running ? "info" : "outline"}>
                {daemon?.running ? "on" : "off"}
              </Badge>
            </CardAction>
          </CardHeader>
          <CardPanel className="flex flex-col gap-4">
            <label className="flex items-center justify-between gap-3 text-sm">
              <span className="flex items-center gap-2">
                <ActivityIcon className="size-4" /> Activo
              </span>
              <Switch
                checked={daemon?.running ?? false}
                disabled={!daemon}
                onCheckedChange={(checked) => {
                  if (checked) void startDaemon(interval);
                  else void stopDaemon();
                }}
              />
            </label>
            <Field>
              <FieldLabel>Cadencia (horas)</FieldLabel>
              <FieldItem>
                <Input
                  type="number"
                  min={1}
                  value={interval}
                  onChange={(event) => {
                    const value = Number(event.target.value) || 12;
                    setIntervalHours(value);
                    localStorage.setItem("argos_interval", String(value));
                  }}
                  className="w-28"
                />
              </FieldItem>
              <FieldDescription>
                Los cambios de brief se toman en el próximo ciclo, sin reiniciar.
              </FieldDescription>
            </Field>
            {daemon?.record ? (
              <p className="text-xs text-muted-foreground">
                desde {daemon.record.started_at} · {daemon.record.label}
              </p>
            ) : null}
          </CardPanel>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>
            Cola de trabajos{" "}
            <span className="text-muted-foreground">
              ({jobs?.done.length ?? 0} hechos · {jobs?.failed.length ?? 0} fallidos)
            </span>
          </CardTitle>
          <CardDescription>
            Cada YAML encolado se ejecuta una vez y se archiva. El daemon los toma automáticamente;
            también podés correrlos a mano.
          </CardDescription>
        </CardHeader>
        <CardPanel>
          {pending.length === 0 ? (
            <Empty>
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <ZapIcon />
                </EmptyMedia>
                <EmptyTitle>Cola vacía</EmptyTitle>
                <EmptyDescription>
                  Encolá el brief actual desde Investigación para probar el flujo completo.
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <div className="flex flex-col divide-y">
              {pending.map((job) => (
                <div key={job.file} className="flex items-center justify-between gap-3 py-2.5">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">{job.job ?? job.file}</div>
                    <div className="truncate text-xs text-muted-foreground">
                      {job.error ? `⚠ ${job.error}` : (job.objective ?? "").slice(0, 120)}
                    </div>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => void startRun("job", job.file)}
                      disabled={running}
                    >
                      <PlayIcon /> Correr
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      onClick={() => void deleteJob(job.file)}
                    >
                      <Trash2Icon />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardPanel>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Consola</CardTitle>
          <CardDescription>
            Salida del proceso {run?.label ? `“${run.label}”` : "del daemon"} en vivo.
          </CardDescription>
        </CardHeader>
        <CardPanel>
          {run ? (
            <LogConsole log={run.log} running={running} title={run.label} />
          ) : daemon?.record ? (
            <LogConsole log={daemon.record.log} running={daemon.running} title={daemon.record.label} />
          ) : (
            <Empty>
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <Loader2Icon />
                </EmptyMedia>
                <EmptyTitle>Sin actividad</EmptyTitle>
                <EmptyDescription>Lanzá una corrida o prendé el daemon para ver la salida.</EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}
        </CardPanel>
      </Card>
    </div>
  );
}
