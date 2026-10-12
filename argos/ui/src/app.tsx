import { useEffect, useState } from "react";
import { MenuIcon } from "lucide-react";
import { AppSidebar } from "@/components/app-sidebar";
import { CommandHint, CommandMenu } from "@/components/command-menu";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { ToastProvider } from "@/components/ui/toast";
import { ArgosProvider, useArgos } from "@/lib/store";
import type { Section } from "@/lib/types";
import { BriefPage } from "@/pages/brief";
import { DashboardPage } from "@/pages/dashboard";
import { LeadsTab } from "@/pages/leads";
import { PlacesPage } from "@/pages/places";
import { ResultsPage } from "@/pages/results";
import { RunPage } from "@/pages/run";
import { SettingsPage } from "@/pages/settings";

const SECTION_TITLES: Record<Section, string> = {
  dashboard: "Estado",
  brief: "Investigación",
  personalizada: "Personalizada",
  places: "Lugares",
  run: "Ejecutar",
  results: "Resultados",
  settings: "Ajustes",
};

function Shell({
  theme,
  setTheme,
  onOpenPalette,
}: {
  theme: "dark" | "light";
  setTheme: (theme: "dark" | "light") => void;
  onOpenPalette: () => void;
}) {
  const { section } = useArgos();
  return (
    <SidebarProvider defaultOpen>
      <AppSidebar />
      <SidebarInset>
        <header className="flex h-14 shrink-0 items-center gap-3 border-b px-4 lg:px-6">
          <SidebarTrigger>
            <MenuIcon />
          </SidebarTrigger>
          <span className="text-sm font-medium">{SECTION_TITLES[section]}</span>
          <div className="ms-auto flex items-center gap-2">
            <CommandHint onOpen={onOpenPalette} />
          </div>
        </header>
        <main className="flex-1 p-4 lg:p-6">
          {section === "dashboard" ? <DashboardPage /> : null}
          {section === "brief" ? <BriefPage /> : null}
          {section === "personalizada" ? <LeadsTab /> : null}
          {section === "places" ? <PlacesPage /> : null}
          {section === "run" ? <RunPage /> : null}
          {section === "results" ? <ResultsPage /> : null}
          {section === "settings" ? <SettingsPage theme={theme} setTheme={setTheme} /> : null}
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}

export function App() {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [theme, setThemeState] = useState<"dark" | "light">(() => {
    const stored = localStorage.getItem("argos_theme");
    return stored === "light" || stored === "dark" ? stored : "dark";
  });

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.style.colorScheme = theme;
    localStorage.setItem("argos_theme", theme);
  }, [theme]);

  const setTheme = (value: "dark" | "light") => setThemeState(value);

  return (
    <ArgosProvider>
      <ToastProvider>
        <Shell theme={theme} setTheme={setTheme} onOpenPalette={() => setPaletteOpen(true)} />
        <CommandMenu open={paletteOpen} onOpenChange={setPaletteOpen} />
      </ToastProvider>
    </ArgosProvider>
  );
}
