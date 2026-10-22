import { useEffect, useRef, useState, useCallback } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import { ChevronLeft, ChevronRight, Minus, Plus, RotateCcw, Download, Loader2, AlertCircle, FileText } from "lucide-react";
import { clsx } from "clsx";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url
).toString();

interface DocumentPdfViewerProps {
  packetId: string;
  documentId: string;
  fileName: string;
  pageCount: number;
  batesRange?: string | null;
  onDownload?: () => void;
}

type PDFDoc = { numPages: number };

export function DocumentPdfViewer({
  packetId,
  documentId,
  fileName,
  pageCount,
  batesRange,
  onDownload,
}: DocumentPdfViewerProps) {
  const [numPages, setNumPages] = useState<number | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [scale, setScale] = useState(1.0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);

  const pdfDocRef = useRef<PDFDoc | null>(null);

  const pdfSource = pdfUrl ? { url: pdfUrl } : null;

  useEffect(() => {
    setLoading(true);
    setError(null);
    const controller = new AbortController();

    fetch(`/api/documents/${packetId}/${documentId}/download`, {
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Failed to load PDF: ${response.status}`);
        }
        return response.blob();
      })
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        setPdfUrl(url);
        setLoading(false);
      })
      .catch((err) => {
        if (err.name !== "AbortError") {
          setError(err.message || "Failed to load PDF");
          setLoading(false);
        }
      });

    return () => {
      controller.abort();
      if (pdfUrl) {
        URL.revokeObjectURL(pdfUrl);
      }
    };
  }, [packetId, documentId]);

  const onDocumentLoadSuccess = useCallback((pdf: PDFDoc) => {
    pdfDocRef.current = pdf;
    setNumPages(pdf.numPages);
    setLoading(false);
  }, []);

  const onDocumentLoadError = useCallback((err: Error) => {
    setError(err.message || "Failed to load PDF document");
    setLoading(false);
  }, []);

  const handlePreviousPage = () => {
    setPageNumber((prev) => Math.max(1, prev - 1));
  };

  const handleNextPage = () => {
    setPageNumber((prev) => Math.min(numPages || pageCount, prev + 1));
  };

  const handleZoomIn = () => {
    setScale((prev) => Math.min(prev + 0.25, 3.0));
  };

  const handleZoomOut = () => {
    setScale((prev) => Math.max(prev - 0.25, 0.5));
  };

  const handleZoomReset = () => {
    setScale(1.0);
  };

  if (error) {
    return (
      <div className="aspect-video dark:bg-slate-900/60 bg-rose-50/50 rounded-2xl border dark:border-rose-800/80 border-rose-200 flex flex-col items-center justify-center p-6 text-center">
        <AlertCircle className="h-10 w-10 text-rose-500 mb-3" />
        <p className="dark:text-rose-200 text-rose-800 font-semibold">Failed to load PDF</p>
        <p className="text-xs dark:text-rose-300 text-rose-700 px-4 mt-1 max-w-sm">{error}</p>
        <button
          onClick={() => {
            setError(null);
            setLoading(true);
            setPdfUrl(null);
          }}
          className="mt-4 px-4 py-2 text-xs font-medium bg-rose-600 hover:bg-rose-500 text-white rounded-xl transition-colors shadow-sm"
        >
          Retry
        </button>
      </div>
    );
  }

  if (loading || !pdfSource) {
    return (
      <div className="aspect-video dark:bg-slate-900/40 bg-slate-100 rounded-2xl border dark:border-slate-800 border-slate-200 flex flex-col items-center justify-center p-8">
        <Loader2 className="h-10 w-10 animate-spin text-sky-500 mb-3" />
        <p className="dark:text-slate-300 text-slate-700 text-sm font-medium">Loading document render...</p>
        <p className="text-xs font-mono dark:text-slate-500 text-slate-400 mt-1 truncate max-w-xs">{fileName}</p>
      </div>
    );
  }

  return (
    <div className="dark:bg-slate-900/90 bg-white border dark:border-slate-800 border-slate-200 rounded-2xl overflow-hidden flex flex-col h-full shadow-sm backdrop-blur-md">
      {/* Top Viewer Toolbar */}
      <div className="flex items-center justify-between px-4 py-3 border-b dark:border-slate-800 border-slate-200 dark:bg-slate-950/60 bg-slate-50">
        <div className="flex items-center gap-3 min-w-0">
          <div className="h-8 w-8 rounded-lg dark:bg-sky-500/10 bg-sky-50 border dark:border-sky-500/20 border-sky-200 flex items-center justify-center text-sky-500 shrink-0">
            <FileText className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <p className="font-semibold dark:text-white text-slate-900 text-sm truncate max-w-xs">{fileName}</p>
            <div className="flex items-center gap-2 text-xs dark:text-slate-400 text-slate-500 mt-0.5">
              <span>{numPages || pageCount} page{((numPages || pageCount) !== 1 ? "s" : "")}</span>
              {batesRange && (
                <>
                  <span>•</span>
                  <span className="font-mono text-sky-500 dark:bg-sky-500/10 bg-sky-50 px-1.5 py-0.2 rounded border dark:border-sky-500/20 border-sky-200 text-[11px] font-bold">
                    {batesRange}
                  </span>
                </>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {onDownload && (
            <button
              onClick={onDownload}
              className="p-2 dark:text-slate-400 text-slate-500 hover:text-sky-500 dark:hover:bg-slate-800 hover:bg-slate-100 rounded-xl transition-colors"
              title="Download original"
            >
              <Download className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      {/* PDF Viewport */}
      <div className="flex-1 overflow-auto relative dark:bg-slate-950/80 bg-slate-100 flex items-center justify-center p-6" style={{ minHeight: 450 }}>
        <Document
          file={pdfSource}
          onLoadSuccess={onDocumentLoadSuccess}
          onLoadError={onDocumentLoadError}
          renderMode="canvas"
          className="shadow-xl rounded-lg overflow-hidden border dark:border-slate-800 border-slate-300"
        >
          <Page
            pageNumber={pageNumber}
            width={pageNumber > 0 ? 760 * scale : undefined}
            renderAnnotationLayer={false}
            renderTextLayer={false}
          />
        </Document>
      </div>

      {/* Bottom Viewer Controls */}
      <div className="flex items-center justify-between px-4 py-2.5 border-t dark:border-slate-800 border-slate-200 dark:bg-slate-950/70 bg-slate-50">
        <div className="flex items-center gap-2">
          <button
            onClick={handlePreviousPage}
            disabled={pageNumber <= 1}
            className={clsx(
              "p-1.5 rounded-lg transition-colors disabled:opacity-30 disabled:cursor-not-allowed",
              "dark:text-slate-400 text-slate-600 dark:hover:text-white hover:text-slate-900 dark:hover:bg-slate-800 hover:bg-slate-200"
            )}
            title="Previous page"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="px-2.5 py-1 text-xs font-mono dark:text-slate-300 text-slate-700 dark:bg-slate-900 bg-white border dark:border-slate-800 border-slate-300 rounded-lg">
            {pageNumber} / {numPages || pageCount}
          </span>
          <button
            onClick={handleNextPage}
            disabled={pageNumber >= (numPages || pageCount)}
            className={clsx(
              "p-1.5 rounded-lg transition-colors disabled:opacity-30 disabled:cursor-not-allowed",
              "dark:text-slate-400 text-slate-600 dark:hover:text-white hover:text-slate-900 dark:hover:bg-slate-800 hover:bg-slate-200"
            )}
            title="Next page"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={handleZoomOut}
            disabled={scale <= 0.5}
            className={clsx(
              "p-1.5 rounded-lg transition-colors disabled:opacity-30 disabled:cursor-not-allowed",
              "dark:text-slate-400 text-slate-600 dark:hover:text-white hover:text-slate-900 dark:hover:bg-slate-800 hover:bg-slate-200"
            )}
            title="Zoom out"
          >
            <Minus className="h-4 w-4" />
          </button>
          <span className="px-2 py-1 text-xs font-mono dark:text-slate-300 text-slate-700 dark:bg-slate-900 bg-white border dark:border-slate-800 border-slate-300 rounded-lg w-14 text-center">
            {Math.round(scale * 100)}%
          </span>
          <button
            onClick={handleZoomIn}
            disabled={scale >= 3.0}
            className={clsx(
              "p-1.5 rounded-lg transition-colors disabled:opacity-30 disabled:cursor-not-allowed",
              "dark:text-slate-400 text-slate-600 dark:hover:text-white hover:text-slate-900 dark:hover:bg-slate-800 hover:bg-slate-200"
            )}
            title="Zoom in"
          >
            <Plus className="h-4 w-4" />
          </button>
          <button
            onClick={handleZoomReset}
            className={clsx(
              "p-1.5 rounded-lg transition-colors ml-1",
              "dark:text-slate-400 text-slate-600 dark:hover:text-white hover:text-slate-900 dark:hover:bg-slate-800 hover:bg-slate-200"
            )}
            title="Reset zoom"
          >
            <RotateCcw className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}