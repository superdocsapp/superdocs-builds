import { useCallback, useRef, useState } from "react";
import { FileUp, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type DragDropUploadProps = {
  accept?: string;
  maxSizeMb?: number;
  value?: File | null;
  fileName?: string | null;
  onChange: (file: File | null) => void;
  label?: string;
  hint?: string;
};

export function DragDropUpload({
  accept = ".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  maxSizeMb = 10,
  value,
  fileName,
  onChange,
  label = "Upload file",
  hint = "PDF or DOCX up to 10MB",
}: DragDropUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const validateAndSet = useCallback(
    (file: File | null) => {
      setError(null);
      if (!file) {
        onChange(null);
        return;
      }
      const lower = file.name.toLowerCase();
      if (!lower.endsWith(".pdf") && !lower.endsWith(".docx")) {
        setError("Only PDF or DOCX files are supported.");
        return;
      }
      if (file.size > maxSizeMb * 1024 * 1024) {
        setError(`File exceeds ${maxSizeMb}MB limit.`);
        return;
      }
      onChange(file);
    },
    [maxSizeMb, onChange],
  );

  return (
    <div className="space-y-2">
      <div
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
        }}
        onClick={() => inputRef.current?.click()}
        onDragEnter={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={(e) => {
          e.preventDefault();
          setDragging(false);
        }}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const file = e.dataTransfer.files?.[0] ?? null;
          validateAndSet(file);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-12 text-center transition",
          dragging
            ? "border-primary bg-primary/5"
            : "border-border bg-card hover:border-primary/50 hover:bg-muted/40",
        )}
      >
        <div className="mb-3 rounded-full bg-primary/10 p-3 text-primary">
          <FileUp className="h-6 w-6" />
        </div>
        <p className="font-semibold">{label}</p>
        <p className="mt-1 text-sm text-muted-foreground">{hint}</p>
        <p className="mt-3 text-xs text-muted-foreground">Drag & drop or click to browse</p>
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          className="hidden"
          onChange={(e) => validateAndSet(e.target.files?.[0] ?? null)}
        />
      </div>

      {(value || fileName) && (
        <div className="flex items-center justify-between rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm">
          <span className="truncate">{value?.name || fileName}</span>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Remove file"
            onClick={(e) => {
              e.stopPropagation();
              validateAndSet(null);
              if (inputRef.current) inputRef.current.value = "";
            }}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      )}

      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
}
