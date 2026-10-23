import { useEffect, useRef } from "react";
import { Bold, Italic, List, ListOrdered, Underline } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type RichTextEditorProps = {
  value: string;
  onChange: (html: string, text: string) => void;
  placeholder?: string;
  className?: string;
  minHeightClassName?: string;
};

export function RichTextEditor({
  value,
  onChange,
  placeholder = "Paste or write the job description…",
  className,
  minHeightClassName = "min-h-[220px]",
}: RichTextEditorProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (ref.current && ref.current.innerHTML !== value) {
      ref.current.innerHTML = value || "";
    }
  }, [value]);

  function exec(command: string) {
    document.execCommand(command, false);
    emit();
  }

  function emit() {
    const html = ref.current?.innerHTML ?? "";
    const text = ref.current?.innerText ?? "";
    onChange(html, text);
  }

  return (
    <div className={cn("overflow-hidden rounded-xl border border-border bg-card", className)}>
      <div className="flex flex-wrap gap-1 border-b border-border bg-muted/40 p-2">
        <Button type="button" size="icon" variant="ghost" onClick={() => exec("bold")} aria-label="Bold">
          <Bold className="h-4 w-4" />
        </Button>
        <Button type="button" size="icon" variant="ghost" onClick={() => exec("italic")} aria-label="Italic">
          <Italic className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          onClick={() => exec("underline")}
          aria-label="Underline"
        >
          <Underline className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          onClick={() => exec("insertUnorderedList")}
          aria-label="Bullet list"
        >
          <List className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          onClick={() => exec("insertOrderedList")}
          aria-label="Numbered list"
        >
          <ListOrdered className="h-4 w-4" />
        </Button>
      </div>
      <div className="relative">
        {!value && (
          <p className="pointer-events-none absolute left-4 top-3 text-sm text-muted-foreground">
            {placeholder}
          </p>
        )}
        <div
          ref={ref}
          contentEditable
          role="textbox"
          aria-multiline
          suppressContentEditableWarning
          className={cn(
            "px-4 py-3 text-sm leading-relaxed outline-none focus-visible:ring-0",
            minHeightClassName,
          )}
          onInput={emit}
          onBlur={emit}
        />
      </div>
    </div>
  );
}
