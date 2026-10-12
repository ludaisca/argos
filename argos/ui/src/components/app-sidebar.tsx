import {
  ActivityIcon,
  BookOpenIcon,
  GaugeIcon,
  MapPinIcon,
  PlayIcon,
  SettingsIcon,
  TelescopeIcon,
} from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarSeparator,
} from "@/components/ui/sidebar";
import { Badge } from "@/components/ui/badge";
import { useArgos } from "@/lib/store";
import type { Section } from "@/lib/types";

const NAV: { group: string; items: { id: Section; label: string; icon: typeof GaugeIcon }[] }[] = [
  {
    group: "General",
    items: [
      { id: "dashboard", label: "Estado", icon: GaugeIcon },
      { id: "brief", label: "Investigación", icon: BookOpenIcon },
      { id: "places", label: "Lugares", icon: MapPinIcon },
    ],
  },
  {
    group: "Operación",
    items: [
      { id: "run", label: "Ejecutar", icon: PlayIcon },
      { id: "results", label: "Resultados", icon: TelescopeIcon },
    ],
  },
  {
    group: "Configuración",
    items: [{ id: "settings", label: "Ajustes", icon: SettingsIcon }],
  },
];

export function AppSidebar() {
  const { section, setSection, status, daemon } = useArgos();
  const llmOk = status?.llm.llm_configured ?? false;
  const sessions = status?.sessions ?? {};
  const pendingJobs = status?.jobs.pending ?? 0;

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" onClick={() => setSection("dashboard")}>
              <div className="flex size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
                <span className="text-base">🔭</span>
              </div>
              <div className="grid flex-1 text-left leading-tight">
                <span className="truncate font-semibold">Argos</span>
                <span className="truncate text-xs text-muted-foreground">
                  consola de investigación
                </span>
              </div>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        {NAV.map((group) => (
          <SidebarGroup key={group.group}>
            <SidebarGroupLabel>{group.group}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {group.items.map((item) => (
                  <SidebarMenuItem key={item.id}>
                    <SidebarMenuButton
                      isActive={section === item.id}
                      tooltip={item.label}
                      onClick={() => setSection(item.id)}
                    >
                      <item.icon />
                      <span>{item.label}</span>
                    </SidebarMenuButton>
                    {item.id === "run" && pendingJobs > 0 ? (
                      <SidebarMenuBadge>{pendingJobs}</SidebarMenuBadge>
                    ) : null}
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>
      <SidebarFooter>
        <SidebarSeparator />
        <div className="flex flex-col gap-2 p-2 group-data-[collapsible=icon]:hidden">
          <div className="flex flex-wrap gap-1.5">
            <Badge variant={llmOk ? "success" : "error"}>
              {llmOk ? status?.llm.llm_model : "LLM sin configurar"}
            </Badge>
            <Badge variant={daemon?.running ? "info" : "outline"}>
              <ActivityIcon className="size-3" />
              {daemon?.running ? "daemon on" : "daemon off"}
            </Badge>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(sessions).map(([platform, info]) => (
              <Badge
                key={platform}
                variant={info.cookies > 0 || info.profile ? "success" : "warning"}
              >
                {platform} · {info.cookies > 0 ? `${info.cookies}🍪` : info.profile ? "perfil" : "sin sesión"}
              </Badge>
            ))}
          </div>
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}
