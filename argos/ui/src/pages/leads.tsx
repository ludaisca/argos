import { useEffect, useState } from "react";
import {
  DownloadIcon,
  FileSpreadsheetIcon,
  Loader2Icon,
  PlayIcon,
  RefreshCwIcon,
  StethoscopeIcon,
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { LogConsole } from "@/components/log-console";
import { api } from "@/lib/api";
import { notify, useArgos } from "@/lib/store";
import type { ProcRecord } from "@/lib/types";

interface LeadsRunInfo {
  name: string;
  rows: number;
  csv: boolean;
}

const SAMPLE_TEXT = [
  "Nombre,Correo,Teléfono,Empresa",
  "Char Gipt,chargipt01@gmail.com,,",
  ",,,Hospital Ángeles Puebla",
].join("\n");

const RAMO_VARIANT: Record<string, "success" | "warning" | "error"> = {
  Sí: "success",
  Dudoso: "warning",
  No: "error",
};

export function LeadsTab() {
  const { run, track } = useArgos();
  const [text, setText] = useState(SAMPLE_TEXT);
  const [useGmaps, setUseGmaps] = useState(true);
  const [limit, setLimit] = useState("");
  const [launching, setLaunching] = useState(false);
  const [lotes, setLotes] = useState<LeadsRunInfo[]>([]);
  const [selected, setSelected] = useState("");
  const [rows, setRows] = useState<Array<Record<string, string>>>([]);
  const [refreshing, setRefreshing] = useState(false);
  const leadsRun: ProcRecord | null = run && run.kind === "leads" ? run : null;
  const active = leadsRun?.status === "running";

  const selectLote = async (name: string) => {
    setSelected(name);
    try {
      const data = await api<{ rows: Array<Record<string, string>> }>(
        `/api/leads/runs/${encodeURIComponent(name)}`,
      );
      setRows(data.rows);
    } catch {
      setRows([]);
    }
  };

  const refreshLotes = async (autoSelect = false) => {
    setRefreshing(true);
    try {
      const data = await api<{ runs: LeadsRunInfo[] }>("/api/leads/runs");
      setLotes(data.runs);
      if (autoSelect && data.runs.length > 0) {
        await selectLote(data.runs[0].name);
      } else if (!selected && data.runs.length > 0) {
        await selectLote(data.runs[0].name);
      }
    } catch {
      /* silencioso */
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    void refreshLotes();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (leadsRun && leadsRun.status !== "running") {
      void refreshLotes(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leadsRun?.status, leadsRun?.finished_at]);

  const start = async () => {
    if (!text.trim()) {
      notify("Pegá al menos un lead", "Nombre, Correo, Teléfono y/o Empresa", "warning");
      return;
    }
    setLaunching(true);
    try {
      const record = await api<ProcRecord & { count: number }>("/api/leads/enrich", {
        method: "POST",
        body: {
          text,
          sector: "medico",
          use_gmaps: useGmaps,
          limit: limit ? Number(limit) : null,
        },
      });
      track(record);
      notify("Lote en marcha", `${record.count} leads · mirá la consola`, "info");
    } catch (error) {
      notify(
        "No se pudo iniciar el lote",
        error instanceof Error ? error.message : String(error),
        "error",
      );
    } finally {
      setLaunching(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="font-semibold text-2xl tracking-tight">Personalizada · leads</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Pegá los leads de tu CRM (Nombre, Correo, Teléfono, Empresa) y Argos los enriquece:
          valida el <b>ramo médico</b>, busca Google Maps, Facebook, teléfono, entidad/ciudad,
          tipo de cliente y especialidad — con evidencia y confianza por dato. Todo sin login
          (SearxNG propio + Maps).
        </p>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Leads de entrada</CardTitle>
            <CardDescription>
              CSV/TSV con encabezados o una línea por lead (detecta correo, teléfono y empresa
              por patrón).
            </CardDescription>
            <CardAction>
              <Button
                size="sm"
                variant="outline"
                render={<a href="/api/leads/template" target="_blank" rel="noopener" />}
              >
                <FileSpreadsheetIcon /> Plantilla
              </Button>
            </CardAction>
          </CardHeader>
          <CardPanel className="flex flex-col gap-4">
            <Field>
              <FieldItem>
                <Textarea
                  rows={10}
                  value={text}
                  onChange={(event) => setText(event.target.value)}
                  className="font-mono text-xs"
                  placeholder="Nombre,Correo,Teléfono,Empresa"
                />
              </FieldItem>
              <FieldDescription>Un lead por línea; hasta cientos por lote.</FieldDescription>
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2 text-sm">
                <span className="flex items-center gap-2">
                  <StethoscopeIcon className="size-4" /> Usar Google Maps
                </span>
                <Switch checked={useGmaps} onCheckedChange={(checked) => setUseGmaps(checked)} />
              </label>
              <Field>
                <FieldLabel>Límite (opcional)</FieldLabel>
                <FieldItem>
                  <Input
                    type="number"
                    min={1}
                    value={limit}
                    placeholder="todos"
                    onChange={(event) => setLimit(event.target.value)}
                  />
                </FieldItem>
              </Field>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={() => void start()} disabled={launching || active}>
                {launching || active ? (
                  <Loader2Icon className="animate-spin" />
                ) : (
                  <PlayIcon />
                )}
                {active ? "Procesando…" : "Procesar lote"}
              </Button>
              {useGmaps ? (
                <span className="text-xs text-muted-foreground">
                  Maps agrega ficha/categoría/dirección (más lento); sin él, ~4 búsquedas web por lead.
                </span>
              ) : null}
            </div>
          </CardPanel>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Progreso</CardTitle>
            <CardDescription>
              {leadsRun
                ? `${leadsRun.label} · ${leadsRun.status}`
                : "Sin lote en esta sesión — el historial está abajo."}
            </CardDescription>
            <CardAction>
              <Badge
                variant={
                  active
                    ? "warning"
                    : leadsRun?.status === "ok"
                      ? "success"
                      : leadsRun
                        ? "error"
                        : "outline"
                }
              >
                {leadsRun ? leadsRun.status : "idle"}
              </Badge>
            </CardAction>
          </CardHeader>
          <CardPanel>
            {leadsRun ? (
              <LogConsole log={leadsRun.log} running={active} title={leadsRun.label} />
            ) : (
              <Empty>
                <EmptyHeader>
                  <EmptyMedia variant="icon">
                    <StethoscopeIcon />
                  </EmptyMedia>
                  <EmptyTitle>Todo listo para enriquecer</EmptyTitle>
                  <EmptyDescription>
                    Pegá los leads y dale a “Procesar lote”. Los resultados aparecen abajo con
                    su CSV descargable.
                  </EmptyDescription>
                </EmptyHeader>
              </Empty>
            )}
          </CardPanel>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>
            Resultados {rows.length ? <span className="text-muted-foreground">({rows.length})</span> : null}
          </CardTitle>
          <CardDescription>
            Validación de ramo médico y campos del CRM. Lo que no tiene confianza suficiente
            queda vacío para que lo complete una persona.
          </CardDescription>
          <CardAction className="flex items-center gap-2">
            {lotes.length > 0 ? (
              <Select value={selected} onValueChange={(value) => void selectLote(String(value))}>
                <SelectTrigger className="w-56">
                  <SelectValue placeholder="Elegí un lote…" />
                </SelectTrigger>
                <SelectPopup>
                  {lotes.map((lote) => (
                    <SelectItem key={lote.name} value={lote.name}>
                      {lote.name} · {lote.rows} leads
                    </SelectItem>
                  ))}
                </SelectPopup>
              </Select>
            ) : null}
            <Button
              size="icon"
              variant="outline"
              onClick={() => void refreshLotes()}
              disabled={refreshing}
            >
              <RefreshCwIcon className={refreshing ? "animate-spin" : ""} />
            </Button>
            {selected ? (
              <Button
                size="sm"
                variant="secondary"
                render={
                  <a
                    href={`/api/leads/runs/${encodeURIComponent(selected)}/csv`}
                    target="_blank"
                    rel="noopener"
                  />
                }
              >
                <DownloadIcon /> CSV
              </Button>
            ) : null}
          </CardAction>
        </CardHeader>
        <CardPanel>
          {rows.length === 0 ? (
            <Empty>
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <FileSpreadsheetIcon />
                </EmptyMedia>
                <EmptyTitle>Sin resultados todavía</EmptyTitle>
                <EmptyDescription>
                  Cuando termine un lote, acá ves la tabla enriquecida y su CSV.
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Lead</TableHead>
                    <TableHead>Teléfono</TableHead>
                    <TableHead>Entidad / Ciudad</TableHead>
                    <TableHead>Tipo</TableHead>
                    <TableHead>Especialidad</TableHead>
                    <TableHead>Ramo</TableHead>
                    <TableHead>Conf.</TableHead>
                    <TableHead>Links</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row, index) => (
                    <TableRow key={index}>
                      <TableCell>
                        <div className="font-medium">
                          {row["Nombre"]} {row["Apellido"]}
                          {!row["Nombre"] && !row["Apellido"] ? row["Correo"] || "—" : ""}
                        </div>
                        {row["Correo"] ? (
                          <div className="text-xs text-muted-foreground">{row["Correo"]}</div>
                        ) : null}
                      </TableCell>
                      <TableCell>{row["Teléfono"] || "—"}</TableCell>
                      <TableCell>
                        {row["Entidad"] || row["Ciudad"] ? (
                          <span>
                            {row["Entidad"] || "—"}
                            {row["Ciudad"] ? ` · ${row["Ciudad"]}` : ""}
                          </span>
                        ) : (
                          "—"
                        )}
                      </TableCell>
                      <TableCell>{row["Tipo de cliente"] || "—"}</TableCell>
                      <TableCell>{row["Especialidad"] || "—"}</TableCell>
                      <TableCell>
                        <Badge variant={RAMO_VARIANT[row["Ramo médico"]] ?? "outline"}>
                          {row["Ramo médico"] || "—"}
                        </Badge>
                      </TableCell>
                      <TableCell>{row["Confianza"] || "—"}</TableCell>
                      <TableCell>
                        <div className="flex flex-col gap-0.5 text-xs">
                          {row["Google Maps"] ? (
                            <a
                              href={row["Google Maps"]}
                              target="_blank"
                              rel="noopener"
                              className="text-primary hover:underline"
                            >
                              Google Maps
                            </a>
                          ) : null}
                          {row["Facebook"] ? (
                            <a
                              href={row["Facebook"]}
                              target="_blank"
                              rel="noopener"
                              className="text-primary hover:underline"
                            >
                              Facebook
                            </a>
                          ) : null}
                          {!row["Google Maps"] && !row["Facebook"] ? "—" : null}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardPanel>
      </Card>
    </div>
  );
}
