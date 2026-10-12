import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { toastManager } from "@/components/ui/toast";
import { api } from "@/lib/api";
import type {
  Brief,
  DoctorResult,
  JobEntry,
  JobsPayload,
  Meta,
  PlacesSearchResult,
  ProcRecord,
  RunDetail,
  RunSummary,
  Section,
  Settings,
  StatusPayload,
  Target,
} from "@/lib/types";

type ToastKind = "success" | "error" | "info" | "warning";

function notify(title: string, description?: string, type: ToastKind = "success") {
  toastManager.add({ title, description, type });
}

function fail(title: string, error: unknown) {
  const description = error instanceof Error ? error.message : String(error);
  toastManager.add({ title, description, type: "error" });
}

interface ArgosContextValue {
  meta: Meta | null;
  status: StatusPayload | null;
  settings: Settings | null;
  brief: Brief | null;
  runs: RunSummary[];
  jobs: JobsPayload | null;
  daemon: { running: boolean; record: ProcRecord | null } | null;
  run: ProcRecord | null;
  runDetail: RunDetail | null;
  selectedRun: string | null;
  section: Section;
  setSection: (section: Section) => void;
  refresh: () => Promise<void>;
  saveBrief: (payload: Omit<Brief, "source">) => Promise<void>;
  requestPlan: () => Promise<Target[]>;
  startRun: (source: "brief" | "job", job?: string) => Promise<void>;
  cancelRun: () => Promise<void>;
  startDaemon: (intervalHours: number) => Promise<void>;
  stopDaemon: () => Promise<void>;
  queueJob: (payload: Omit<Brief, "source"> & { overwrite?: boolean }) => Promise<void>;
  deleteJob: (file: string) => Promise<void>;
  searchPlaces: (payload: {
    query: string;
    location?: string | null;
    radius_km?: number;
    limit?: number;
    provider?: string;
  }) => Promise<PlacesSearchResult>;
  savePlaces: (payload: {
    query: string;
    location?: string | null;
    provider?: string;
    places: unknown[];
    center?: unknown;
  }) => Promise<string>;
  saveSettings: (payload: {
    llm_api_key?: string;
    llm_base_url?: string;
    llm_model?: string;
    interval_hours?: number;
  }) => Promise<void>;
  testLlm: () => Promise<{ ok: boolean; model?: string; reply?: string; error?: string }>;
  runDoctor: () => Promise<DoctorResult>;
  selectRun: (name: string) => Promise<void>;
  refreshRuns: () => Promise<void>;
  track: (record: ProcRecord) => void;
}

const ArgosContext = createContext<ArgosContextValue | null>(null);

export function useArgos(): ArgosContextValue {
  const value = useContext(ArgosContext);
  if (!value) throw new Error("useArgos debe usarse dentro de <ArgosProvider>");
  return value;
}

export function ArgosProvider({ children }: { children: ReactNode }) {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [status, setStatus] = useState<StatusPayload | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [brief, setBrief] = useState<Brief | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [jobs, setJobs] = useState<JobsPayload | null>(null);
  const [daemon, setDaemon] = useState<{ running: boolean; record: ProcRecord | null } | null>(null);
  const [run, setRun] = useState<ProcRecord | null>(null);
  const [runDetail, setRunDetail] = useState<RunDetail | null>(null);
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [section, setSection] = useState<Section>("dashboard");
  const runRef = useRef<ProcRecord | null>(null);
  runRef.current = run;

  const refreshRuns = useCallback(async () => {
    try {
      const data = await api<{ runs: RunSummary[] }>("/api/runs");
      setRuns(data.runs);
    } catch {
      /* silencioso: el poll reintenta */
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [statusData, daemonData, jobsData] = await Promise.all([
        api<StatusPayload>("/api/status"),
        api<{ running: boolean; record: ProcRecord | null }>("/api/daemon"),
        api<JobsPayload>("/api/jobs"),
      ]);
      setStatus(statusData);
      setDaemon(daemonData);
      setJobs(jobsData);
      const current = runRef.current;
      if (current && current.status === "running") {
        const record = await api<ProcRecord>(`/api/run/${current.id}`);
        setRun(record);
        if (record.status !== "running") {
          void refreshRuns();
          const okCount = (record.result?.results ?? []).filter((item) => item.status === "ok").length;
          if (record.status === "ok") {
            notify(
              "Corrida terminada",
              `${okCount}/${record.result?.results?.length ?? 0} objetivos ok`,
              "success",
            );
          } else if (record.status === "error") {
            notify("La corrida falló", "Mirá la consola en Ejecutar", "error");
          }
        }
      }
    } catch {
      /* servidor caído: reintenta */
    }
  }, [refreshRuns]);

  const loadInitial = useCallback(async () => {
    try {
      const [metaData, statusData, settingsData, briefData, daemonData, jobsData] =
        await Promise.all([
          api<Meta>("/api/meta"),
          api<StatusPayload>("/api/status"),
          api<Settings>("/api/settings"),
          api<Brief>("/api/brief"),
          api<{ running: boolean; record: ProcRecord | null }>("/api/daemon"),
          api<JobsPayload>("/api/jobs"),
        ]);
      setMeta(metaData);
      setStatus(statusData);
      setSettings(settingsData);
      setBrief({
        source: briefData.source,
        job: briefData.job ?? "research",
        objective: briefData.objective ?? "",
        questions: briefData.questions ?? [],
        targets: briefData.targets ?? [],
        max_targets: briefData.max_targets ?? 6,
        platforms: briefData.platforms ?? metaData.platforms,
      });
      setDaemon(daemonData);
      setJobs(jobsData);
      void refreshRuns();
    } catch (error) {
      fail("No se pudo hablar con el servidor", error);
    }
  }, [refreshRuns]);

  useEffect(() => {
    void loadInitial();
  }, [loadInitial]);

  useEffect(() => {
    const timer = setInterval(() => void refresh(), 3000);
    return () => clearInterval(timer);
  }, [refresh]);

  const saveBrief = useCallback(
    async (payload: Omit<Brief, "source">) => {
      try {
        const saved = await api<Brief>("/api/brief", { method: "PUT", body: payload });
        setBrief({ ...saved, source: "home" });
        notify("Brief guardado", `se usará en la próxima corrida y en el daemon`, "success");
        void refresh();
      } catch (error) {
        fail("No se pudo guardar el brief", error);
        throw error;
      }
    },
    [refresh],
  );

  const requestPlan = useCallback(async () => {
    try {
      const data = await api<{ targets: Target[] }>("/api/plan", { method: "POST" });
      return data.targets;
    } catch (error) {
      fail("El plan del LLM falló", error);
      throw error;
    }
  }, []);

  const startRun = useCallback(
    async (source: "brief" | "job", job?: string) => {
      try {
        const record = await api<ProcRecord>("/api/run", {
          method: "POST",
          body: { source, job: job ?? null },
        });
        setRun(record);
        notify("Corrida lanzada", record.label, "info");
        setSection("run");
      } catch (error) {
        fail("No se pudo lanzar la corrida", error);
      }
    },
    [],
  );

  const cancelRun = useCallback(async () => {
    const current = runRef.current;
    if (!current) return;
    try {
      const record = await api<ProcRecord>(`/api/run/${current.id}`, { method: "DELETE" });
      setRun(record);
      notify("Corrida detenida", undefined, "warning");
    } catch (error) {
      fail("No se pudo detener la corrida", error);
    }
  }, []);

  const startDaemon = useCallback(
    async (intervalHours: number) => {
      try {
        await api<ProcRecord>("/api/daemon", {
          method: "POST",
          body: { interval_hours: intervalHours },
        });
        notify("Daemon iniciado", `cada ${intervalHours} h`, "success");
        void refresh();
      } catch (error) {
        fail("No se pudo iniciar el daemon", error);
      }
    },
    [refresh],
  );

  const stopDaemon = useCallback(async () => {
    try {
      await api("/api/daemon", { method: "DELETE" });
      notify("Daemon detenido", undefined, "warning");
      void refresh();
    } catch (error) {
      fail("No se pudo detener el daemon", error);
    }
  }, [refresh]);

  const queueJob = useCallback(
    async (payload: Omit<Brief, "source"> & { overwrite?: boolean }) => {
      try {
        const res = await api<{ file: string }>("/api/jobs", { method: "POST", body: payload });
        notify("Trabajo encolado", res.file, "success");
        void refresh();
      } catch (error) {
        fail("No se pudo encolar", error);
      }
    },
    [refresh],
  );

  const deleteJob = useCallback(
    async (file: string) => {
      try {
        await api(`/api/jobs/${encodeURIComponent(file)}`, { method: "DELETE" });
        notify("Trabajo borrado", file, "warning");
        void refresh();
      } catch (error) {
        fail("No se pudo borrar", error);
      }
    },
    [refresh],
  );

  const searchPlaces = useCallback(
    async (payload: {
      query: string;
      location?: string | null;
      radius_km?: number;
      limit?: number;
      provider?: string;
    }) => {
      try {
        return await api<PlacesSearchResult>("/api/places/search", {
          method: "POST",
          body: payload,
        });
      } catch (error) {
        fail("La búsqueda de lugares falló", error);
        throw error;
      }
    },
    [],
  );

  const savePlaces = useCallback(
    async (payload: {
      query: string;
      location?: string | null;
      provider?: string;
      places: unknown[];
      center?: unknown;
    }) => {
      try {
        const res = await api<{ run_name: string }>("/api/places/save", {
          method: "POST",
          body: payload,
        });
        notify("Lugares guardados", `corrida ${res.run_name}`, "success");
        void refreshRuns();
        return res.run_name;
      } catch (error) {
        fail("No se pudieron guardar los lugares", error);
        throw error;
      }
    },
    [refreshRuns],
  );

  const saveSettings = useCallback(
    async (payload: {
      llm_api_key?: string;
      llm_base_url?: string;
      llm_model?: string;
      interval_hours?: number;
    }) => {
      try {
        const saved = await api<Settings>("/api/settings", { method: "PUT", body: payload });
        setSettings(saved);
        notify("Ajustes guardados", undefined, "success");
        void refresh();
      } catch (error) {
        fail("No se pudieron guardar los ajustes", error);
        throw error;
      }
    },
    [refresh],
  );

  const testLlm = useCallback(async () => {
    try {
      return await api<{ ok: boolean; model?: string; reply?: string; error?: string }>(
        "/api/settings/test-llm",
        { method: "POST" },
      );
    } catch (error) {
      fail("La prueba del LLM falló", error);
      throw error;
    }
  }, []);

  const runDoctor = useCallback(async () => {
    try {
      return await api<DoctorResult>("/api/doctor", { method: "POST" });
    } catch (error) {
      fail("El doctor falló", error);
      throw error;
    }
  }, []);

  const selectRun = useCallback(async (name: string) => {
    setSelectedRun(name);
    try {
      const detail = await api<RunDetail>(`/api/runs/${encodeURIComponent(name)}`);
      setRunDetail(detail);
    } catch (error) {
      fail("No se pudo abrir la corrida", error);
    }
  }, []);

  const track = useCallback((record: ProcRecord) => {
    setRun(record);
  }, []);

  const value = useMemo<ArgosContextValue>(
    () => ({
      meta,
      status,
      settings,
      brief,
      runs,
      jobs,
      daemon,
      run,
      runDetail,
      selectedRun,
      section,
      setSection,
      refresh,
      saveBrief,
      requestPlan,
      startRun,
      cancelRun,
      startDaemon,
      stopDaemon,
      queueJob,
      deleteJob,
      searchPlaces,
      savePlaces,
      saveSettings,
      testLlm,
      runDoctor,
      selectRun,
      refreshRuns,
      track,
    }),
    [
      meta,
      status,
      settings,
      brief,
      runs,
      jobs,
      daemon,
      run,
      runDetail,
      selectedRun,
      section,
      refresh,
      saveBrief,
      requestPlan,
      startRun,
      cancelRun,
      startDaemon,
      stopDaemon,
      queueJob,
      deleteJob,
      searchPlaces,
      savePlaces,
      saveSettings,
      testLlm,
      runDoctor,
      selectRun,
      refreshRuns,
      track,
    ],
  );

  return <ArgosContext.Provider value={value}>{children}</ArgosContext.Provider>;
}

export { notify };
