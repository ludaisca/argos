import { useEffect, useMemo, useState } from "react";
import {
  ActivityIcon,
  BookOpenIcon,
  GaugeIcon,
  MapPinIcon,
  PlayIcon,
  SettingsIcon,
  SquareIcon,
  StethoscopeIcon,
  TelescopeIcon,
  WrenchIcon,
  ZapIcon,
} from "lucide-react";
import {
  Command,
  CommandDialog,
  CommandDialogPopup,
  CommandEmpty,
  CommandGroup,
  CommandGroupLabel,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Kbd } from "@/components/ui/kbd";
import { notify, useArgos } from "@/lib/store";
import type { Section } from "@/lib/types";

interface PaletteAction {
  value: string;
  label: string;
  group: string;
  icon: typeof GaugeIcon;
  run: () => void | Promise<void>;
}

export function CommandMenu({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const {
    setSection,
    startRun,
    cancelRun,
    startDaemon,
    stopDaemon,
    daemon,
    refresh,
    runDoctor,
  } = useArgos();

  const actions = useMemo<PaletteAction[]>(() => {
    const nav = (section: Section, label: string, icon: typeof GaugeIcon): PaletteAction => ({
      value: `ir-${section}`,
      label: `Ir a ${label}`,
      group: "Navegación",
      icon,
      run: () => setSection(section),
    });
    return [
      nav("dashboard", "Estado", GaugeIcon),
      nav("brief", "Investigación", BookOpenIcon),
      nav("personalizada", "Personalizada (leads)", StethoscopeIcon),
      nav("places", "Lugares", MapPinIcon),
      nav("run", "Ejecutar", PlayIcon),
      nav("results", "Resultados", TelescopeIcon),
      nav("settings", "Ajustes", SettingsIcon),
      {
        value: "correr-ahora",
        label: "Correr ahora (brief actual)",
        group: "Acciones",
        icon: ZapIcon,
        run: () => startRun("brief"),
      },
      {
        value: "detener-corrida",
        label: "Detener la corrida en curso",
        group: "Acciones",
        icon: SquareIcon,
        run: () => cancelRun(),
      },
      {
        value: "daemon-toggle",
        label: daemon?.running ? "Detener el daemon" : "Iniciar el daemon",
        group: "Acciones",
        icon: ActivityIcon,
        run: () =>
          daemon?.running
            ? stopDaemon()
            : startDaemon(Number(localStorage.getItem("argos_interval") ?? 12) || 12),
      },
      {
        value: "doctor",
        label: "Chequear sesiones (doctor)",
        group: "Acciones",
        icon: WrenchIcon,
        run: async () => {
          setSection("settings");
          void refresh();
          const result = await runDoctor();
          notify(
            "Doctor",
            Object.entries(result.platforms)
              .map(([name, info]) => `${name}: ${info.status}`)
              .join(" · "),
            "info",
          );
        },
      },
    ];
  }, [
    setSection,
    startRun,
    cancelRun,
    startDaemon,
    stopDaemon,
    daemon,
    refresh,
    runDoctor,
    notify,
  ]);

  const items = useMemo(
    () => actions.map((action) => ({ value: action.value, label: action.label })),
    [actions],
  );

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        onOpenChange(!open);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onOpenChange]);

  const runAction = async (value: string) => {
    const action = actions.find((item) => item.value === value);
    onOpenChange(false);
    if (action) await action.run();
  };

  const groups = useMemo(() => {
    const map = new Map<string, PaletteAction[]>();
    for (const action of actions) {
      const list = map.get(action.group) ?? [];
      list.push(action);
      map.set(action.group, list);
    }
    return [...map.entries()];
  }, [actions]);

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange}>
      <CommandDialogPopup>
        <Command
          items={items}
          onValueChange={(value) => void runAction(String(value))}
        >
          <CommandInput placeholder="Buscar acciones… (correr, daemon, doctor, ir a…)" />
          <CommandList>
            <CommandEmpty>Sin resultados.</CommandEmpty>
            {groups.map(([group, groupActions]) => (
              <CommandGroup key={group}>
                <CommandGroupLabel>{group}</CommandGroupLabel>
                {groupActions.map((action) => (
                  <CommandItem
                    key={action.value}
                    value={action.value}
                    onClick={() => void runAction(action.value)}
                  >
                    <action.icon className="size-4" />
                    <span>{action.label}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}
          </CommandList>
        </Command>
      </CommandDialogPopup>
    </CommandDialog>
  );
}

export function CommandHint({ onOpen }: { onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="inline-flex h-8 items-center gap-2 rounded-lg border bg-background px-3 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
    >
      <span>Buscar…</span>
      <Kbd>⌘K</Kbd>
    </button>
  );
}
