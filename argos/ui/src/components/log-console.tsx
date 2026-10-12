import { useEffect, useRef } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Spinner } from "@/components/ui/spinner";

export function LogConsole({
  log,
  running,
  title,
}: {
  log: string;
  running: boolean;
  title?: string;
}) {
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [log]);

  return (
    <div className="overflow-hidden rounded-xl border bg-[#0a100d] dark:bg-[#070d0a]">
      <div className="flex items-center gap-2 border-b border-white/5 px-4 py-2">
        <span className="flex gap-1.5">
          <span className="size-2.5 rounded-full bg-red-500/70" />
          <span className="size-2.5 rounded-full bg-amber-500/70" />
          <span className="size-2.5 rounded-full bg-emerald-500/70" />
        </span>
        <span className="ml-2 flex items-center gap-2 text-xs text-emerald-200/70">
          {title ?? "salida"}
          {running ? <Spinner className="size-3.5" /> : null}
        </span>
      </div>
      <ScrollArea className="h-105">
        <pre className="p-4 font-mono text-xs leading-relaxed whitespace-pre-wrap break-words text-emerald-100/90">
          {log || (running ? "…" : "(sin salida)")}
        </pre>
      </ScrollArea>
      <div ref={endRef} />
    </div>
  );
}
