import { useState } from "react";
import axios from "axios";
import type { Branding, Property } from "./types/brandingproperty";

const emptyProperty = (): Property => ({
  address: "",
  city: "",
  state: "",
  beds: "",
  baths: "",
  sqft: "",
  lot_size_sqft: "",
  year_built: "",
  list_price: "",
  sale_price: "",
  sale_date: "",
  photo_url: "",
  distance_miles: "",
  days_on_market: "",
});
const emptyBranding: Branding = { agent_name: "", brokerage: "", phone: "", email: "" };
const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

function Field({ label, value, onChange, type = "text", placeholder }: { label: string; value: string; onChange: (value: string) => void; type?: string; placeholder?: string }) {
  return (
    <label className="block space-y-2">
      <span className="text-[11px] font-bold uppercase tracking-[0.16em] text-slate-500">{label}</span>
      <input
        required
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none transition focus:border-amber-500 focus:ring-4 focus:ring-amber-500/10"
      />
    </label>
  );
}
function PropertyFields({ property, update, subject = false }: { property: Property; update: (key: keyof Property, value: string) => void; subject?: boolean }) {
  return (
    <div className="grid gap-5 sm:grid-cols-2">
      <div className="sm:col-span-2">
        <Field label="Street address" value={property.address} onChange={(v) => update("address", v)} placeholder="123 Main Street" />
      </div>
      <Field label="City" value={property.city} onChange={(v) => update("city", v)} placeholder="Austin" />
      <Field label="State" value={property.state} onChange={(v) => update("state", v)} placeholder="TX" />
      <Field label="Bedrooms" type="number" value={property.beds} onChange={(v) => update("beds", v)} placeholder="3" />
      <Field label="Bathrooms" type="number" value={property.baths} onChange={(v) => update("baths", v)} placeholder="2" />
      <Field label="Square feet" type="number" value={property.sqft} onChange={(v) => update("sqft", v)} placeholder="1850" />
      <Field label="Lot size (sq ft)" type="number" value={property.lot_size_sqft} onChange={(v) => update("lot_size_sqft", v)} placeholder="7500" />
      <Field label="Year built" type="number" value={property.year_built} onChange={(v) => update("year_built", v)} placeholder="2018" />
      {subject ? null : (
        <>
          <Field label="List price" type="number" value={property.list_price} onChange={(v) => update("list_price", v)} placeholder="525000" />
          <Field label="Sale price" type="number" value={property.sale_price} onChange={(v) => update("sale_price", v)} placeholder="510000" />
          <Field label="Sale date" type="date" value={property.sale_date} onChange={(v) => update("sale_date", v)} placeholder="2026-06-15" />
          <Field label="Distance (miles)" type="number" value={property.distance_miles} onChange={(v) => update("distance_miles", v)} placeholder="1.2" />
          <Field label="Days on market" type="number" value={property.days_on_market} onChange={(v) => update("days_on_market", v)} placeholder="18" />
        </>
      )}
      <div className="sm:col-span-2">
        <Field label="Photo URL" type="url" value={property.photo_url} onChange={(v) => update("photo_url", v)} placeholder="https://picsum.photos/seed/property/800/600" />
      </div>
    </div>
  );
}
function App() {
  const [branding, setBranding] = useState(emptyBranding);
  const [subject, setSubject] = useState(emptyProperty());
  const [comps, setComps] = useState([emptyProperty(), emptyProperty(), emptyProperty(), emptyProperty()]);
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState("");
  const updateComp = (index: number, key: keyof Property, value: string) => setComps((items) => items.map((item, i) => (i === index ? { ...item, [key]: value } : item)));
  const normalize = (item: Property, isSubject = false) => ({
    ...item,
    beds: Number(item.beds),
    baths: Number(item.baths),
    sqft: Number(item.sqft),
    lot_size_sqft: Number(item.lot_size_sqft),
    year_built: Number(item.year_built),
    list_price: isSubject ? 0 : Number(item.list_price),
    sale_price: isSubject ? null : Number(item.sale_price),
    sale_date: isSubject ? null : item.sale_date,
    distance_miles: isSubject ? null : Number(item.distance_miles),
    days_on_market: isSubject ? null : Number(item.days_on_market),
  });
  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoading(true);
    setSuccess(false);
    setError("");
    try {
      await axios.post(`${API_URL}/api/generate-cma`, { branding, subject: normalize(subject, true), comps: comps.map((item) => normalize(item)) });
      setSuccess(true);
    } catch (requestError) {
      setError(axios.isAxiosError(requestError) ? (requestError.response?.data?.detail ?? "Could not create the document. Check that the backend is running.") : "Could not create the document.");
    } finally {
      setLoading(false);
    }
  };
  const updateBranding = (key: keyof Branding, value: string) => setBranding((current) => ({ ...current, [key]: value }));
  return (
    <main className="min-h-screen overflow-x-hidden bg-[#f4f1eb] text-slate-900">
      <nav className="mx-auto flex max-w-6xl items-center justify-between px-6 py-7 lg:px-10">
        <div className="flex items-center gap-3">
          <span className="grid h-9 w-9 place-items-center rounded-full bg-[#173b4a] font-bold text-amber-300">C</span>
          <span className="text-sm font-bold tracking-[0.2em] text-[#173b4a]">COMPASS / CMA</span>
        </div>
        <span className="hidden text-xs uppercase tracking-[0.18em] text-slate-500 sm:block">Listing presentation studio</span>
      </nav>
      <section className="mx-auto grid max-w-6xl gap-12 px-6 pb-20 pt-12 lg:grid-cols-[1.05fr_0.95fr] lg:px-10 lg:pt-24">
        <div>
          <p className="mb-7 text-xs font-bold uppercase tracking-[0.25em] text-amber-700">A better first impression</p>
          <h1 className="max-w-5xl text-5xl font-semibold leading-[0.98] tracking-[-0.06em] text-[#173b4a] sm:text-7xl">Turn market data into a document sellers remember.</h1>
          <p className="mt-8 max-w-xl text-lg leading-8 text-slate-600">
            Build a polished comparative market analysis with your branding, a photo-backed subject property, and the comps that support your recommendation.
          </p>
        </div>
        <div className="rounded-4xl bg-[#173b4a] p-8 text-white shadow-2xl shadow-[#173b4a]/20 sm:p-10">
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-amber-300">Ready when you are</p>
          <p className="mt-8 text-3xl font-medium leading-tight">
            One subject.
            <br />
            Four strong comps.
            <br />
            <span className="text-amber-300">One clear story.</span>
          </p>
          <p className="mt-10 border-t border-white/20 pt-5 text-sm text-slate-300">Every field is required so your final report is complete.</p>
        </div>
      </section>
      <form onSubmit={submit} className="mx-auto max-w-6xl space-y-8 px-6 pb-24 lg:px-10">
        <section className="rounded-4xl bg-white p-7 shadow-sm sm:p-10">
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-amber-700">Your identity</p>
          <h2 className="mt-2 mb-8 border-b border-slate-100 pb-6 text-3xl font-semibold text-[#173b4a]">Branding details</h2>
          <div className="grid gap-5 sm:grid-cols-2">
            <Field label="Agent name" value={branding.agent_name} onChange={(v) => updateBranding("agent_name", v)} placeholder="Jordan Lee" />
            <Field label="Brokerage" value={branding.brokerage} onChange={(v) => updateBranding("brokerage", v)} placeholder="Compass Realty" />
            <Field label="Phone" type="tel" value={branding.phone} onChange={(v) => updateBranding("phone", v)} placeholder="(512) 555-0147" />
            <Field label="Email" type="email" value={branding.email} onChange={(v) => updateBranding("email", v)} placeholder="jordan@example.com" />
          </div>
        </section>
        <section className="rounded-4xl bg-white p-7 shadow-sm sm:p-10">
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-amber-700">The listing</p>
          <h2 className="mt-2 mb-8 border-b border-slate-100 pb-6 text-3xl font-semibold text-[#173b4a]">Subject property</h2>
          <PropertyFields subject property={subject} update={(key, value) => setSubject((current) => ({ ...current, [key]: value }))} />
        </section>
        <section className="rounded-4xl bg-white p-7 shadow-sm sm:p-10">
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-amber-700">The evidence</p>
          <h2 className="mt-2 text-3xl font-semibold text-[#173b4a]">Comparable properties</h2>
          <p className="mt-2 mb-8 text-sm text-slate-500">Four are required. Add more when the market calls for it.</p>
          {comps.map((comp, index) => (
            <div key={index} className="border-t border-slate-100 py-8">
              <h3 className="mb-5 font-semibold text-[#173b4a]">Comparable {index + 1}</h3>
              <PropertyFields property={comp} update={(key, value) => updateComp(index, key, value)} />
            </div>
          ))}
          <button
            type="button"
            onClick={() => setComps([...comps, emptyProperty()])}
            className="rounded-full border border-[#173b4a] px-5 py-3 text-sm font-semibold text-[#173b4a] transition hover:bg-[#173b4a] hover:text-white"
          >
            + Add another comparable
          </button>
        </section>
        <section className="flex flex-col gap-5 rounded-4xl bg-[#173b4a] p-7 text-white sm:flex-row sm:items-center sm:justify-between sm:p-10">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.2em] text-amber-300">Ready to send</p>
            <h2 className="mt-2 text-3xl font-semibold">Create the presentation</h2>
          </div>
          <button disabled={loading} className="rounded-full bg-amber-300 px-7 py-4 text-sm font-bold text-[#173b4a] transition hover:bg-amber-200 disabled:cursor-wait disabled:opacity-60">
            {loading ? "Creating document…" : "Create CMA document →"}
          </button>
        </section>
        {success ? (
          <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5 text-sm font-semibold text-emerald-800">Document created Successfully. Check at use.superdocs.app</div>
        ) : null}
        {error ? <div className="rounded-2xl border border-red-200 bg-red-50 p-5 text-sm font-semibold text-red-800">{error}</div> : null}
      </form>
    </main>
  );
}
export default App;
