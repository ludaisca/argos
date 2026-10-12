import {
  ActivityIcon,
  ArrowRightIcon,
  BookOpenIcon,
  MapPinIcon,
  SparklesIcon,
  TriangleAlertIcon,
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
import { QuotaGauge } from "@/components/quota-chart";
import { useArgos } from "@/lib/store";

const PLATFORM_ACCENTS: Record<string, string> = {
  instagram: "var(--chart-1)",
  facebook: "var(--chart-2)",
  places: "var(--chart-3)",
};

export function DashboardPage() {
  const { status, runs, daemon, setSection, startRun, selectRun, meta } = useArgos();
  const llm = status?.llm;
  const quota = status?.quota ?? {};
  const sessions = status?.sessions ?? {};

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-semibold text-2xl tracking-tight">Estado</h1>
          <p className="text-sm text-muted-foreground">
            Todo lo que está pasando en tu Argos, de un vistazo.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setSection("places")}>
            <MapPinIcon /> Buscar lugares
          </Button>
          <Button onClick={() => startRun("brief")} disabled={status?.busy}>
            <ZapIcon /> Correr ahora
          </Button>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Proveedor LLM</CardTitle>
            <CardAction>
              <SparklesIcon className="size-4 text-muted-foreground" />
            </CardAction>
          </CardHeader>
          <CardPanel>
            {llm?.llm_configured ? (
              <div className="flex flex-col gap-2">
                <Badge variant="success" className="w-fit">
                  {llm.llm_model}
                </Badge>
                <p className="truncate text-xs text-muted-foreground">{llm.llm_base_url}</p>
                <p className="text-xs text-muted-foreground">
                  key {llm.llm_key_masked} ({llm.llm_key_source})
                </p>
              </div>
            ) : (
              <div className="flex flex-col items-start gap-2">
                <Badge variant="error" className="w-fit">
                  <TriangleAlertIcon className="size-3" /> sin configurar
                </Badge>
                <Button size="sm" variant="outline" onClick={() => setSection("settings")}>
                  Configurar
                </Button>
              </div>
            )}
          </CardPanel>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Sesiones</CardTitle>
            <CardAction>
              <ActivityIcon className="size-4 text-muted-foreground" />
            </CardAction>
          </CardHeader>
          <CardPanel>
            <div className="flex flex-wrap gap-2">
              {Object.entries(sessions).map(([platform, info]) => (
                <Badge
                  key={platform}
                  variant={info.cookies > 0 || info.profile ? "success" : "warning"}
                >
                  {platform}: {info.cookies > 0 ? `${info.cookies} cookies` : "perfil"}
                </Badge>
              ))}
            </div>
          </CardPanel>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Daemon</CardTitle>
            <CardAction>
              <Badge variant={daemon?.running ? "info" : "outline"}>
                {daemon?.running ? "corriendo" : "detenido"}
              </Badge>
            </CardAction>
          </CardHeader>
          <CardPanel>
            <p className="text-xs text-muted-foreground">
              Revisa la cola de trabajos cada pocos minutos y repite el brief cada{" "}
              {status?.interval_hours ?? 12} h.
            </p>
            <Button size="sm" variant="outline" className="mt-2" onClick={() => setSection("run")}>
              Ir a Ejecutar <ArrowRightIcon />
            </Button>
          </CardPanel>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Cola de trabajos</CardTitle>
            <CardAction>
              <BookOpenIcon className="size-4 text-muted-foreground" />
            </CardAction>
          </CardHeader>
          <CardPanel>
            <div className="flex gap-3 text-sm">
              <span>
                <span className="font-semibold">{status?.jobs.pending ?? 0}</span>{" "}
                <span className="text-muted-foreground">pendientes</span>
              </span>
              <span>
                <span className="font-semibold text-success-foreground">
                  {status?.jobs.done ?? 0}
                </span>{" "}
                <span className="text-muted-foreground">hechos</span>
              </span>
              <span>
                <span className="font-semibold text-destructive-foreground">
                  {status?.jobs.failed ?? 0}
                </span>{" "}
                <span className="text-muted-foreground">fallidos</span>
              </span>
            </div>
          </CardPanel>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle>Actividad reciente</CardTitle>
            <CardDescription>
              Las últimas corridas, con su informe cuando está listo.
            </CardDescription>
            <CardAction>
              <Button size="sm" variant="ghost" onClick={() => setSection("results")}>
                Ver todas
              </Button>
            </CardAction>
          </CardHeader>
          <CardPanel>
            {runs.length === 0 ? (
              <Empty>
                <EmptyHeader>
                  <EmptyMedia variant="icon">
                    <BookOpenIcon />
                  </EmptyMedia>
                  <EmptyTitle>Todavía no hay corridas</EmptyTitle>
                  <EmptyDescription>
                    Guardá un brief en Investigación y dale a “Correr ahora”.
                  </EmptyDescription>
                </EmptyHeader>
              </Empty>
            ) : (
              <div className="flex flex-col divide-y">
                {runs.slice(0, 6).map((item) => (
                  <button
                    key={item.name}
                    type="button"
                    onClick={() => {
                      setSection("results");
                      void selectRun(item.name);
                    }}
                    className="flex items-center justify-between gap-3 py-2.5 text-left transition-colors hover:bg-accent/40"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">{item.job}</div>
                      <div className="truncate text-xs text-muted-foreground">
                        {item.name} · plan {item.plan_source ?? "?"}
                        {item.generated_at ? ` · ${item.generated_at.replace("T", " ").slice(0, 16)}` : ""}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      {item.analysis ? <Badge variant="info">informe</Badge> : null}
                      <Badge variant={item.total > 0 && item.ok === item.total ? "success" : "outline"}>
                        {item.ok}/{item.total} ok
                      </Badge>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </CardPanel>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Cuota de hoy</CardTitle>
            <CardDescription>Límites diarios por plataforma (se resetean cada día).</CardDescription>
          </CardHeader>
          <CardPanel className="flex flex-col gap-4">
            {Object.entries(quota).map(([platform, info]) => (
              <QuotaGauge
                key={platform}
                label={platform}
                used={info.used}
                limit={info.daily_limit}
                accent={PLATFORM_ACCENTS[platform] ?? "var(--chart-1)"}
              />
            ))}
            <div className="text-xs text-muted-foreground">
              Estado en <span className="font-mono">{meta?.home}</span>
            </div>
          </CardPanel>
        </Card>
      </div>
    </div>
  );
}
