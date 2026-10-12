import { Tabs, TabsList, TabsPanel, TabsTab } from "@/components/ui/tabs";
import { BriefPage } from "@/pages/brief";
import { LeadsTab } from "@/pages/leads";

export function InvestigacionPage() {
  return (
    <Tabs defaultValue="brief" className="gap-4">
      <TabsList>
        <TabsTab value="brief">Investigación</TabsTab>
        <TabsTab value="personalizada">Personalizada</TabsTab>
      </TabsList>
      <TabsPanel value="brief">
        <BriefPage />
      </TabsPanel>
      <TabsPanel value="personalizada">
        <LeadsTab />
      </TabsPanel>
    </Tabs>
  );
}
