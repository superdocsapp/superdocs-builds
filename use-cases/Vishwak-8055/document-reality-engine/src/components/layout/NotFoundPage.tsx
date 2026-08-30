import { Link } from "react-router-dom";
import { FileQuestion } from "lucide-react";

export function NotFoundPage() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-6 py-24 text-center">
      <FileQuestion className="h-8 w-8 text-text-tertiary" aria-hidden="true" />
      <h1 className="text-lg font-semibold text-text-primary">Page not found</h1>
      <p className="max-w-sm text-sm text-text-tertiary">The page you're looking for doesn't exist, or the document may have been moved.</p>
      <Link to="/" className="mt-2 rounded-md bg-trust px-3.5 py-2 text-sm font-medium text-white transition-colors hover:bg-trust-strong">
        Back to Dashboard
      </Link>
    </div>
  );
}
