import { useMemo } from "react";
import { mdToHtml } from "@/lib/markdown";

export function MarkdownView({ source }: { source: string }) {
  const html = useMemo(() => mdToHtml(source), [source]);
  return (
    <div
      className="text-sm leading-relaxed [&_h3]:mt-5 [&_h3]:mb-2 [&_h3]:text-base [&_h3]:font-semibold [&_h4]:mt-4 [&_h4]:mb-1.5 [&_h4]:font-semibold [&_p]:my-2 [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5 [&_li]:my-0.5 [&_hr]:my-4 [&_hr]:border-border [&_code]:rounded [&_code]:bg-muted [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-xs [&_pre]:my-3 [&_pre]:overflow-auto [&_pre]:rounded-lg [&_pre]:border [&_pre]:bg-muted/50 [&_pre]:p-3 [&_a]:text-primary [&_a]:underline [&_strong]:font-semibold"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
