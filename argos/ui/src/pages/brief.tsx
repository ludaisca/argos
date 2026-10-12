import { useEffect, useMemo, useState } from "react";
import {
  BrainCircuitIcon,
  ListPlusIcon,
  Loader2Icon,
  PlusIcon,
  SaveIcon,
  SparklesIcon,
  Trash2Icon,
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
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogPopup,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldItem, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectItem,
  SelectPopup,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { useArgos } from "@/lib/store";
import type { Target } from "@/lib/types";

const TYPE_HINTS: Record<string, string> = {
  places_search: "qué buscar (ej: restaurantes)",
};

function typeOptionsFor(platforms: string[], platform: string, targetTypes: Record<string, string[]>) {
  const types: string[] = [];
  for (const p of platforms) types.push(...(targetTypes[p] ?? []));
  return types;
}

export function BriefPage() {
  const { meta, brief, saveBrief, requestPlan, queueJob } = useArgos();
  const [job, setJob] = useState("");
  const [objective, setObjective] = useState("");
  const [questions, setQuestions] = useState("");
  const [maxTargets, setMaxTargets] = useState(6);
  const [platforms, setPlatforms] = useState<string[]>([]);
  const [targets, setTargets] = useState<Target[]>([]);
  const [planOpen, setPlanOpen] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [plan, setPlan] = useState<Target[] | null>(null);

  useEffect(() => {
    if (!brief) return;
    setJob(brief.job);
    setObjective(brief.objective);
    setQuestions(brief.questions.join("\n"));
    setMaxTargets(brief.max_targets);
    setPlatforms(brief.platforms);
    setTargets(brief.targets);
  }, [brief]);

  const allTypes = useMemo(
    () => typeOptionsFor(platforms, "", meta?.target_types ?? {}),
    [platforms, meta],
  );

  const payload = () => ({
    job: job.trim() || "research",
    objective: objective.trim(),
    questions: questions
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean),
    platforms,
    targets: targets.filter((target) => target.value || target.type === "fb_groups_feed"),
    max_targets: maxTargets,
  });

  const onSave = async () => {
    if (!objective.trim()) return;
    await saveBrief(payload());
  };

  const onQueue = async () => {
    if (!objective.trim()) return;
    await queueJob({ ...payload(), overwrite: true });
  };

  const onPlan = async () => {
    setPlanOpen(true);
    setPlanning(true);
    setPlan(null);
    try {
      setPlan(await requestPlan());
    } catch {
      setPlan([]);
    } finally {
      setPlanning(false);
    }
  };

  const updateTarget = (index: number, patch: Partial<Target>) => {
    setTargets((current) =>
      current.map((target, position) => (position === index ? { ...target, ...patch } : target)),
    );
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-semibold text-2xl tracking-tight">Investigación</h1>
          <p className="text-sm text-muted-foreground">
            Definí el objetivo, las plataformas y (si querés) los objetivos de recolección.
            El daemon y el contenedor leen este mismo brief.
          </p>
        </div>
        {brief?.source ? (
          <Badge variant="outline">
            fuente: {brief.source === "home" ? "volumen (brief.yaml)" : brief.source}
          </Badge>
        ) : null}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Objetivo</CardTitle>
            <CardDescription>Qué querés averiguar, en tus palabras.</CardDescription>
          </CardHeader>
          <CardPanel className="flex flex-col gap-4">
            <Field>
              <FieldLabel>Nombre</FieldLabel>
              <FieldItem>
                <Input
                  value={job}
                  onChange={(event) => setJob(event.target.value)}
                  placeholder="mi-investigacion"
                />
              </FieldItem>
            </Field>
            <Field>
              <FieldLabel>Qué querés averiguar</FieldLabel>
              <FieldItem>
                <Textarea
                  rows={6}
                  value={objective}
                  onChange={(event) => setObjective(event.target.value)}
                  placeholder="Ej: investigar cómo se habla de DeepSeek en Instagram y Facebook: cuentas relevantes y temas dominantes."
                />
              </FieldItem>
            </Field>
            <Field>
              <FieldLabel>Preguntas (una por línea)</FieldLabel>
              <FieldItem>
                <Textarea
                  rows={4}
                  value={questions}
                  onChange={(event) => setQuestions(event.target.value)}
                  placeholder={"¿Qué cuentas/páginas tienen más alcance?\n¿Qué temas aparecen en los comentarios?"}
                />
              </FieldItem>
            </Field>
            <Field>
              <FieldLabel>Dónde buscar</FieldLabel>
              <FieldItem className="flex flex-wrap gap-4">
                {(meta?.platforms ?? []).map((platform) => (
                  <label key={platform} className="flex items-center gap-2 text-sm">
                    <Checkbox
                      checked={platforms.includes(platform)}
                      onCheckedChange={(checked) => {
                        setPlatforms((current) => {
                          const next = checked
                            ? [...current, platform]
                            : current.filter((item) => item !== platform);
                          return next.length > 0 ? next : current;
                        });
                      }}
                    />
                    {meta?.platform_labels[platform] ?? platform}
                  </label>
                ))}
              </FieldItem>
              <FieldDescription>
                Al sumar fuentes nuevas aparecen acá solas.
              </FieldDescription>
            </Field>
            <Field>
              <FieldLabel>Máximo de objetivos por corrida</FieldLabel>
              <FieldItem>
                <Input
                  type="number"
                  min={1}
                  max={meta?.max_targets_cap ?? 12}
                  value={maxTargets}
                  onChange={(event) => setMaxTargets(Number(event.target.value) || 6)}
                  className="w-28"
                />
              </FieldItem>
            </Field>
          </CardPanel>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Objetivos de la corrida</CardTitle>
            <CardDescription>
              Vacío = el LLM los propone a partir del objetivo. Podés fijarlos a mano.
            </CardDescription>
          </CardHeader>
          <CardPanel className="flex flex-col gap-3">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Tipo</TableHead>
                  <TableHead>Valor</TableHead>
                  <TableHead className="w-20">Límite</TableHead>
                  <TableHead>Kind / zona</TableHead>
                  <TableHead className="w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {targets.map((target, index) => {
                  const kinds = meta?.kinds[target.type] ?? [];
                  const isPlaces = target.type === "places_search";
                  return (
                    <TableRow key={index}>
                      <TableCell className="min-w-36">
                        <Select
                          value={target.type}
                          onValueChange={(value) =>
                            updateTarget(index, { type: String(value), kind: undefined })
                          }
                        >
                          <SelectTrigger className="w-full">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectPopup>
                            {allTypes.map((type) => (
                              <SelectItem key={type} value={type}>
                                {type}
                              </SelectItem>
                            ))}
                          </SelectPopup>
                        </Select>
                      </TableCell>
                      <TableCell>
                        <Input
                          value={target.value ?? ""}
                          placeholder={TYPE_HINTS[target.type] ?? "usuario / etiqueta / término"}
                          onChange={(event) => updateTarget(index, { value: event.target.value })}
                        />
                      </TableCell>
                      <TableCell>
                        <Input
                          type="number"
                          min={1}
                          max={meta?.target_limit_cap ?? 20}
                          value={target.limit ?? 12}
                          onChange={(event) =>
                            updateTarget(index, { limit: Number(event.target.value) || 12 })
                          }
                        />
                      </TableCell>
                      <TableCell className="min-w-40">
                        {isPlaces ? (
                          <Input
                            value={target.kind ?? ""}
                            placeholder="zona (ej: Puebla, MX)"
                            onChange={(event) => updateTarget(index, { kind: event.target.value })}
                          />
                        ) : kinds.length > 0 ? (
                          <Select
                            value={target.kind ?? ""}
                            onValueChange={(value) =>
                              updateTarget(index, { kind: value ? String(value) : undefined })
                            }
                          >
                            <SelectTrigger className="w-full">
                              <SelectValue placeholder="—" />
                            </SelectTrigger>
                            <SelectPopup>
                              {kinds.map((kind) => (
                                <SelectItem key={kind} value={kind}>
                                  {kind}
                                </SelectItem>
                              ))}
                            </SelectPopup>
                          </Select>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() =>
                            setTargets((current) => current.filter((_, position) => position !== index))
                          }
                        >
                          <Trash2Icon />
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
            <div>
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  setTargets((current) => [
                    ...current,
                    { type: allTypes[0] ?? "ig_profile", value: "", limit: 12 },
                  ])
                }
              >
                <PlusIcon /> Agregar objetivo
              </Button>
            </div>
          </CardPanel>
          <CardPanel className="flex flex-wrap gap-2 border-t">
            <Button onClick={() => void onSave()} disabled={!objective.trim()}>
              <SaveIcon /> Guardar brief
            </Button>
            <Button variant="secondary" onClick={() => void onPlan()} disabled={!objective.trim()}>
              <BrainCircuitIcon /> Ver plan del LLM
            </Button>
            <Button variant="outline" onClick={() => void onQueue()} disabled={!objective.trim()}>
              <ListPlusIcon /> Encolar como trabajo
            </Button>
          </CardPanel>
        </Card>
      </div>

      <Dialog open={planOpen} onOpenChange={setPlanOpen}>
        <DialogPopup>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <SparklesIcon className="size-4" /> Plan propuesto por el LLM
            </DialogTitle>
            <DialogDescription>
              Esto es lo que recolectaría el agente con el brief actual (no gasta acciones).
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2 px-6 pb-2">
            {planning ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2Icon className="size-4 animate-spin" /> Consultando al modelo…
              </div>
            ) : plan && plan.length > 0 ? (
              plan.map((target, index) => (
                <div
                  key={index}
                  className="flex items-center justify-between rounded-lg border bg-muted/30 px-3 py-2 text-sm"
                >
                  <span className="font-mono text-xs">{target.type}</span>
                  <span className="truncate px-3">{target.value ?? "(feed)"}</span>
                  <Badge variant="outline">límite {target.limit}</Badge>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">
                No se pudo obtener un plan (¿LLM configurado?). Probá de nuevo en un momento.
              </p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPlanOpen(false)}>
              Cerrar
            </Button>
          </DialogFooter>
        </DialogPopup>
      </Dialog>
    </div>
  );
}
