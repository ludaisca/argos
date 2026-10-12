import { useMemo, useState } from "react";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  ExternalLinkIcon,
  Loader2Icon,
  MapPinIcon,
  SaveIcon,
  SearchIcon,
  StarIcon,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardPanel, CardTitle } from "@/components/ui/card";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Field, FieldItem, FieldLabel } from "@/components/ui/field";
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
import { useArgos } from "@/lib/store";
import type { Place, PlacesSearchResult } from "@/lib/types";

type SortKey = "name" | "rating" | "distance_km";

const PROVIDERS = [
  { value: "osm", label: "OpenStreetMap · gratis" },
  { value: "gmaps", label: "Google Maps · scraping" },
];

export function PlacesPage() {
  const { searchPlaces, savePlaces, meta } = useArgos();
  const [query, setQuery] = useState("");
  const [location, setLocation] = useState("");
  const [radius, setRadius] = useState(3);
  const [limit, setLimit] = useState(25);
  const [provider, setProvider] = useState("osm");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PlacesSearchResult | null>(null);
  const [sort, setSort] = useState<SortKey>("distance_km");
  const [sortAsc, setSortAsc] = useState(true);
  const [saving, setSaving] = useState(false);

  const places = useMemo(() => {
    const list = [...(result?.places ?? [])];
    list.sort((a, b) => {
      const left = a[sort];
      const right = b[sort];
      if (left == null && right == null) return 0;
      if (left == null) return 1;
      if (right == null) return -1;
      if (typeof left === "string" || typeof right === "string") {
        return String(left).localeCompare(String(right));
      }
      return (left as number) - (right as number);
    });
    if (!sortAsc) list.reverse();
    return list;
  }, [result, sort, sortAsc]);

  const onSearch = async () => {
    if (!query.trim()) return;
    setBusy(true);
    try {
      const data = await searchPlaces({
        query: query.trim(),
        location: location.trim() || null,
        radius_km: radius,
        limit,
        provider,
      });
      setResult(data);
    } finally {
      setBusy(false);
    }
  };

  const onSave = async () => {
    if (!result?.places.length) return;
    setSaving(true);
    try {
      await savePlaces({
        query: query.trim(),
        location: location.trim() || null,
        provider,
        places: result.places,
        center: result.center,
      });
    } finally {
      setSaving(false);
    }
  };

  const toggleSort = (key: SortKey) => {
    if (sort === key) setSortAsc((value) => !value);
    else {
      setSort(key);
      setSortAsc(true);
    }
  };

  const mapHref = result?.center
    ? `https://www.openstreetmap.org/#map=14/${result.center.lat}/${result.center.lon}`
    : `https://www.google.com/maps/search/${encodeURIComponent(
        [query, location].filter(Boolean).join(" "),
      )}`;

  const sortIcon = (key: SortKey) =>
    sort === key ? (
      sortAsc ? (
        <ArrowUpIcon className="size-3" />
      ) : (
        <ArrowDownIcon className="size-3" />
      )
    ) : null;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="font-semibold text-2xl tracking-tight">Lugares</h1>
        <p className="text-sm text-muted-foreground">
          Búsqueda de lugares sin costo: OpenStreetMap (sin API key, con respaldo automático) o
          Google Maps por scraping (incluye rating).
        </p>
      </div>

      <Card>
        <CardPanel className="flex flex-col gap-4">
          <div className="grid gap-3 lg:grid-cols-12">
            <div className="lg:col-span-4">
              <Field>
                <FieldLabel>Qué buscás</FieldLabel>
                <FieldItem>
                  <Input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") void onSearch();
                    }}
                    placeholder="restaurantes · cafeterías · farmacias · nombre del negocio"
                  />
                </FieldItem>
              </Field>
            </div>
            <div className="lg:col-span-4">
              <Field>
                <FieldLabel>Dónde</FieldLabel>
                <FieldItem>
                  <Input
                    value={location}
                    onChange={(event) => setLocation(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") void onSearch();
                    }}
                    placeholder="Puebla, MX — vacío = buscar por nombre"
                  />
                </FieldItem>
              </Field>
            </div>
            <div className="lg:col-span-1">
              <Field>
                <FieldLabel>Km</FieldLabel>
                <FieldItem>
                  <Input
                    type="number"
                    min={0.5}
                    step={0.5}
                    value={radius}
                    onChange={(event) => setRadius(Number(event.target.value) || 3)}
                  />
                </FieldItem>
              </Field>
            </div>
            <div className="lg:col-span-1">
              <Field>
                <FieldLabel>Máx</FieldLabel>
                <FieldItem>
                  <Input
                    type="number"
                    min={1}
                    max={100}
                    value={limit}
                    onChange={(event) => setLimit(Number(event.target.value) || 25)}
                  />
                </FieldItem>
              </Field>
            </div>
            <div className="lg:col-span-2">
              <Field>
                <FieldLabel>Proveedor</FieldLabel>
                <FieldItem>
                  <Select value={provider} onValueChange={(value) => setProvider(String(value))}>
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectPopup>
                      {PROVIDERS.map((item) => (
                        <SelectItem key={item.value} value={item.value}>
                          {item.label}
                        </SelectItem>
                      ))}
                    </SelectPopup>
                  </Select>
                </FieldItem>
              </Field>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => void onSearch()} disabled={busy || !query.trim()}>
              {busy ? <Loader2Icon className="animate-spin" /> : <SearchIcon />} Buscar
            </Button>
            <Button
              variant="outline"
              render={<a href={mapHref} target="_blank" rel="noopener" />}
            >
              <MapPinIcon /> Ver en el mapa
            </Button>
            {result?.places.length ? (
              <Button variant="secondary" onClick={() => void onSave()} disabled={saving}>
                {saving ? <Loader2Icon className="animate-spin" /> : <SaveIcon />} Guardar como corrida
              </Button>
            ) : null}
            {result ? (
              <span className="text-xs text-muted-foreground">{result.detail}</span>
            ) : null}
          </div>
        </CardPanel>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>
            Resultados {result ? <span className="text-muted-foreground">({result.places.length})</span> : null}
          </CardTitle>
          <CardDescription>
            Datos de {provider === "osm" ? "OpenStreetMap" : "Google Maps"}. Clic en el nombre para
            abrirlo en el mapa original.
          </CardDescription>
        </CardHeader>
        <CardPanel>
          {!result ? (
            <Empty>
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <SearchIcon />
                </EmptyMedia>
                <EmptyTitle>Sin búsquedas todavía</EmptyTitle>
                <EmptyDescription>
                  Probá “cafeterías” en “Puebla, MX”, o encolá lugares como objetivo
                  (<span className="font-mono text-xs">places_search</span>) en una investigación.
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : places.length === 0 ? (
            <Empty>
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <MapPinIcon />
                </EmptyMedia>
                <EmptyTitle>Sin resultados</EmptyTitle>
                <EmptyDescription>Probá otra categoría, otra zona o un radio más amplio.</EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>
                      <button
                        type="button"
                        className="inline-flex items-center gap-1"
                        onClick={() => toggleSort("name")}
                      >
                        Nombre {sortIcon("name")}
                      </button>
                    </TableHead>
                    <TableHead>Categoría</TableHead>
                    <TableHead>Dirección</TableHead>
                    <TableHead>Teléfono</TableHead>
                    <TableHead>Web</TableHead>
                    <TableHead>Horario</TableHead>
                    <TableHead>
                      <button
                        type="button"
                        className="inline-flex items-center gap-1"
                        onClick={() => toggleSort("rating")}
                      >
                        Rating {sortIcon("rating")}
                      </button>
                    </TableHead>
                    <TableHead>
                      <button
                        type="button"
                        className="inline-flex items-center gap-1"
                        onClick={() => toggleSort("distance_km")}
                      >
                        Dist. {sortIcon("distance_km")}
                      </button>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {places.map((place: Place) => (
                    <TableRow key={`${place.source}-${place.id}`}>
                      <TableCell className="font-medium">
                        {place.url ? (
                          <a
                            href={place.url}
                            target="_blank"
                            rel="noopener"
                            className="inline-flex items-center gap-1 text-primary hover:underline"
                          >
                            {place.name}
                            <ExternalLinkIcon className="size-3" />
                          </a>
                        ) : (
                          place.name
                        )}
                      </TableCell>
                      <TableCell>{place.category ?? "—"}</TableCell>
                      <TableCell className="max-w-56 truncate">{place.address ?? "—"}</TableCell>
                      <TableCell>{place.phone ?? "—"}</TableCell>
                      <TableCell>
                        {place.website ? (
                          <a
                            href={place.website}
                            target="_blank"
                            rel="noopener"
                            className="text-primary hover:underline"
                          >
                            web
                          </a>
                        ) : (
                          "—"
                        )}
                      </TableCell>
                      <TableCell className="max-w-44 truncate">{place.opening_hours ?? "—"}</TableCell>
                      <TableCell>
                        {place.rating ? (
                          <Badge variant="warning">
                            <StarIcon className="size-3 fill-current" />
                            {place.rating}
                            {place.reviews ? ` (${place.reviews})` : ""}
                          </Badge>
                        ) : (
                          "—"
                        )}
                      </TableCell>
                      <TableCell>
                        {place.distance_km != null ? `${place.distance_km} km` : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardPanel>
      </Card>

      <p className="text-xs text-muted-foreground">
        Tip: con el tipo <span className="font-mono">places_search</span> en Investigación, el
        planner del LLM y la cola de trabajos pueden investigar lugares igual que FB/IG —{" "}
        {meta?.platform_labels.places}.
      </p>
    </div>
  );
}
