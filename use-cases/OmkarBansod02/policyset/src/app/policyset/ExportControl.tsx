"use client";

import { ChevronDown, Download, LoaderCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { PolicyDocumentExportFormat } from "./superdocs-contract";

export function ExportControl({
  hasSession,
  disabled,
  exportingFormat,
  documentTitle,
  onExport,
}: {
  hasSession: boolean;
  disabled: boolean;
  exportingFormat: PolicyDocumentExportFormat | null;
  documentTitle: string;
  onExport: (format: PolicyDocumentExportFormat) => void;
}) {
  const exporting = exportingFormat !== null;
  const unavailableMessage = !hasSession
    ? "Connect SuperDocs before exporting."
    : disabled && !exporting
      ? "Finish the current SuperDocs operation before exporting."
      : undefined;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="quiet"
          size="sm"
          disabled={disabled || exporting}
          title={unavailableMessage}
          aria-label={
            exporting
              ? `Exporting ${documentTitle} as ${exportingFormat.toUpperCase()}`
              : `Export ${documentTitle}`
          }
        >
          {exporting ? (
            <LoaderCircle data-icon="inline-start" className="animate-spin" />
          ) : (
            <Download data-icon="inline-start" />
          )}
          <span className="hidden sm:inline">
            {exporting ? `Exporting ${exportingFormat.toUpperCase()}…` : "Export"}
          </span>
          {!exporting ? <ChevronDown data-icon="inline-end" /> : null}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" aria-label={`Export ${documentTitle}`}>
        <DropdownMenuGroup>
          <DropdownMenuItem onSelect={() => onExport("docx")}>
            <Download />
            Download DOCX
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => onExport("pdf")}>
            <Download />
            Download PDF
          </DropdownMenuItem>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
