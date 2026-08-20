import { FileText } from "lucide-react";

function Header() {
    return (
        <header className="fixed inset-x-0 top-0 z-50 border-b border-slate-200 bg-white/95 backdrop-blur">
            <div className="mx-auto flex h-16 max-w-7xl items-center px-6">
                <div className="flex items-center gap-3">
                    <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-900 text-white">
                        <FileText size={18} />
                    </div>

                    <div>
                        <h1 className="text-base font-semibold tracking-tight text-slate-900">
                            Dealer Agreement Redline
                        </h1>

                        <p className="hidden text-xs text-slate-500 sm:block">
                            Review and approve contract changes
                        </p>
                    </div>
                </div>
            </div>
        </header>
    );
}

export default Header;
