import { useState, useMemo } from 'react'

const TIERS = [
  { name: 'Free', max: 500, monthly: 0 },
  { name: 'Plus', max: 2000, monthly: 20 },
  { name: 'Pro', max: 10000, monthly: 99 },
]

const SCENARIOS = [
  { label: 'Startup MVP', volume: 200, hours: 120, hourlyCost: 65, infra: 50 },
  { label: 'Growth SaaS', volume: 1500, hours: 250, hourlyCost: 85, infra: 150 },
  { label: 'Enterprise Fleet', volume: 6000, hours: 400, hourlyCost: 110, infra: 300 },
]

export default function App() {
  const [volume, setVolume] = useState(1500)
  const [hours, setHours] = useState(200)
  const [hourlyCost, setHourlyCost] = useState(75)
  const [infra, setInfra] = useState(100)
  const [horizon, setHorizon] = useState(3)
  const [downloading, setDownloading] = useState(false)
  const [pdfDataUrl, setPdfDataUrl] = useState<string | null>(null)
  const [pdfPath, setPdfPath] = useState<string | null>(null)
  const [copiedPath, setCopiedPath] = useState(false)

  const results = useMemo(() => {
    const buildOneTime = hours * hourlyCost
    const buildMaintPerYear = hours * 0.2 * hourlyCost
    const buildInfraPerYear = infra * 12
    const buildTotal = buildOneTime + (buildMaintPerYear + buildInfraPerYear) * horizon

    const tier = volume <= 500 ? TIERS[0] : volume <= 2000 ? TIERS[1] : TIERS[2]
    const buyAnnual = tier.monthly * 12
    const buyTotal = buyAnnual * horizon

    const savings = buildTotal - buyTotal
    const savingsPct = buildTotal > 0 ? Math.round((savings / buildTotal) * 100) : 0
    const buildAnnualOp = buildMaintPerYear + buildInfraPerYear
    const annualOpSavings = buildAnnualOp - buyAnnual
    const buildBreakevenMonths =
      tier.monthly >= 0 && annualOpSavings > 0 ? (buildOneTime / annualOpSavings) * 12 : null

    return {
      buildOneTime,
      buildMaintPerYear,
      buildInfraPerYear,
      buildTotal,
      buyTier: tier.name,
      buyMonthly: tier.monthly,
      buyAnnual,
      buyTotal,
      savings,
      savingsPct,
      buildAnnualOp,
      buildBreakevenMonths,
    }
  }, [volume, hours, hourlyCost, infra, horizon])

  const fmt = (n: number) =>
    n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

  const handleDownload = async () => {
    setDownloading(true)
    setPdfPath(null)
    setPdfDataUrl(null)
    try {
      const res = await fetch('/api/export-report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: `roi-${Date.now()}`,
          volume,
          hours,
          hourly_cost: hourlyCost,
          infrastructure_monthly: infra,
          horizon_years: horizon,
        }),
      })
      if (!res.ok) throw new Error(`Export failed: ${res.statusText}`)
      const data = await res.json()
      setPdfPath(data.pdf_path)
      setPdfDataUrl(data.pdf_data_url || null)
    } catch (err: any) {
      alert(`Report export failed: ${err.message}`)
    } finally {
      setDownloading(false)
    }
  }

  const maxVal = Math.max(results.buildTotal, results.buyTotal, 1)
  const buildPct = (results.buildTotal / maxVal) * 100
  const buyPct = (results.buyTotal / maxVal) * 100

  return (
    <div className="app-container">
      {/* Top Header */}
      <header style={{
        background: 'var(--bg-surface)',
        borderBottom: '1px solid var(--border-subtle)',
        padding: '12px 24px',
        position: 'sticky',
        top: 0,
        zIndex: 50,
      }}>
        <div style={{
          maxWidth: 1480,
          margin: '0 auto',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 16,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{
              background: 'linear-gradient(135deg, #10b981, #0ea5e9)',
              color: '#fff',
              fontWeight: 800,
              fontSize: 12,
              padding: '4px 10px',
              borderRadius: 6,
              letterSpacing: '0.05em',
            }}>
              💰 FINOPS ENGINE
            </span>
            <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
              SuperDocs Build vs Buy ROI Calculator
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span className="badge badge-cyan" style={{ fontFamily: 'var(--font-mono)', textTransform: 'none' }}>
              Tier: SuperDocs {results.buyTier} (${results.buyMonthly}/mo)
            </span>
            <span className="badge badge-emerald">
              <span className="pulse-dot" /> Live Financial Model
            </span>
          </div>
        </div>
      </header>

      {/* Top KPI Scorecards */}
      <div style={{
        maxWidth: 1480,
        margin: '20px auto 0',
        padding: '0 24px',
        width: '100%',
        display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr)',
        gap: 16,
      }}>
        <div className="panel" style={{ margin: 0 }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 700, letterSpacing: '0.04em' }}>
            {horizon}-YEAR NET SAVINGS
          </div>
          <div style={{ fontSize: 24, fontWeight: 800, color: 'var(--emerald-text)', fontFamily: 'var(--font-mono)', marginTop: 4 }}>
            +{fmt(results.savings)}
          </div>
          <div style={{ fontSize: 11.5, color: 'var(--emerald-text)', marginTop: 2 }}>
            {results.savingsPct}% reduction vs In-House
          </div>
        </div>

        <div className="panel" style={{ margin: 0 }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 700, letterSpacing: '0.04em' }}>
            PAYBACK PERIOD
          </div>
          <div style={{ fontSize: 24, fontWeight: 800, color: 'var(--cyan-text)', fontFamily: 'var(--font-mono)', marginTop: 4 }}>
            Day 1
          </div>
          <div style={{ fontSize: 11.5, color: 'var(--text-secondary)', marginTop: 2 }}>
            Immediate ($0 CapEx required)
          </div>
        </div>

        <div className="panel" style={{ margin: 0 }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 700, letterSpacing: '0.04em' }}>
            IN-HOUSE BREAK-EVEN
          </div>
          <div style={{ fontSize: 24, fontWeight: 800, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', marginTop: 4 }}>
            {results.buildBreakevenMonths ? `${results.buildBreakevenMonths.toFixed(1)} mo` : 'N/A'}
          </div>
          <div style={{ fontSize: 11.5, color: 'var(--text-secondary)', marginTop: 2 }}>
            To recoup initial dev CapEx
          </div>
        </div>

        <div className="panel" style={{ margin: 0 }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 700, letterSpacing: '0.04em' }}>
            MONTHLY OPEX RUN-RATE
          </div>
          <div style={{ fontSize: 24, fontWeight: 800, color: 'var(--emerald-text)', fontFamily: 'var(--font-mono)', marginTop: 4 }}>
            ${results.buyMonthly}/mo
          </div>
          <div style={{ fontSize: 11.5, color: 'var(--rose-text)', marginTop: 2 }}>
            vs {fmt(results.buildAnnualOp / 12)}/mo In-House
          </div>
        </div>
      </div>

      {/* Main Grid */}
      <main className="workspace-grid" style={{ marginTop: 0 }}>
        {/* Left Column: Financial Model Controls */}
        <section className="panel">
          <div className="panel-header">
            <div className="panel-title">
              <span>🎛️</span>
              <span>Model Parameters</span>
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              {SCENARIOS.map((s, idx) => (
                <button
                  key={idx}
                  type="button"
                  className="btn btn-ghost"
                  style={{ fontSize: 11, padding: '2px 8px' }}
                  onClick={() => {
                    setVolume(s.volume)
                    setHours(s.hours)
                    setHourlyCost(s.hourlyCost)
                    setInfra(s.infra)
                  }}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* Volume */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, fontWeight: 500 }}>
                <span>Monthly Document Volume</span>
                <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--cyan-text)', fontWeight: 700 }}>
                  {volume.toLocaleString()} docs/mo
                </span>
              </div>
              <input
                type="range"
                min={100}
                max={10000}
                step={100}
                value={volume}
                onChange={(e) => setVolume(Number(e.target.value))}
              />
            </div>

            {/* Build Hours */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, fontWeight: 500 }}>
                <span>Initial Engineering Build Hours</span>
                <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--cyan-text)', fontWeight: 700 }}>
                  {hours} hours
                </span>
              </div>
              <input
                type="range"
                min={50}
                max={500}
                step={10}
                value={hours}
                onChange={(e) => setHours(Number(e.target.value))}
              />
            </div>

            {/* Hourly Rate */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, fontWeight: 500 }}>
                <span>Loaded Developer Hourly Rate</span>
                <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--cyan-text)', fontWeight: 700 }}>
                  ${hourlyCost}/hr
                </span>
              </div>
              <input
                type="range"
                min={40}
                max={150}
                step={5}
                value={hourlyCost}
                onChange={(e) => setHourlyCost(Number(e.target.value))}
              />
            </div>

            {/* Infrastructure */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, fontWeight: 500 }}>
                <span>Monthly Infrastructure Overhead</span>
                <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--cyan-text)', fontWeight: 700 }}>
                  ${infra}/mo
                </span>
              </div>
              <input
                type="range"
                min={0}
                max={500}
                step={25}
                value={infra}
                onChange={(e) => setInfra(Number(e.target.value))}
              />
            </div>

            {/* Horizon */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, fontWeight: 500 }}>
                <span>Evaluation Horizon</span>
                <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--cyan-text)', fontWeight: 700 }}>
                  {horizon} Years
                </span>
              </div>
              <input
                type="range"
                min={1}
                max={5}
                step={1}
                value={horizon}
                onChange={(e) => setHorizon(Number(e.target.value))}
              />
            </div>
          </div>
        </section>

        {/* Right Column: Visual Comparison & Report */}
        <section className="panel" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="panel-header">
            <div className="panel-title">
              <span>📊</span>
              <span>Cost Comparison Visualizer</span>
            </div>
            <button
              type="button"
              className="btn btn-primary"
              disabled={downloading}
              onClick={handleDownload}
              style={{ fontWeight: 600, fontSize: 12 }}
            >
              {downloading ? (
                <>
                  <span className="spinner" />
                  <span>Compiling Cloud PDF</span>
                </>
              ) : (
                '📥 Download Executive Report'
              )}
            </button>
          </div>

          {downloading && (
            <div style={{
              background: 'var(--cyan-bg)',
              border: '1px solid var(--cyan-border)',
              borderRadius: 8,
              padding: '10px 14px',
              fontSize: 12,
              display: 'flex',
              alignItems: 'center',
              gap: 10,
            }}>
              <span className="spinner spinner-cyan" />
              <span style={{ color: 'var(--cyan-text)' }}>
                <b>SuperDocs Cloud Pipeline:</b> Synthesizing document structure & compiling vector PDF (~10-15s)
              </span>
            </div>
          )}

          {/* Visual Bars */}
          <div style={{
            background: 'var(--bg-surface-elevated)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 8,
            padding: '16px',
            display: 'flex',
            flexDirection: 'column',
            gap: 12,
          }}>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
                <span style={{ fontWeight: 600, color: 'var(--rose-text)' }}>In-House AI Pipeline (Build)</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{fmt(results.buildTotal)}</span>
              </div>
              <div style={{ height: 28, background: 'var(--bg-canvas)', borderRadius: 6, overflow: 'hidden' }}>
                <div style={{
                  width: `${buildPct}%`,
                  height: '100%',
                  background: 'linear-gradient(90deg, #f43f5e, #e11d48)',
                  borderRadius: 6,
                  display: 'flex',
                  alignItems: 'center',
                  paddingLeft: 10,
                  color: '#fff',
                  fontSize: 11,
                  fontWeight: 700,
                  fontFamily: 'var(--font-mono)',
                  minWidth: 80,
                  transition: 'width 0.2s ease',
                }}>
                  {fmt(results.buildTotal)}
                </div>
              </div>
            </div>

            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
                <span style={{ fontWeight: 600, color: 'var(--emerald-text)' }}>SuperDocs Plus (Buy)</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{fmt(results.buyTotal)}</span>
              </div>
              <div style={{ height: 28, background: 'var(--bg-canvas)', borderRadius: 6, overflow: 'hidden' }}>
                <div style={{
                  width: `${buyPct}%`,
                  height: '100%',
                  background: 'linear-gradient(90deg, #10b981, #059669)',
                  borderRadius: 6,
                  display: 'flex',
                  alignItems: 'center',
                  paddingLeft: 10,
                  color: '#fff',
                  fontSize: 11,
                  fontWeight: 700,
                  fontFamily: 'var(--font-mono)',
                  minWidth: 60,
                  transition: 'width 0.2s ease',
                }}>
                  {fmt(results.buyTotal)}
                </div>
              </div>
            </div>
          </div>

          {/* Financial Ledger Table */}
          <div style={{
            background: 'var(--bg-surface-elevated)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 8,
            overflow: 'hidden',
          }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
              <thead>
                <tr style={{ background: 'var(--bg-canvas)', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-muted)', fontSize: 11 }}>
                  <th style={{ textAlign: 'left', padding: '8px 12px' }}>LINE ITEM</th>
                  <th style={{ textAlign: 'right', padding: '8px 12px' }}>IN-HOUSE BUILD</th>
                  <th style={{ textAlign: 'right', padding: '8px 12px' }}>SUPERDOCS</th>
                </tr>
              </thead>
              <tbody>
                <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '8px 12px' }}>Initial Engineering CapEx</td>
                  <td style={{ textAlign: 'right', padding: '8px 12px', fontFamily: 'var(--font-mono)', color: 'var(--rose-text)' }}>{fmt(results.buildOneTime)}</td>
                  <td style={{ textAlign: 'right', padding: '8px 12px', fontFamily: 'var(--font-mono)', color: 'var(--emerald-text)' }}>$0</td>
                </tr>
                <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '8px 12px' }}>Annual Maintenance (20%)</td>
                  <td style={{ textAlign: 'right', padding: '8px 12px', fontFamily: 'var(--font-mono)' }}>{fmt(results.buildMaintPerYear)}/yr</td>
                  <td style={{ textAlign: 'right', padding: '8px 12px', fontFamily: 'var(--font-mono)', color: 'var(--emerald-text)' }}>Included</td>
                </tr>
                <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '8px 12px' }}>Annual Infrastructure Overhead</td>
                  <td style={{ textAlign: 'right', padding: '8px 12px', fontFamily: 'var(--font-mono)' }}>{fmt(results.buildInfraPerYear)}/yr</td>
                  <td style={{ textAlign: 'right', padding: '8px 12px', fontFamily: 'var(--font-mono)', color: 'var(--emerald-text)' }}>Included</td>
                </tr>
                <tr style={{ background: 'var(--bg-canvas)', fontWeight: 700 }}>
                  <td style={{ padding: '10px 12px' }}>{horizon}-Year Total TCO</td>
                  <td style={{ textAlign: 'right', padding: '10px 12px', fontFamily: 'var(--font-mono)', color: 'var(--rose-text)' }}>{fmt(results.buildTotal)}</td>
                  <td style={{ textAlign: 'right', padding: '10px 12px', fontFamily: 'var(--font-mono)', color: 'var(--emerald-text)' }}>{fmt(results.buyTotal)}</td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* Export Report Status */}
          {pdfPath && (
            <div style={{
              background: 'var(--emerald-bg)',
              border: '1px solid var(--emerald-border)',
              borderRadius: 6,
              padding: '8px 12px',
              fontSize: 12,
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}>
              <span style={{ color: 'var(--emerald-text)', fontFamily: 'var(--font-mono)' }}>
                PDF: {pdfPath}
              </span>
              <div style={{ display: 'flex', gap: 6 }}>
                {pdfDataUrl && (
                  <a
                    href={pdfDataUrl}
                    download={`SuperDocs-ROI-Report-${Date.now()}.pdf`}
                    className="btn btn-secondary"
                    style={{ fontSize: 11, padding: '2px 8px', textDecoration: 'none' }}
                  >
                    📥 Save PDF
                  </a>
                )}
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => {
                    navigator.clipboard.writeText(pdfPath)
                    setCopiedPath(true)
                    setTimeout(() => setCopiedPath(false), 2000)
                  }}
                  style={{ fontSize: 11, padding: '2px 6px' }}
                >
                  {copiedPath ? '✔ Copied' : '📋 Copy Path'}
                </button>
              </div>
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
