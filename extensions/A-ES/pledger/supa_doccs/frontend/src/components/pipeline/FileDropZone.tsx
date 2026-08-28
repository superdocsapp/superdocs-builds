import { useState, useCallback, useRef } from 'react';

interface FileDropZoneProps {
  onFilesSelected: (files: File[]) => void;
  isUploading: boolean;
  disabled?: boolean;
}

const ACCEPTED_EXTENSIONS = ['.pdf', '.docx', '.txt', '.text'];
const ACCEPT_STRING = '.pdf,.docx,.txt,.text';

/**
 * Multi-file drag-and-drop zone + file picker.
 * Replaces the old hidden single-file input.
 */
export function FileDropZone({ onFilesSelected, isUploading, disabled }: FileDropZoneProps) {
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!disabled && !isUploading) {
      setIsDragOver(true);
    }
  }, [disabled, isUploading]);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);

    if (disabled || isUploading) return;

    const droppedFiles = Array.from(e.dataTransfer.files).filter((file) => {
      const ext = '.' + file.name.split('.').pop()?.toLowerCase();
      return ACCEPTED_EXTENSIONS.includes(ext);
    });

    if (droppedFiles.length > 0) {
      onFilesSelected(droppedFiles);
    }
  }, [disabled, isUploading, onFilesSelected]);

  const handleClick = useCallback(() => {
    if (!disabled && !isUploading) {
      fileInputRef.current?.click();
    }
  }, [disabled, isUploading]);

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (files.length > 0) {
      onFilesSelected(files);
    }
    // Reset so re-selecting the same file works
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, [onFilesSelected]);

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onClick={handleClick}
      className={`
        relative rounded-lg border-2 border-dashed p-4 transition-all duration-150 cursor-pointer
        ${disabled || isUploading
          ? 'border-white/[0.06] bg-white/[0.01] cursor-not-allowed opacity-50'
          : isDragOver
            ? 'border-indigo-400/60 bg-indigo-500/[0.08]'
            : 'border-white/[0.12] bg-white/[0.02] hover:border-white/[0.2] hover:bg-white/[0.04]'
        }
      `}
      role="button"
      aria-label="Drop files here or click to browse"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') handleClick(); }}
    >
      <input
        ref={fileInputRef}
        type="file"
        accept={ACCEPT_STRING}
        multiple
        className="hidden"
        onChange={handleFileChange}
        aria-hidden="true"
      />

      <div className="flex flex-col items-center gap-2 text-center">
        {isUploading ? (
          <>
            <svg className="w-6 h-6 text-indigo-400 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M12 2v4m0 12v4m-7.07-3.93l2.83-2.83m8.48-8.48l2.83-2.83M2 12h4m12 0h4m-3.93 7.07l-2.83-2.83M6.34 6.34L3.51 3.51" strokeLinecap="round" />
            </svg>
            <span className="text-[12px] text-white/50">Uploading...</span>
          </>
        ) : (
          <>
            <svg className="w-6 h-6 text-white/30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
              <path d="M12 16V4m0 0l-4 4m4-4l4 4" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M2 17l.621 2.485A2 2 0 004.561 21h14.878a2 2 0 001.94-1.515L22 17" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="text-[12px] text-white/50">
              Drop files here or <span className="text-indigo-400">browse</span>
            </span>
            <span className="text-[10px] text-white/30">PDF, DOCX, TXT — multiple files OK</span>
          </>
        )}
      </div>
    </div>
  );
}
