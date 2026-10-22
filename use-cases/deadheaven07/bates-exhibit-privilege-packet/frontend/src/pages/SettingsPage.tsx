import { Database, KeyRound, HardDrive, Server } from "lucide-react";

export function SettingsPage() {
  const rows = [
    { icon: Server, label: "API Base URL", value: import.meta.env.VITE_API_URL || "/api (proxied to :8000)" },
    { icon: KeyRound, label: "SuperDocs Integration", value: "Backend-configured (SUPERDOCS_API_KEY from .env)" },
    { icon: Database, label: "Database", value: "PostgreSQL 16 (bates_packet)" },
    { icon: HardDrive, label: "Storage", value: "backend/storage (originals, processed, working, final)" },
  ];

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
      <p className="text-gray-500 mt-1">Application configuration overview.</p>

      <div className="mt-6 bg-white rounded-lg border border-gray-200 divide-y divide-gray-100">
        {rows.map(({ icon: Icon, label, value }) => (
          <div key={label} className="flex items-start gap-4 p-4">
            <Icon className="h-5 w-5 text-primary-600 mt-0.5 flex-shrink-0" />
            <div>
              <p className="text-sm font-medium text-gray-900">{label}</p>
              <p className="text-sm text-gray-500 mt-0.5">{value}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-6 bg-gray-50 rounded-lg border border-gray-200 p-4 text-sm text-gray-600">
        <p className="font-medium text-gray-900 mb-1">Bates Numbering</p>
        <p>
          Packets use a configurable prefix (default <code className="font-mono">CASE-</code>), start number and
          zero-padding width, set per packet at creation time.
        </p>
      </div>
    </div>
  );
}