import { useEffect } from "react";
import { DownloadIcon, FileTextIcon, TelescopeIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardPanel, CardTitle } from "@/components/ui/card";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { MarkdownView } from "@/components/markdown-view";
import { fileUrl } from "@/lib/api";
import { formatBytes } from "@/lib/markdown";
import { useArgos } from "@/lib/store";

export function ResultsPage() {
  const { runs, selectedRun, runDetail, selectRun, refreshRuns } = useArgos();

  useEffect(() => {
    void refreshRuns();
  }, [refreshRuns]);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="font-semibold text-2xl tracking-tight">Resultados</h1>
        <p className="text-sm text-muted-foreground">
          Informes del LLM, datos crudos (JSONL/CSV/SQLite) y planes, listos para descargar.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Corridas</CardTitle>
            <CardDescription>{runs.length} en total</CardDescription>
          </CardHeader>
          <CardPanel className="max-h-150 overflow-y-auto p-2">
            {runs.length === 0 ? (
              <p className="p-3 text-sm text-muted-foreground">Sin corridas todavía.</p>
            ) : (
              <div className="flex flex-col gap-1">
                {runs.map((item) => (
                  <button
                    key={item.name}
                    type="button"
                    onClick={() => void selectRun(item.name)}
                    className={`flex w-full flex-col gap-1 rounded-lg border px-3 py-2 text-left transition-colors ${
                      selectedRun === item.name
                        ? "border-primary/50 bg-accent"
                        : "border-transparent hover:bg-accent/50"
                    }`}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-medium">{item.job}</span>
                      <Badge
                        variant={item.total > 0 && item.ok === item.total ? "success" : "outline"}
                      >
                        {item.ok}/{item.total}
                      </Badge>
                    </span>
                    <span className="flex items-center gap-2 text-xs text-muted-foreground">
                      <span className="truncate">{item.name}</span>
                      {item.analysis ? <Badge variant="info">informe</Badge> : null}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </CardPanel>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{runDetail ? (runDetail.meta.job ?? runDetail.name) : "Detalle"}</CardTitle>
            <CardDescription>
              {runDetail
                ? `${runDetail.name} · plan ${runDetail.meta.plan_source ?? "?"} · ${
                    runDetail.meta.generated_at?.replace("T", " ").slice(0, 16) ?? ""
                  }`
                : "Elegí una corrida de la izquierda."}
            </CardDescription>
          </CardHeader>
          <CardPanel>
            {!runDetail ? (
              <Empty>
                <EmptyHeader>
                  <EmptyMedia variant="icon">
                    <TelescopeIcon />
                  </EmptyMedia>
                  <EmptyTitle>Nada seleccionado</EmptyTitle>
                  <EmptyDescription>
                    Los informes aparecen acá cuando termina una corrida.
                  </EmptyDescription>
                </EmptyHeader>
              </Empty>
            ) : (
              <div className="flex flex-col gap-4">
                {runDetail.meta.objective ? (
                  <p className="text-sm text-muted-foreground">{runDetail.meta.objective}</p>
                ) : null}
                {runDetail.meta.results && runDetail.meta.results.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {runDetail.meta.results.map((result, index) => (
                      <Badge
                        key={index}
                        variant={result.status === "ok" ? "success" : "error"}
                      >
                        {result.target}: {result.status}
                      </Badge>
                    ))}
                  </div>
                ) : null}
                {runDetail.analysis ? (
                  <MarkdownView source={runDetail.analysis} />
                ) : (
                  <p className="text-sm text-muted-foreground">
                    (sin analysis.md — ¿falló el análisis?)
                  </p>
                )}
                {runDetail.files.length > 0 ? (
                  <div className="flex flex-col gap-2">
                    <div className="flex items-center gap-2 text-sm font-medium">
                      <FileTextIcon className="size-4" /> Archivos
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {runDetail.files.map((file) => (
                        <Button
                          key={file.path}
                          variant="outline"
                          size="sm"
                          render={
                            <a
                              href={fileUrl(runDetail.name, file.path)}
                              target="_blank"
                              rel="noopener"
                            />
                          }
                        >
                          <DownloadIcon />
                          <span className="font-mono text-xs">{file.path}</span>
                          <span className="text-muted-foreground">{formatBytes(file.size)}</span>
                        </Button>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            )}
          </CardPanel>
        </Card>
      </div>
    </div>
  );
}
